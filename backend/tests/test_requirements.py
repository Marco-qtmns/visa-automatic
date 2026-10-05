from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend.app.database import get_session
from backend.app.main import app
from backend.app.models import RequirementFulfillmentStatus
from backend.app.schemas.core import (
    CaseCreate,
    FactCreate,
    FactUpdate,
    PersonCreate,
    RequirementCreate,
    RequirementUpdate,
)
from backend.app.services import CoreDataService, RequirementEngine, RuleConfigurationError
from backend.app.services.requirements import DEFAULT_RULE_CATALOG, validate_rule_configuration
from backend.app.services.workflow import WorkflowService


def make_case(session, number="CA-RULE-001"):
    return CoreDataService(session).create_case(CaseCreate(
        case_number=number, visa_type="TRV", purpose="tourism"
    ))


def add_fact(session, case_id, key, value, status="confirmed"):
    return CoreDataService(session).create_fact(case_id, FactCreate(
        key=key,
        value_json=value,
        source_type="manual",
        source_reference="synthetic requirement fixture",
        status=status,
    ))


def generated(session, case_id):
    return [item for item in CoreDataService(session).list_requirements(case_id) if item.rule_id]


def sponsor_requirements(session, case_id):
    return [item for item in generated(session, case_id) if item.owner_role == "sponsor"]


def raw_configs():
    documents = {
        "version": 1,
        "document_types": [{"id": "known", "label": "Known"}],
        "document_groups": {
            "base": [{
                "document_type": "known",
                "owner_role": "applicant",
                "requirement_level": "supporting",
                "is_blocking": False,
            }]
        },
    }
    rules = {
        "version": 1,
        "rules": [{
            "id": "RULE_1",
            "description": "Synthetic rule",
            "when": {"visa_type": "TRV", "facts": {}},
            "add_groups": ["base"],
            "reason": "Synthetic configuration test",
        }],
    }
    return documents, rules


def test_base_trv_rule_and_provenance(session):
    case = make_case(session)
    result = RequirementEngine(session).evaluate(case.id)
    assert len(result.created) == 4
    assert {item.document_type for item in result.created} == {
        "passport_bio_page", "identity_document", "civil_status_document", "digital_photo"
    }
    assert all(item.rule_id == "TRV_BASE_INTERNAL_001" for item in result.created)
    assert all(item.requirement_level == "supporting" for item in result.created)
    assert all(item.is_blocking is False for item in result.created)
    assert all("internal checklist" in item.reason for item in result.created)


def test_evaluation_is_idempotent(session):
    case = make_case(session)
    engine = RequirementEngine(session)
    engine.evaluate(case.id)
    second = engine.evaluate(case.id)
    assert not second.created
    assert len(second.unchanged) == 4
    assert len(generated(session, case.id)) == 4


@pytest.mark.parametrize("value,status", [
    (False, "confirmed"),
    (True, "proposed"),
    (True, "conflict"),
    (True, "rejected"),
])
def test_unconfirmed_or_false_sponsor_does_not_activate_requirements(
    session, value, status
):
    case = make_case(session, f"CA-SPONSOR-{status}-{value}")
    add_fact(session, case.id, "sponsor.exists", value, status)
    RequirementEngine(session).evaluate(case.id)
    assert sponsor_requirements(session, case.id) == []


def test_confirmed_sponsor_activates_requirement_and_resolves_owner(session):
    core = CoreDataService(session)
    case = make_case(session)
    sponsor = core.create_person(case.id, PersonCreate(
        first_name="Synthetic", last_name="Sponsor", roles=["sponsor"]
    ))
    add_fact(session, case.id, "sponsor.exists", True)
    RequirementEngine(session).evaluate(case.id)
    requirements = sponsor_requirements(session, case.id)
    assert len(requirements) == 1
    assert requirements[0].document_type == "bank_statements"
    assert requirements[0].owner_person_id == sponsor.id
    assert requirements[0].rule_id == "TRV_SPONSOR_BANK_001"
    assert requirements[0].is_blocking is True


def test_sponsor_without_unique_person_keeps_owner_unassigned(session):
    case = make_case(session)
    add_fact(session, case.id, "sponsor.exists", True)
    RequirementEngine(session).evaluate(case.id)
    assert sponsor_requirements(session, case.id)[0].owner_person_id is None


