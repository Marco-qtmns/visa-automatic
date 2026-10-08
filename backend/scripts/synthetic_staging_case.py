"""Create and generate one wholly synthetic D1 staging case."""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import date
from io import BytesIO

from sqlalchemy import func, select

from backend.app import models
from backend.app.config.canada_preparation_policy import OFFICIAL_QUESTION_CODES
from backend.app.database import SessionLocal
from backend.app.integrations.canada_forms import LegacyCanadaFormGeneratorAdapter
from backend.app.models import canada as cm
from backend.app.schemas import core as schemas
from backend.app.services.documents import DocumentUploadService
from backend.app.services.preparation_runs import CanadaPreparationService
from backend.app.services.requirements import CaseApplicationService
from backend.app.services.workflow import WorkflowService
from backend.app.storage import LocalStorageProvider


def create_synthetic_case(*, continuation: bool) -> dict[str, object]:
    suffix = uuid.uuid4().hex[:10]
    document_storage = LocalStorageProvider.from_environment()
    generated_storage = LocalStorageProvider.generated_from_environment()
    with SessionLocal() as session:
        application_service = CaseApplicationService(session)
        case = application_service.create_case(schemas.CaseCreate(
            case_number=f"SYN-D1-{suffix}", visa_type="TRV", purpose="Synthetic staging visit",
        ))
        applicant = application_service.create_person(case.id, schemas.PersonCreate(
            first_name="Amina", last_name="Synthetic", roles=["applicant"],
        ))
        representative = application_service.create_person(case.id, schemas.PersonCreate(
            first_name="Rita", last_name="Synthetic-Representative", roles=["representative"],
        ))
        for key, value in (
            ("sponsor.exists", False), ("host.exists", False), ("trip.payer", "applicant"),
        ):
            application_service.create_fact(case.id, schemas.FactCreate(
                person_id=applicant.id, key=key, value_json=value,
                source_type="manual", source_reference="synthetic-d1-smoke", status="confirmed",
            ))

        canada_application = cm.CanadaApplication(
            case_id=case.id, applicant_person_id=applicant.id,
            official_application_date=date(2026, 10, 15),
            application_date_review_state="confirmed", mailing_same_as_residential=False,
            preferred_language_code="en",
        )
        session.add(canada_application); session.flush()
        session.add_all([
            cm.PersonBiography(person_id=applicant.id, date_of_birth=date(1992, 4, 17), sex="female", birth_city="Synthetic City", birth_country_code="CHE", marital_status="single"),
            cm.PersonCitizenship(person_id=applicant.id, country_code="CHE", is_primary=True, sort_order=0),
            cm.ApplicantResidence(application_id=canada_application.id, country_code="CHE", immigration_status_code="citizen", is_current=True),
            cm.ContactPoint(person_id=applicant.id, type="email", value="amina@example.invalid", purpose="primary", is_primary=True, sort_order=0),
            cm.ContactPoint(person_id=applicant.id, type="phone", value="5550100", country_code="+41", purpose="primary", is_primary=True, sort_order=0),
            cm.Address(application_id=canada_application.id, context="residential", owner_id=canada_application.id, street_number="1", street_name="Teststrasse", city="Synthetic City", state_province="ZH", postal_code="8000", country_code="CHE", review_state="confirmed"),
            cm.Address(application_id=canada_application.id, context="mailing", owner_id=canada_application.id, street_number="2", street_name="Exampleweg", city="Synthetic City", state_province="ZH", postal_code="8001", country_code="CHE", review_state="confirmed"),
        ])
        passport = cm.TravelDocument(
            application_id=canada_application.id, person_id=applicant.id,
            document_type="passport", number=f"SYN{suffix.upper()}", issuing_country_code="CHE",
            issue_date=date(2024, 1, 1), expiry_date=date(2034, 1, 1), is_primary=True, sort_order=0,
        )
        session.add_all([
            passport,
            cm.TripPlan(application_id=canada_application.id, intake_purpose_text="Synthetic visit", imm5257_purpose_code="Tourism", purpose_review_state="confirmed", arrival_date=date(2027, 1, 10), departure_date=date(2027, 1, 24), available_funds_amount=5000, available_funds_currency="CAD", funds_source_reference="Synthetic personal savings"),
            cm.ActivityRecord(application_id=canada_application.id, person_id=applicant.id, activity_type="employment", position="Synthetic Analyst", organization_name="Example Invalid AG", start_date=date(2020, 1, 1), period_status="current", city="Synthetic City", country_code="CHE", sort_order=0),
        ])
        if continuation:
            session.add(cm.ResidenceHistoryRecord(
                application_id=canada_application.id, person_id=applicant.id,
                country_code="FRA", status_or_purpose="synthetic visitor",
                start_date=date(2024, 1, 1), end_date=date(2024, 2, 1),
                review_state="confirmed", sort_order=0,
            ))
        for code in OFFICIAL_QUESTION_CODES:
            session.add(cm.OfficialApplicationAnswer(
                application_id=canada_application.id, question_code=code,
                answer="no", review_state="confirmed", reviewed_by="synthetic-d1-smoke",
            ))
        profile = cm.RepresentativeProfile(profile_name=f"Synthetic D1 representative {suffix}")
        session.add(profile); session.flush()
        revision = cm.RepresentativeProfileRevision(
            profile_id=profile.id, revision_number=1,
            family_name="Synthetic-Representative", given_names="Rita",
            street_name="Example Street", city="Synthetic City", province="ZH",
            country_code="CHE", postal_code="8000", phone_number="5550199",
            email="representative@example.invalid", category="Unpaid - friend or family",
            created_by="synthetic-d1-smoke",
        )
        session.add(revision); session.flush()
        session.add(cm.RepresentativeAuthorization(
            application_id=canada_application.id, representative_person_id=representative.id,
            profile_revision_id=revision.id, action="Appoint a representative",
            review_state="confirmed", reviewed_by="synthetic-d1-smoke",
        ))
        session.commit()

        document = DocumentUploadService(session, document_storage).upload(
            case.id, BytesIO(b"%PDF-1.4\n% Synthetic D1 fixture only\n%%EOF\n"),
            original_filename="synthetic-passport-fixture.pdf",
            declared_mime_type="application/pdf", document_type="passport_bio_page",
            person_id=applicant.id,
        )

        workflow = WorkflowService(session, generated_storage)
        workflow.transition(case.id, models.WorkflowState.DOCUMENTS, actor="synthetic-d1-smoke")
        workflow.transition(case.id, models.WorkflowState.PREPARE, actor="synthetic-d1-smoke")
        requirement_count = session.scalar(
            select(func.count()).select_from(models.Requirement).where(
                models.Requirement.case_id == case.id
            )
        )
        if not requirement_count:
            raise RuntimeError("synthetic fixture did not exercise requirements")
        preparation = CanadaPreparationService(
            session, generated_storage, LegacyCanadaFormGeneratorAdapter()
        )
        run = preparation.prepare(case.id, initiated_by="synthetic-d1-smoke")
        status = preparation.status(case.id)
        if status.package_status != "current":
            raise RuntimeError("synthetic package did not become current")
        artifacts = preparation.artifacts(run.id)
        return {
            "case_id": str(case.id), "case_number": case.case_number,
            "document_id": str(document.id), "run_id": str(run.id),
            "workflow_state": case.workflow_state.value,
            "package_status": status.package_status,
            "continuation_requested": continuation,
            "requirement_count": requirement_count,
            "artifact_types": sorted(item.artifact_type for item in artifacts),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation", action="store_true")
    args = parser.parse_args()
    print(json.dumps(create_synthetic_case(continuation=args.continuation), sort_keys=True))


if __name__ == "__main__":
    main()
