from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app import models
from backend.app.api.core import fact_extraction_provider
from backend.app.conversation_parsers import WhatsAppConversationParser
from backend.app.database import get_session
from backend.app.fact_extractors import (
    DisabledFactExtractor,
    ExtractedFactCandidate,
    FactExtractionProviderError,
    LocalRuleFactExtractor,
    fact_extractor_from_environment,
)
from backend.app.main import app


CHAT = """[02/10/2026, 09:15:00] Applicant: My father will pay for the trip.
[02/10/2026, 09:16:00] Applicant: I will stay with my sister in Toronto.
This is a multiline detail.
"""


@dataclass
class FakeExtractor:
    output: list[ExtractedFactCandidate] = field(default_factory=list)
    fail: bool = False
    name: str = "synthetic_fake"
    model_version: str = "test-v1"

    def extract(self, messages):
        if self.fail:
            raise FactExtractionProviderError("Synthetic provider failure")
        resolved = []
        for item in self.output:
            ids = [messages[index - 1].id for index in map(int, item.source_message_ids)]
            resolved.append(ExtractedFactCandidate(
                item.key, item.value, item.confidence, ids, item.evidence
            ))
        return resolved


@pytest.fixture
def conversation_client(session):
    extractor = FakeExtractor()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[fact_extraction_provider] = lambda: extractor
    try:
        yield TestClient(app), extractor
    finally:
        app.dependency_overrides.clear()


def create_case(client, suffix):
    response = client.post("/cases", json={
        "case_number": f"M8-{suffix}", "visa_type": "TRV", "purpose": "Synthetic visit"
    })
    assert response.status_code == 201
    return response.json()


