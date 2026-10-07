from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..schemas import core as schemas


ModelT = TypeVar("ModelT")


class DomainNotFound(LookupError):
    pass


class DomainValidationError(ValueError):
    pass


class CoreDataService:
    """Persistence-level CRUD; cross-entity automation belongs in app services."""

    def __init__(self, session: Session):
        self.session = session

    def _get(self, model: type[ModelT], object_id: uuid.UUID) -> ModelT:
        value = self.session.get(model, object_id)
        if value is None:
            raise DomainNotFound(f"{model.__name__} not found")
        return value

    def _case(self, case_id: uuid.UUID) -> models.Case:
        return self._get(models.Case, case_id)

    def _belongs_to_case(self, model: type[ModelT], object_id: uuid.UUID | None, case_id: uuid.UUID, label: str) -> ModelT | None:
        if object_id is None:
            return None
        value = self._get(model, object_id)
        if value.case_id != case_id:
            raise DomainValidationError(f"{label} belongs to a different case")
        return value

    def _save(
        self, value: ModelT, *, before_commit: Callable[[ModelT], None] | None = None
    ) -> ModelT:
        self.session.add(value)
        try:
            if before_commit is not None:
                self.session.flush()
                before_commit(value)
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("record conflicts with existing data") from error
        self.session.refresh(value)
        return value

    def _update(self, value: ModelT, payload: BaseModel) -> ModelT:
        for key, item in payload.model_dump(exclude_unset=True).items():
            setattr(value, key, item)
        return self._save(value)

    def create_case(
        self,
        payload: schemas.CaseCreate,
        *,
        case_id: uuid.UUID | None = None,
        before_commit: Callable[[models.Case], None] | None = None,
    ) -> models.Case:
        values = payload.model_dump()
        if case_id is not None:
            values["id"] = case_id
        return self._save(models.Case(**values), before_commit=before_commit)

    def list_cases(self) -> list[models.Case]:
        return list(self.session.scalars(select(models.Case).order_by(models.Case.created_at)))

    def get_case(self, case_id: uuid.UUID) -> models.Case:
        return self._case(case_id)

    def update_case(self, case_id: uuid.UUID, payload: schemas.CaseUpdate) -> models.Case:
        return self._update(self._case(case_id), payload)

    def create_person(self, case_id: uuid.UUID, payload: schemas.PersonCreate) -> models.Person:
        self._case(case_id)
        return self._save(models.Person(case_id=case_id, **payload.model_dump()))

    def list_persons(self, case_id: uuid.UUID) -> list[models.Person]:
        self._case(case_id)
        return list(self.session.scalars(select(models.Person).where(models.Person.case_id == case_id).order_by(models.Person.created_at)))

    def get_person(self, person_id: uuid.UUID) -> models.Person:
        return self._get(models.Person, person_id)

    def update_person(self, person_id: uuid.UUID, payload: schemas.PersonUpdate) -> models.Person:
        return self._update(self.get_person(person_id), payload)

    def create_fact(self, case_id: uuid.UUID, payload: schemas.FactCreate) -> models.Fact:
        self._case(case_id)
        self._belongs_to_case(models.Person, payload.person_id, case_id, "person")
        return self._save(models.Fact(case_id=case_id, **payload.model_dump()))

    def list_facts(self, case_id: uuid.UUID) -> list[models.Fact]:
        self._case(case_id)
        return list(self.session.scalars(select(models.Fact).where(models.Fact.case_id == case_id).order_by(models.Fact.created_at)))

    def get_fact(self, fact_id: uuid.UUID) -> models.Fact:
        return self._get(models.Fact, fact_id)

    def update_fact(self, fact_id: uuid.UUID, payload: schemas.FactUpdate) -> models.Fact:
        fact = self.get_fact(fact_id)
        if "person_id" in payload.model_fields_set:
            self._belongs_to_case(models.Person, payload.person_id, fact.case_id, "person")
        return self._update(fact, payload)

    def create_requirement(self, case_id: uuid.UUID, payload: schemas.RequirementCreate) -> models.Requirement:
        self._case(case_id)
        self._belongs_to_case(models.Person, payload.owner_person_id, case_id, "owner person")
        return self._save(models.Requirement(case_id=case_id, **payload.model_dump()))

    def list_requirements(self, case_id: uuid.UUID) -> list[models.Requirement]:
        self._case(case_id)
        return list(self.session.scalars(select(models.Requirement).where(models.Requirement.case_id == case_id).order_by(models.Requirement.created_at)))

    def get_requirement(self, requirement_id: uuid.UUID) -> models.Requirement:
        return self._get(models.Requirement, requirement_id)

    def update_requirement(self, requirement_id: uuid.UUID, payload: schemas.RequirementUpdate) -> models.Requirement:
        requirement = self.get_requirement(requirement_id)
        if "owner_person_id" in payload.model_fields_set:
            self._belongs_to_case(models.Person, payload.owner_person_id, requirement.case_id, "owner person")
        changes = payload.model_dump(exclude_unset=True)
        previous_status = requirement.fulfillment_status
        if "fulfillment_status" in payload.model_fields_set:
            if payload.fulfillment_status == models.RequirementFulfillmentStatus.WAIVED:
                waiver_reason = payload.waiver_reason or requirement.waiver_reason
                if not waiver_reason:
                    raise DomainValidationError("waiving a requirement requires waiver_reason")
                changes["waived_at"] = datetime.now(timezone.utc)
                changes["fulfillment_source"] = models.RequirementFulfillmentSource.WAIVED
            else:
                changes.update({
                    "waiver_reason": None,
                    "waived_by": None,
                    "waived_at": None,
                })
                changes["fulfillment_source"] = (
                    models.RequirementFulfillmentSource.MANUAL
                    if payload.fulfillment_status == models.RequirementFulfillmentStatus.FULFILLED
                    else None
                )
            changes["fulfillment_updated_at"] = datetime.now(timezone.utc)
        for key, item in changes.items():
            setattr(requirement, key, item)
        if (
            "fulfillment_status" in payload.model_fields_set
            and payload.fulfillment_status is not None
            and payload.fulfillment_status != previous_status
        ):
            source = (
                models.RequirementFulfillmentSource.WAIVED
                if payload.fulfillment_status == models.RequirementFulfillmentStatus.WAIVED
                else models.RequirementFulfillmentSource.MANUAL
            )
            self.session.add(models.RequirementFulfillmentEvent(
                requirement_id=requirement.id,
                from_status=previous_status.value,
                to_status=payload.fulfillment_status.value,
                source=source,
                reason=payload.waiver_reason or "Manual requirement status update",
                actor=payload.waived_by,
                document_ids_json=[],
            ))
        saved = self._save(requirement)
        if (
            ("active" in payload.model_fields_set and payload.active is True)
            or "completeness_policy_json" in payload.model_fields_set
        ):
            from .quality import RequirementCompletenessService

            RequirementCompletenessService(self.session).evaluate(
                requirement.id, trigger="requirement_update"
            )
            self.session.refresh(saved)
        return saved

    def create_document(self, case_id: uuid.UUID, payload: schemas.DocumentCreate) -> models.Document:
        self._case(case_id)
        self._belongs_to_case(models.Person, payload.person_id, case_id, "person")
        return self._save(models.Document(case_id=case_id, **payload.model_dump()))

    def list_documents(self, case_id: uuid.UUID) -> list[models.Document]:
        self._case(case_id)
        return list(self.session.scalars(select(models.Document).where(models.Document.case_id == case_id).order_by(models.Document.created_at)))

    def get_document(self, document_id: uuid.UUID) -> models.Document:
        return self._get(models.Document, document_id)

    def update_document(self, document_id: uuid.UUID, payload: schemas.DocumentUpdate) -> models.Document:
        document = self.get_document(document_id)
        if "person_id" in payload.model_fields_set:
            self._belongs_to_case(models.Person, payload.person_id, document.case_id, "person")
        return self._update(document, payload)

    def create_task(self, case_id: uuid.UUID, payload: schemas.TaskCreate) -> models.Task:
        self._case(case_id)
        self._belongs_to_case(models.Requirement, payload.related_requirement_id, case_id, "requirement")
        self._belongs_to_case(models.Document, payload.related_document_id, case_id, "document")
        return self._save(models.Task(case_id=case_id, **payload.model_dump()))

    def list_tasks(self, case_id: uuid.UUID) -> list[models.Task]:
        self._case(case_id)
        return list(self.session.scalars(select(models.Task).where(models.Task.case_id == case_id).order_by(models.Task.created_at)))

    def get_task(self, task_id: uuid.UUID) -> models.Task:
        return self._get(models.Task, task_id)

    def update_task(self, task_id: uuid.UUID, payload: schemas.TaskUpdate) -> models.Task:
        task = self.get_task(task_id)
        if "related_requirement_id" in payload.model_fields_set:
            self._belongs_to_case(models.Requirement, payload.related_requirement_id, task.case_id, "requirement")
        if "related_document_id" in payload.model_fields_set:
            self._belongs_to_case(models.Document, payload.related_document_id, task.case_id, "document")
        return self._update(task, payload)
