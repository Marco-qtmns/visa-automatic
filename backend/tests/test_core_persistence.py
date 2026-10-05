from __future__ import annotations

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import Case
from backend.app.schemas.core import (
    CaseCreate,
    DocumentCreate,
    FactCreate,
    PersonCreate,
    RequirementCreate,
    TaskCreate,
)
from backend.app.services import CoreDataService


def create_case(service: CoreDataService, number: str = "CA-2026-00142"):
    return service.create_case(CaseCreate(
        case_number=number,
        visa_type="TRV",
        purpose="family_visit",
    ))


def test_case_creation_and_reload(session):
    case = create_case(CoreDataService(session))
    session.expire_all()
    reloaded = session.get(Case, case.id)
    assert reloaded.case_number == "CA-2026-00142"
    assert reloaded.workflow_state == "INTAKE"


def test_person_creation_and_multiple_roles(session):
    service = CoreDataService(session)
    case = create_case(service)
    person = service.create_person(case.id, PersonCreate(
        first_name="Carlos", last_name="Silva", roles=["host", "sponsor"]
    ))
    session.expire_all()
    assert service.get_person(person.id).roles == ["host", "sponsor"]
    assert service.get_person(person.id).case_id == case.id


def test_fact_json_provenance_and_status_persist(session):
    service = CoreDataService(session)
    case = create_case(service)
    fact = service.create_fact(case.id, FactCreate(
        key="trip.details",
        value_json={"payer": "sponsor", "travellers": 2},
        source_type="google_form",
        source_reference="response:42/question:trip_payer",
        confidence=0.98,
        status="confirmed",
    ))
    session.expire_all()
    reloaded = service.get_fact(fact.id)
    assert reloaded.value_json == {"payer": "sponsor", "travellers": 2}
    assert (reloaded.source_type, reloaded.status) == ("google_form", "confirmed")


def test_requirement_document_and_task_are_distinct_and_related(session):
    service = CoreDataService(session)
    case = create_case(service)
    sponsor = service.create_person(case.id, PersonCreate(
        first_name="Joao", last_name="Silva", roles=["sponsor"]
    ))
    requirement = service.create_requirement(case.id, RequirementCreate(
        document_type="bank_statements",
        owner_role="sponsor",
        owner_person_id=sponsor.id,
        requirement_level="required",
        rule_id=None,
        reason="Manually requested by employee",
        is_blocking=True,
    ))
    document = service.create_document(case.id, DocumentCreate(
        person_id=sponsor.id,
        document_type="bank_statements",
        original_filename="statements.pdf",
        storage_path="cases/CA-2026-00142/statements.pdf",
        mime_type="application/pdf",
        source_type="manual_upload",
        metadata_json={"pages": 3},
    ))
    task = service.create_task(case.id, TaskCreate(
        type="review_document",
        title="Review sponsor statements",
        blocking=True,
        related_requirement_id=requirement.id,
        related_document_id=document.id,
    ))
    session.expire_all()
    assert service.get_requirement(requirement.id).owner_person_id == sponsor.id
    assert service.get_document(document.id).metadata_json == {"pages": 3}
    assert service.get_task(task.id).related_requirement_id == requirement.id
    assert service.get_task(task.id).related_document_id == document.id
    assert len(service.list_requirements(case.id)) == 1
    assert len(service.list_documents(case.id)) == 1


def test_complete_acceptance_case_survives_database_restart(tmp_path):
    database_path = tmp_path / "acceptance.db"

    def engine_and_factory():
        engine = create_engine(f"sqlite+pysqlite:///{database_path}")
        event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
        return engine, sessionmaker(bind=engine, expire_on_commit=False)

    engine, factory = engine_and_factory()
    Base.metadata.create_all(engine)
    with factory() as session:
        service = CoreDataService(session)
        case = create_case(service, "CA-2026-ACCEPTANCE")
        applicant = service.create_person(case.id, PersonCreate(first_name="Maria", last_name="Silva", roles=["applicant"]))
        sponsor = service.create_person(case.id, PersonCreate(first_name="Antonio", last_name="Silva", roles=["sponsor"]))
        host = service.create_person(case.id, PersonCreate(first_name="Ana", last_name="Costa", roles=["host"]))
        service.create_person(case.id, PersonCreate(first_name="Rita", last_name="Law", roles=["representative"]))
        for key, value in (("sponsor.exists", True), ("host.exists", True), ("trip.payer", "sponsor")):
            service.create_fact(case.id, FactCreate(
                person_id=applicant.id,
                key=key,
                value_json=value,
                source_type="manual",
                source_reference="acceptance fixture",
                status="confirmed",
            ))
        sponsor_requirement = service.create_requirement(case.id, RequirementCreate(
            document_type="bank_statements", owner_role="sponsor", owner_person_id=sponsor.id,
            requirement_level="required", reason="Manual acceptance example", is_blocking=True,
        ))
        service.create_requirement(case.id, RequirementCreate(
            document_type="invitation_letter", owner_role="host", owner_person_id=host.id,
            requirement_level="supporting", reason="Manual acceptance example", is_blocking=False,
        ))
        document = service.create_document(case.id, DocumentCreate(
            person_id=sponsor.id, document_type="bank_statements", original_filename="bank.pdf",
            storage_path="cases/acceptance/bank.pdf", mime_type="application/pdf",
            source_type="google_form", metadata_json={"form_field": "sponsor_documents"},
        ))
        service.create_document(case.id, DocumentCreate(
            person_id=applicant.id, document_type="passport", original_filename="passport.pdf",
            storage_path="cases/acceptance/passport.pdf", mime_type="application/pdf",
            source_type="google_form",
        ))
        service.create_task(case.id, TaskCreate(
            type="request_document", title="Request host invitation", status="open", blocking=False,
            related_requirement_id=sponsor_requirement.id,
        ))
        service.create_task(case.id, TaskCreate(
            type="review_document", title="Review bank statements", status="in_progress", blocking=True,
            related_document_id=document.id,
        ))
        case_id = case.id
    engine.dispose()

    restarted_engine, restarted_factory = engine_and_factory()
    with restarted_factory() as session:
        case = session.scalar(select(Case).where(Case.id == case_id))
        assert case.case_number == "CA-2026-ACCEPTANCE"
        assert {role for person in case.persons for role in person.roles} == {
            "applicant", "sponsor", "host", "representative"
        }
        assert {fact.key: fact.value_json for fact in case.facts} == {
            "sponsor.exists": True,
            "host.exists": True,
            "trip.payer": "sponsor",
        }
        assert len(case.requirements) == 2
        assert len(case.documents) == 2
        assert len(case.tasks) == 2
        assert case.tasks[1].related_document.person.id == sponsor.id
    restarted_engine.dispose()