def paste(client, case, text=CHAT):
    response = client.post(
        f"/cases/{case['id']}/conversations/whatsapp/paste",
        json={"text": text, "imported_by": "test.employee"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def candidate(key, value, message="1", evidence="Synthetic evidence", confidence=.9):
    return ExtractedFactCandidate(key, value, confidence, [message], evidence)


def extract(client, conversation):
    response = client.post(f"/conversations/{conversation['id']}/extract-facts")
    assert response.status_code == 201, response.text
    return response.json()


def candidates(client, conversation):
    return client.get(f"/conversations/{conversation['id']}/fact-candidates").json()


def test_parser_preserves_sequence_sender_timestamp_multiline_and_warnings():
    parsed = WhatsAppConversationParser().parse(
        "[02/10/2026, 09:15:00] A: First line\ncontinued\n"
        "10/2/26, 9:16 AM - B: Second\n2026/99/99 unsupported"
    )
    assert [(item.sequence_number, item.sender) for item in parsed.messages[:2]] == [(1, "A"), (2, "B")]
    assert parsed.messages[0].timestamp.year == 2026
    assert parsed.messages[0].text == "First line\ncontinued"
    assert parsed.warnings
    assert parsed.messages[-1].text == "2026/99/99 unsupported"


def test_paste_and_txt_import_are_traceable_and_duplicate_is_controlled(conversation_client):
    client, _ = conversation_client
    case = create_case(client, "IMPORT")
    imported = paste(client, case)
    assert imported["source_type"] == "whatsapp_paste" and imported["message_count"] == 2
    messages = client.get(f"/conversations/{imported['id']}/messages").json()
    assert messages[0]["sender"] == "Applicant"
    assert messages[1]["text"].endswith("multiline detail.")
    duplicate = client.post(
        f"/cases/{case['id']}/conversations/whatsapp/paste", json={"text": CHAT}
    )
    assert duplicate.status_code == 409 and "already imported" in duplicate.json()["detail"]

    uploaded = client.post(
        f"/cases/{case['id']}/conversations/whatsapp/upload",
        data={"imported_by": "test.employee"},
        files={"file": ("synthetic.txt", CHAT.replace("father", "mother").encode(), "text/plain")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["source_type"] == "whatsapp_export"
    assert uploaded.json()["original_filename"] == "synthetic.txt"


def test_txt_import_rejects_binary_wrong_type_and_oversize(conversation_client, monkeypatch):
    client, _ = conversation_client
    case = create_case(client, "UPLOAD-SAFETY")
    binary = client.post(
        f"/cases/{case['id']}/conversations/whatsapp/upload",
        files={"file": ("synthetic.txt", b"text\x00binary", "text/plain")},
    )
    assert binary.status_code == 415
    wrong = client.post(
        f"/cases/{case['id']}/conversations/whatsapp/upload",
        files={"file": ("synthetic.pdf", b"plain", "application/pdf")},
    )
    assert wrong.status_code == 415
    monkeypatch.setenv("MAX_CONVERSATION_IMPORT_MB", "1")
    large = client.post(
        f"/cases/{case['id']}/conversations/whatsapp/upload",
        files={"file": ("large.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
    )
    assert large.status_code == 413


def test_structured_extraction_validates_catalog_provenance_evidence_and_confidence(conversation_client, session):
    client, extractor = conversation_client
    case = create_case(client, "EXTRACT")
    conversation = paste(client, case)
    extractor.output = [
        candidate("sponsor.exists", True, evidence="My father will pay", confidence=.97),
        candidate("unsupported.key", "invented"),
        candidate("host.exists", True, confidence=1.5),
    ]
    run = extract(client, conversation)
    assert run["status"] == "completed" and run["candidate_count"] == 1
    assert run["rejected_output_count"] == 2
    found = candidates(client, conversation)
    assert found[0]["key"] == "sponsor.exists"
    assert found[0]["evidence"] == "My father will pay"
    assert found[0]["confidence"] == .97
    assert session.get(models.ConversationMessage, uuid.UUID(found[0]["source_message_ids_json"][0]))


def test_local_rules_handle_sponsor_negation_host_independence_and_payer():
    parser = WhatsAppConversationParser()
    parsed = parser.parse(
        "[02/10/2026, 09:00] A: My father will not pay for the trip.\n"
        "[02/10/2026, 09:01] A: I will stay with my sister in Toronto.\n"
        "[02/10/2026, 09:02] A: My father will pay for the trip."
    )
    messages = [
        type("Message", (), {"id": str(item.sequence_number), "sequence_number": item.sequence_number, "sender": item.sender, "text": item.text})
        for item in parsed.messages
    ]
    output = LocalRuleFactExtractor().extract(messages)
    assert not any(item.key == "sponsor.exists" and item.value is True and item.source_message_ids == ["1"] for item in output)
    assert any(item.key == "host.exists" and item.value is True for item in output)
    assert not any(item.key == "sponsor.exists" and item.source_message_ids == ["2"] for item in output)
    assert any(item.key == "trip.payer" and item.value == "sponsor" for item in output)


def test_extraction_never_creates_person_or_document_and_repeated_runs_deduplicate(conversation_client):
    client, extractor = conversation_client
    case = create_case(client, "BOUNDARIES")
    conversation = paste(client, case, "[02/10/2026, 09:00] Client: I sent my bank statement")
    extractor.output = [candidate("trip.payer", "sponsor")]
    first = extract(client, conversation)
    second = extract(client, conversation)
    assert first["candidate_count"] == 1
    assert second["candidate_count"] == 0 and second["rejected_output_count"] == 1
    assert len(client.get(f"/conversations/{conversation['id']}/extraction-runs").json()) == 2
    assert client.get(f"/cases/{case['id']}/persons").json() == []
    assert client.get(f"/cases/{case['id']}/documents").json() == []


def test_same_value_accept_reuses_fact_without_false_conflict(conversation_client, session):
    client, extractor = conversation_client
    case = create_case(client, "CONSISTENT")
    existing = client.post(f"/cases/{case['id']}/facts", json={
        "person_id": None, "key": "sponsor.exists", "value_json": True,
        "source_type": "google_form", "source_reference": "Synthetic form", "confidence": 1, "status": "confirmed",
    }).json()
    conversation = paste(client, case)
    extractor.output = [candidate("sponsor.exists", True)]
    extract(client, conversation)
    item = candidates(client, conversation)[0]
    assert item["status"] == "proposed" and item["conflicting_fact_id"] is None
    accepted = client.post(f"/fact-candidates/{item['id']}/accept", json={
        "reviewed_by": "employee", "reason": "Consistent supporting evidence"
    }).json()
    assert accepted["authoritative_fact_id"] == existing["id"]
    facts = session.scalars(select(models.Fact).where(
        models.Fact.case_id == uuid.UUID(case["id"]), models.Fact.key == "sponsor.exists"
    )).all()
    assert len(facts) == 1


def test_conflict_accept_preserves_old_fact_and_triggers_requirements_without_workflow_change(conversation_client, session):
    client, extractor = conversation_client
    case = create_case(client, "CONFLICT")
    old = client.post(f"/cases/{case['id']}/facts", json={
        "person_id": None, "key": "sponsor.exists", "value_json": False,
        "source_type": "google_form", "source_reference": "Synthetic form", "confidence": 1, "status": "confirmed",
    }).json()
    conversation = paste(client, case)
    extractor.output = [candidate("sponsor.exists", True, evidence="Father pays")]
    extract(client, conversation)
    item = candidates(client, conversation)[0]
    assert item["status"] == "conflict" and item["conflicting_fact_id"] == old["id"]
    action = client.get(f"/cases/{case['id']}/next-action").json()
    assert action["type"] == "REVIEW_FACT_CANDIDATE" and action["fact_candidate_id"] == item["id"]
    before = client.get(f"/cases/{case['id']}").json()["workflow_state"]
    reviewed = client.post(f"/fact-candidates/{item['id']}/accept", json={
        "reviewed_by": "employee", "reason": "Client correction confirmed"
    }).json()
    after = client.get(f"/cases/{case['id']}").json()["workflow_state"]
    assert before == after
    assert session.get(models.Fact, uuid.UUID(old["id"])).status == "rejected"
    new_fact = session.get(models.Fact, uuid.UUID(reviewed["authoritative_fact_id"]))
    assert new_fact.value_json is True and new_fact.source_type == "whatsapp"
    requirements = client.get(f"/cases/{case['id']}/requirements").json()
    assert any(item["rule_id"] == "TRV_SPONSOR_BANK_001" and item["active"] for item in requirements)


def test_correct_preserves_prediction_and_reject_leaves_facts_unchanged(conversation_client, session):
    client, extractor = conversation_client
    case = create_case(client, "DECISIONS")
    conversation = paste(client, case)
    extractor.output = [candidate("trip.payer", "other"), candidate("host.exists", True, message="2")]
    extract(client, conversation)
    found = {item["key"]: item for item in candidates(client, conversation)}
    corrected = client.post(f"/fact-candidates/{found['trip.payer']['id']}/correct", json={
        "reviewed_by": "employee", "reason": "Clarified by employee", "value_json": "applicant"
    }).json()
    assert corrected["status"] == "corrected"
    assert corrected["value_json"] == "other" and corrected["corrected_value_json"] == "applicant"
    fact = session.get(models.Fact, uuid.UUID(corrected["authoritative_fact_id"]))
    assert fact.value_json == "applicant" and "fact-candidate:" in fact.source_reference
    rejected = client.post(f"/fact-candidates/{found['host.exists']['id']}/reject", json={
        "reviewed_by": "employee", "reason": "Message was misunderstood"
    }).json()
    assert rejected["status"] == "rejected"
    assert not session.scalars(select(models.Fact).where(
        models.Fact.case_id == uuid.UUID(case["id"]), models.Fact.key == "host.exists"
    )).all()


def test_provider_disabled_or_failure_preserves_import_and_manual_workflow(conversation_client):
    client, extractor = conversation_client
    case = create_case(client, "FAILURE")
    conversation = paste(client, case)
    extractor.fail = True
    run = extract(client, conversation)
    assert run["status"] == "failed" and "Synthetic provider failure" in run["failure_reason"]
    assert client.get(f"/cases/{case['id']}/conversations").json()[0]["id"] == conversation["id"]
    manual = client.post(f"/cases/{case['id']}/facts", json={
        "person_id": None, "key": "host.exists", "value_json": False,
        "source_type": "manual", "source_reference": "Employee entry", "confidence": None, "status": "confirmed",
    })
    assert manual.status_code == 201


def test_fact_extraction_provider_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FACT_EXTRACTION_PROVIDER", raising=False)
    assert isinstance(fact_extractor_from_environment(), DisabledFactExtractor)


def test_privacy_raw_chat_is_not_logged(conversation_client, caplog):
    client, _ = conversation_client
    case = create_case(client, "PRIVACY")
    secret = "Synthetic private phrase 932847"
    paste(client, case, f"[02/10/2026, 09:00] Client: {secret}")
    assert secret not in caplog.text