def test_person_creation_automatically_resolves_generated_owner(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        case = client.post("/cases", json={
            "case_number": "CA-RULE-OWNER", "visa_type": "TRV", "purpose": "tourism"
        }).json()
        client.post(f"/cases/{case['id']}/facts", json={
            "key": "sponsor.exists",
            "value_json": True,
            "source_type": "manual",
            "source_reference": "synthetic owner fixture",
            "status": "confirmed",
        })
        before = client.get(f"/cases/{case['id']}/requirements").json()
        sponsor_before = next(
            item for item in before if item["rule_id"] == "TRV_SPONSOR_BANK_001"
        )
        assert sponsor_before["owner_person_id"] is None

        person = client.post(f"/cases/{case['id']}/persons", json={
            "first_name": "Synthetic",
            "last_name": "Sponsor",
            "roles": ["sponsor"],
        })
        assert person.status_code == 201
        after = client.get(f"/cases/{case['id']}/requirements").json()
        sponsor_after = next(
            item for item in after if item["rule_id"] == "TRV_SPONSOR_BANK_001"
        )
        assert sponsor_after["owner_person_id"] == person.json()["id"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("host_exists", [False, True])
def test_host_branch_is_structural_and_invents_no_requirements(session, host_exists):
    case = make_case(session, f"CA-HOST-{host_exists}")
    add_fact(session, case.id, "host.exists", host_exists)
    engine = RequirementEngine(session)
    engine.evaluate(case.id)
    assert all(item.owner_role != "host" for item in generated(session, case.id))
    applicable = {rule.id for rule in engine.get_applicable_rules(case.id)}
    assert ("TRV_HOST_BRANCH_001" in applicable) is host_exists


def test_fact_change_deactivates_and_reactivates_without_duplicate(session):
    core = CoreDataService(session)
    case = make_case(session)
    fact = add_fact(session, case.id, "sponsor.exists", False)
    engine = RequirementEngine(session)
    engine.evaluate(case.id)
    core.update_fact(fact.id, FactUpdate(value_json=True))
    activated = engine.evaluate(case.id)
    requirement = sponsor_requirements(session, case.id)[0]
    requirement_id = requirement.id
    assert requirement in activated.created
    core.update_fact(fact.id, FactUpdate(value_json=False))
    deactivated = engine.evaluate(case.id)
    assert deactivated.deactivated[0].id == requirement_id
    assert deactivated.deactivated[0].active is False
    core.update_fact(fact.id, FactUpdate(value_json=True))
    reactivated = engine.evaluate(case.id)
    assert reactivated.reactivated[0].id == requirement_id
    assert len(sponsor_requirements(session, case.id)) == 1


def test_manual_requirement_is_preserved(session):
    core = CoreDataService(session)
    case = make_case(session)
    manual = core.create_requirement(case.id, RequirementCreate(
        document_type="employee_note",
        owner_role="applicant",
        requirement_level="optional",
        reason="Synthetic employee request",
        is_blocking=False,
    ))
    RequirementEngine(session).evaluate(case.id)
    session.refresh(manual)
    assert manual.active is True
    assert manual.rule_id is None


@pytest.mark.parametrize("status", ["fulfilled", "waived"])
def test_fulfilment_survives_reevaluation_deactivation_and_reactivation(session, status):
    core = CoreDataService(session)
    case = make_case(session, f"CA-FULFIL-{status}")
    fact = add_fact(session, case.id, "sponsor.exists", True)
    engine = RequirementEngine(session)
    engine.evaluate(case.id)
    requirement = sponsor_requirements(session, case.id)[0]
    payload = RequirementUpdate(fulfillment_status=status)
    if status == "waived":
        payload = RequirementUpdate(
            fulfillment_status="waived",
            waiver_reason="Synthetic equivalent evidence accepted",
            waived_by="employee.test",
        )
    core.update_requirement(requirement.id, payload)
    core.update_fact(fact.id, FactUpdate(value_json=False))
    engine.evaluate(case.id)
    core.update_fact(fact.id, FactUpdate(value_json=True))
    engine.evaluate(case.id)
    reloaded = core.get_requirement(requirement.id)
    assert reloaded.fulfillment_status == RequirementFulfillmentStatus(status)
    if status == "waived":
        assert reloaded.waiver_reason == "Synthetic equivalent evidence accepted"


def test_invalid_unknown_document_type_fails_validation():
    documents, rules = raw_configs()
    documents["document_groups"]["base"][0]["document_type"] = "unknown"
    with pytest.raises(RuleConfigurationError, match="unknown document type"):
        validate_rule_configuration(documents, rules)


def test_duplicate_rule_id_fails_validation():
    documents, rules = raw_configs()
    rules["rules"].append(deepcopy(rules["rules"][0]))
    with pytest.raises(RuleConfigurationError, match="duplicate rule ID"):
        validate_rule_configuration(documents, rules)


def test_unknown_group_and_malformed_condition_fail_validation():
    documents, rules = raw_configs()
    rules["rules"][0]["add_groups"] = ["missing"]
    with pytest.raises(RuleConfigurationError, match="unknown document group"):
        validate_rule_configuration(documents, rules)
    documents, rules = raw_configs()
    rules["rules"][0]["when"] = {"facts": {}}
    with pytest.raises(RuleConfigurationError, match="malformed"):
        validate_rule_configuration(documents, rules)


def test_next_action_uses_new_blocking_requirement(session):
    case = make_case(session)
    add_fact(session, case.id, "sponsor.exists", True)
    add_fact(session, case.id, "host.exists", False)
    RequirementEngine(session).evaluate(case.id)
    action = WorkflowService(session).get_next_action(case.id)
    assert action.type == "RESOLVE_REQUIREMENT"
    assert action.requirement_id == sponsor_requirements(session, case.id)[0].id


def test_evaluation_api_returns_structured_changes_and_fact_mutation_is_automatic(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        case = client.post("/cases", json={
            "case_number": "CA-RULE-API", "visa_type": "TRV", "purpose": "tourism"
        }).json()
        initial = client.post(f"/cases/{case['id']}/requirements/evaluate")
        assert initial.status_code == 200
        assert len(initial.json()["unchanged"]) == 4
        fact = client.post(f"/cases/{case['id']}/facts", json={
            "key": "sponsor.exists",
            "value_json": True,
            "source_type": "manual",
            "source_reference": "synthetic API fixture",
            "status": "confirmed",
        })
        assert fact.status_code == 201
        requirements = client.get(f"/cases/{case['id']}/requirements").json()
        assert any(item["rule_id"] == "TRV_SPONSOR_BANK_001" for item in requirements)
    finally:
        app.dependency_overrides.clear()
