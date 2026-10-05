from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
import pytest

from backend.app.api.core import storage_provider
from backend.app.database import get_session
from backend.app.main import app
from backend.app.models import Document, RequirementFulfillmentStatus
from backend.app.schemas.core import RequirementUpdate
from backend.app.services import CoreDataService
from backend.app.storage import LocalStorageProvider


PDF_BYTES = b"%PDF-1.4\n% synthetic document\n%%EOF\n"


@pytest.fixture
def document_client(session, tmp_path):
    storage = LocalStorageProvider(tmp_path / "isolated-document-storage")

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[storage_provider] = lambda: storage
    try:
        yield TestClient(app), storage
    finally:
        app.dependency_overrides.clear()


def create_case(client: TestClient, number: str):
    response = client.post(
        "/cases",
        json={"case_number": number, "visa_type": "OTHER", "purpose": "synthetic"},
    )
    assert response.status_code == 201
    return response.json()


def create_person(client: TestClient, case_id: str, role: str, suffix: str):
    response = client.post(
        f"/cases/{case_id}/persons",
        json={"first_name": "Synthetic", "last_name": suffix, "roles": [role]},
    )
    assert response.status_code == 201
    return response.json()


def create_requirement(
    client: TestClient,
    case_id: str,
    person_id: str,
    *,
    document_type: str = "bank_statements",
):
    response = client.post(
        f"/cases/{case_id}/requirements",
        json={
            "document_type": document_type,
            "owner_role": "sponsor",
            "owner_person_id": person_id,
            "requirement_level": "required",
            "reason": "Synthetic manual requirement",
            "is_blocking": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def upload(
    client: TestClient,
    case_id: str,
    *,
    filename: str = "synthetic.pdf",
    content: bytes = PDF_BYTES,
    mime_type: str = "application/pdf",
    document_type: str | None = None,
    person_id: str | None = None,
):
    data: dict[str, str] = {}
    if document_type is not None:
        data["document_type"] = document_type
    if person_id is not None:
        data["person_id"] = person_id
    return client.post(
        f"/cases/{case_id}/documents/upload",
        data=data,
        files={"file": (filename, content, mime_type)},
    )


def assigned_document(client: TestClient, case_id: str, person_id: str):
    response = upload(
        client,
        case_id,
        document_type="bank_statements",
        person_id=person_id,
    )
    assert response.status_code == 201
    return response.json()


def test_upload_persists_file_with_opaque_key_and_downloads_bytes(
    document_client, session
):
    client, storage = document_client
    case = create_case(client, "M5-UPLOAD")
    response = upload(client, case["id"], filename="synthetic statement.pdf")
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "synthetic statement.pdf"
    assert body["document_type"] is None
    assert body["person_id"] is None
    assert "storage_path" not in body

    record = session.get(Document, uuid.UUID(body["id"]))
    assert record.storage_path != record.original_filename
    assert "/" not in record.storage_path
    assert storage.exists(record.storage_path)
    assert (storage.root / record.storage_path).read_bytes() == PDF_BYTES

    download = client.get(f"/documents/{body['id']}/content")
    assert download.status_code == 200
    assert download.content == PDF_BYTES
    assert download.headers["content-type"] == "application/pdf"


def test_assigned_upload_and_catalog_validation(document_client):
    client, _storage = document_client
    case = create_case(client, "M5-ASSIGNED")
    sponsor = create_person(client, case["id"], "sponsor", "Sponsor")
    response = upload(
        client,
        case["id"],
        document_type="bank_statements",
        person_id=sponsor["id"],
    )
    assert response.status_code == 201
    assert response.json()["document_type"] == "bank_statements"
    assert response.json()["person_id"] == sponsor["id"]

    invalid = upload(client, case["id"], document_type="bank-statement-guess")
    assert invalid.status_code == 409
    assert "unknown document type" in invalid.json()["detail"]


@pytest.mark.parametrize(
    "filename,content,mime_type",
    [
        ("synthetic.txt", b"synthetic text", "text/plain"),
        ("fake.pdf", b"not actually a PDF", "application/pdf"),
        ("image.png", b"\xff\xd8\xffsynthetic", "image/png"),
    ],
)
def test_unsupported_or_mismatched_file_is_rejected(
    document_client, filename, content, mime_type
):
    client, _storage = document_client
    case = create_case(client, f"M5-UNSUPPORTED-{filename}")
    response = upload(
        client, case["id"], filename=filename, content=content, mime_type=mime_type
    )
    assert response.status_code == 415
    assert response.json()["detail"] == "PDF, JPEG or PNG files are supported"


def test_upload_size_limit(document_client, monkeypatch):
    client, storage = document_client
    case = create_case(client, "M5-SIZE")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    response = upload(
        client,
        case["id"],
        content=b"%PDF-" + (b"x" * (1024 * 1024)),
    )
    assert response.status_code == 413
    assert "maximum upload size" in response.json()["detail"]
    assert list(storage.root.iterdir()) == []


def test_path_traversal_and_filename_collisions_are_safe(document_client, session):
    client, storage = document_client
    case = create_case(client, "M5-PATH")
    first = upload(client, case["id"], filename="../../passport.pdf")
    second = upload(client, case["id"], filename="../../passport.pdf")
    assert first.status_code == second.status_code == 201
    assert first.json()["original_filename"] == "passport.pdf"
    first_record = session.get(Document, uuid.UUID(first.json()["id"]))
    second_record = session.get(Document, uuid.UUID(second.json()["id"]))
    assert first_record.storage_path != second_record.storage_path
    assert (storage.root / first_record.storage_path).parent == storage.root
    assert (storage.root / second_record.storage_path).parent == storage.root


def test_exact_type_and_owner_match_listing_and_unmatch(document_client):
    client, _storage = document_client
    case = create_case(client, "M5-MATCH")
    sponsor = create_person(client, case["id"], "sponsor", "Sponsor")
    requirement = create_requirement(client, case["id"], sponsor["id"])
    document = assigned_document(client, case["id"], sponsor["id"])

    candidates = client.get(
        f"/documents/{document['id']}/matching-requirements"
    ).json()
    assert [item["id"] for item in candidates] == [requirement["id"]]
    match = client.post(
        f"/requirements/{requirement['id']}/documents/{document['id']}",
        json={"created_by": "synthetic.employee", "note": "Manual review"},
    )
    assert match.status_code == 201
    assert match.json()["created_by"] == "synthetic.employee"
    assert client.get(
        f"/requirements/{requirement['id']}/documents"
    ).json()[0]["document"]["id"] == document["id"]
    assert client.get(
        f"/documents/{document['id']}/requirements"
    ).json()[0]["requirement"]["id"] == requirement["id"]

    removed = client.delete(
        f"/requirements/{requirement['id']}/documents/{document['id']}"
    )
    assert removed.status_code == 204
    assert client.get(f"/requirements/{requirement['id']}/documents").json() == []


def test_wrong_type_wrong_owner_cross_case_and_duplicate_are_rejected(document_client):
    client, _storage = document_client
    first_case = create_case(client, "M5-COMPAT-A")
    second_case = create_case(client, "M5-COMPAT-B")
    sponsor = create_person(client, first_case["id"], "sponsor", "Sponsor")
    applicant = create_person(client, first_case["id"], "applicant", "Applicant")
    other_sponsor = create_person(client, second_case["id"], "sponsor", "Other")
    requirement = create_requirement(client, first_case["id"], sponsor["id"])
    second_requirement = create_requirement(
        client, second_case["id"], other_sponsor["id"]
    )

    wrong_type = upload(
        client,
        first_case["id"],
        document_type="digital_photo",
        person_id=sponsor["id"],
        filename="synthetic.jpg",
        content=b"\xff\xd8\xffsynthetic",
        mime_type="image/jpeg",
    ).json()
    wrong_person = assigned_document(client, first_case["id"], applicant["id"])
    correct = assigned_document(client, first_case["id"], sponsor["id"])

    for document, expected in (
        (wrong_type, "document type does not match"),
        (wrong_person, "document owner does not match"),
    ):
        response = client.post(
            f"/requirements/{requirement['id']}/documents/{document['id']}", json={}
        )
        assert response.status_code == 409
        assert expected in response.json()["detail"]

    cross_case = client.post(
        f"/requirements/{second_requirement['id']}/documents/{correct['id']}", json={}
    )
    assert cross_case.status_code == 409
    assert "different cases" in cross_case.json()["detail"]

    path = f"/requirements/{requirement['id']}/documents/{correct['id']}"
    assert client.post(path, json={}).status_code == 201
    duplicate = client.post(path, json={})
    assert duplicate.status_code == 409
    assert "already matched" in duplicate.json()["detail"]


def test_role_based_owner_compatibility_when_requirement_person_is_unresolved(
    document_client,
):
    client, _storage = document_client
    case = create_case(client, "M5-ROLE-OWNER")
    sponsor = create_person(client, case["id"], "sponsor", "Sponsor")
    applicant = create_person(client, case["id"], "applicant", "Applicant")
    requirement_response = client.post(
        f"/cases/{case['id']}/requirements",
        json={
            "document_type": "bank_statements",
            "owner_role": "sponsor",
            "owner_person_id": None,
            "requirement_level": "required",
            "reason": "Synthetic unresolved owner",
        },
    )
    requirement = requirement_response.json()
    sponsor_document = assigned_document(client, case["id"], sponsor["id"])
    applicant_document = assigned_document(client, case["id"], applicant["id"])

    assert client.post(
        f"/requirements/{requirement['id']}/documents/{sponsor_document['id']}",
        json={},
    ).status_code == 201
    rejected = client.post(
        f"/requirements/{requirement['id']}/documents/{applicant_document['id']}",
        json={},
    )
    assert rejected.status_code == 409
    assert "required role" in rejected.json()["detail"]


def test_many_to_many_matching_and_no_auto_fulfilment(document_client):
    client, _storage = document_client
    case = create_case(client, "M5-MANY")
    sponsor = create_person(client, case["id"], "sponsor", "Sponsor")
    first_requirement = create_requirement(client, case["id"], sponsor["id"])
    second_requirement = create_requirement(client, case["id"], sponsor["id"])
    first_document = assigned_document(client, case["id"], sponsor["id"])
    second_document = assigned_document(client, case["id"], sponsor["id"])

    for requirement_id, document_id in (
        (first_requirement["id"], first_document["id"]),
        (first_requirement["id"], second_document["id"]),
        (second_requirement["id"], first_document["id"]),
    ):
        assert client.post(
            f"/requirements/{requirement_id}/documents/{document_id}", json={}
        ).status_code == 201

    assert len(client.get(
        f"/requirements/{first_requirement['id']}/documents"
    ).json()) == 2
    assert len(client.get(
        f"/documents/{first_document['id']}/requirements"
    ).json()) == 2
    reloaded = client.get(f"/requirements/{first_requirement['id']}").json()
    assert reloaded["fulfillment_status"] == "pending"


def test_inactive_requirement_preserves_match_and_metadata_change_is_safe(
    document_client, session
):
    client, _storage = document_client
    case = create_case(client, "M5-HISTORY")
    sponsor = create_person(client, case["id"], "sponsor", "Sponsor")
    applicant = create_person(client, case["id"], "applicant", "Applicant")
    requirement = create_requirement(client, case["id"], sponsor["id"])
    document = assigned_document(client, case["id"], sponsor["id"])
    match_path = f"/requirements/{requirement['id']}/documents/{document['id']}"
    assert client.post(match_path, json={}).status_code == 201

    CoreDataService(session).update_requirement(
        uuid.UUID(requirement["id"]), RequirementUpdate(active=False)
    )
    assert len(client.get(f"/requirements/{requirement['id']}/documents").json()) == 1
    assert client.post(match_path, json={}).status_code == 409

    invalid_change = client.patch(
        f"/documents/{document['id']}", json={"person_id": applicant["id"]}
    )
    assert invalid_change.status_code == 409
    assert "remove incompatible document matches" in invalid_change.json()["detail"]
    unchanged = client.get(f"/documents/{document['id']}").json()
    assert unchanged["person_id"] == sponsor["id"]


def test_unassigned_upload_surfaces_existing_next_action(document_client):
    client, _storage = document_client
    response = client.post(
        "/cases",
        json={"case_number": "M5-NEXT", "visa_type": "TRV", "purpose": "tourism"},
    )
    case = response.json()
    for key in ("sponsor.exists", "host.exists"):
        client.post(
            f"/cases/{case['id']}/facts",
            json={
                "key": key,
                "value_json": False,
                "source_type": "manual",
                "source_reference": "synthetic next-action fixture",
                "status": "confirmed",
            },
        )
    document = upload(client, case["id"]).json()
    action = client.get(f"/cases/{case['id']}/next-action").json()
    assert action["type"] == "ASSIGN_DOCUMENT"
    assert action["document_id"] == document["id"]


def test_document_type_catalog_is_exposed(document_client):
    client, _storage = document_client
    catalog = client.get("/document-types")
    assert catalog.status_code == 200
    assert {item["id"] for item in catalog.json()} >= {
        "passport_bio_page",
        "bank_statements",
    }
