from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..schemas import core as schemas
from .core import CoreDataService, DomainNotFound, DomainValidationError


PersonRole = Literal[
    "applicant", "sponsor", "host", "representative", "spouse", "child", "other"
]
RequirementLevel = Literal["required", "conditional", "supporting", "optional"]


class RuleConfigurationError(ValueError):
    """Raised when version-controlled rule configuration is invalid."""


class DocumentTypeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1)


class RequirementTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(min_length=1, max_length=128)
    owner_role: PersonRole
    requirement_level: RequirementLevel
    is_blocking: bool


class DocumentCatalogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    document_types: list[DocumentTypeDefinition]
    document_groups: dict[str, list[RequirementTemplate]]


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visa_type: str = Field(min_length=1)
    facts: dict[str, Any] = Field(default_factory=dict)


class RequirementRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1)
    when: RuleCondition
    add_groups: list[str]
    reason: str = Field(min_length=1)


class RuleSetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    rules: list[RequirementRule]


@dataclass(frozen=True)
class RuleCatalog:
    document_types: dict[str, DocumentTypeDefinition]
    document_groups: dict[str, tuple[RequirementTemplate, ...]]
    rules: tuple[RequirementRule, ...]

    @property
    def rule_ids(self) -> frozenset[str]:
        return frozenset(rule.id for rule in self.rules)


def validate_rule_configuration(
    document_data: dict[str, Any], rule_data: dict[str, Any]
) -> RuleCatalog:
    try:
        documents = DocumentCatalogConfig.model_validate(document_data)
        rules = RuleSetConfig.model_validate(rule_data)
    except ValidationError as error:
        raise RuleConfigurationError(f"malformed requirement rule configuration: {error}") from error

    document_ids = [item.id for item in documents.document_types]
    if len(document_ids) != len(set(document_ids)):
        raise RuleConfigurationError("duplicate document type ID")

    rule_ids = [rule.id for rule in rules.rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise RuleConfigurationError("duplicate rule ID")

    known_document_types = set(document_ids)
    for group_id, templates in documents.document_groups.items():
        if not group_id.strip():
            raise RuleConfigurationError("document group ID must not be empty")
        for template in templates:
            if template.document_type not in known_document_types:
                raise RuleConfigurationError(
                    f"unknown document type {template.document_type!r} in group {group_id!r}"
                )

    known_groups = set(documents.document_groups)
    for rule in rules.rules:
        unknown_groups = set(rule.add_groups) - known_groups
        if unknown_groups:
            raise RuleConfigurationError(
                f"unknown document group(s) in rule {rule.id!r}: "
                + ", ".join(sorted(unknown_groups))
            )

    return RuleCatalog(
        document_types={item.id: item for item in documents.document_types},
        document_groups={
            key: tuple(value) for key, value in documents.document_groups.items()
        },
        rules=tuple(rules.rules),
    )


def load_rule_catalog(config_root: Path | None = None) -> RuleCatalog:
    root = config_root or Path(__file__).resolve().parents[1] / "config"
    try:
        document_data = json.loads((root / "document_types.json").read_text(encoding="utf-8"))
        rule_data = json.loads((root / "rules" / "trv.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuleConfigurationError(f"cannot load requirement rule configuration: {error}") from error
    return validate_rule_configuration(document_data, rule_data)


DEFAULT_RULE_CATALOG = load_rule_catalog()


@dataclass(frozen=True)
class RequirementEvaluationResult:
    created: tuple[models.Requirement, ...]
    reactivated: tuple[models.Requirement, ...]
    deactivated: tuple[models.Requirement, ...]
    unchanged: tuple[models.Requirement, ...]


@dataclass(frozen=True)
class DesiredRequirement:
    rule_id: str
    document_type: str
    owner_role: str
    owner_person_id: uuid.UUID | None
    requirement_level: str
    reason: str
    is_blocking: bool

    @property
    def key(self) -> tuple[str, str, str]:
        return self.rule_id, self.document_type, self.owner_role


class RequirementEngine:
    """Derives auditable requirements from versioned rules and confirmed facts."""

    RELEVANT_FACT_KEYS = frozenset(
        fact_key for rule in DEFAULT_RULE_CATALOG.rules for fact_key in rule.when.facts
    )

    def __init__(self, session: Session, catalog: RuleCatalog = DEFAULT_RULE_CATALOG):
        self.session = session
        self.catalog = catalog

    def _case(self, case_id: uuid.UUID) -> models.Case:
        case = self.session.get(models.Case, case_id)
        if case is None:
            raise DomainNotFound("Case not found")
        return case

    def _confirmed_facts(self, case_id: uuid.UUID) -> dict[str, Any]:
        facts = list(self.session.scalars(
            select(models.Fact)
            .where(models.Fact.case_id == case_id, models.Fact.status == "confirmed")
            .order_by(models.Fact.created_at, models.Fact.id)
        ))
        return {fact.key: fact.value_json for fact in facts}

    def _owner_person_id(self, case_id: uuid.UUID, role: str) -> uuid.UUID | None:
        people = list(self.session.scalars(
            select(models.Person).where(models.Person.case_id == case_id)
        ))
        matches = [person for person in people if role in person.roles]
        return matches[0].id if len(matches) == 1 else None

    @staticmethod
    def _rule_applies(
        rule: RequirementRule, case: models.Case, confirmed_facts: dict[str, Any]
    ) -> bool:
        if case.visa_type.strip().upper() != rule.when.visa_type.strip().upper():
            return False
        return all(confirmed_facts.get(key) == expected for key, expected in rule.when.facts.items())

    def get_applicable_rules(self, case_id: uuid.UUID) -> tuple[RequirementRule, ...]:
        case = self._case(case_id)
        facts = self._confirmed_facts(case_id)
        return tuple(rule for rule in self.catalog.rules if self._rule_applies(rule, case, facts))

    def _desired_requirements(self, case_id: uuid.UUID) -> dict[tuple[str, str, str], DesiredRequirement]:
        desired: dict[tuple[str, str, str], DesiredRequirement] = {}
        for rule in self.get_applicable_rules(case_id):
            for group_id in rule.add_groups:
                for template in self.catalog.document_groups[group_id]:
                    item = DesiredRequirement(
                        rule_id=rule.id,
                        document_type=template.document_type,
                        owner_role=template.owner_role,
                        owner_person_id=self._owner_person_id(case_id, template.owner_role),
                        requirement_level=template.requirement_level,
                        reason=rule.reason,
                        is_blocking=template.is_blocking,
                    )
                    if item.key in desired:
                        raise DomainValidationError(
                            f"duplicate generated requirement identity for {item.key}"
                        )
                    desired[item.key] = item
        return desired

    def evaluate(self, case_id: uuid.UUID) -> RequirementEvaluationResult:
        self._case(case_id)
        desired = self._desired_requirements(case_id)
        generated = list(self.session.scalars(
            select(models.Requirement)
            .where(
                models.Requirement.case_id == case_id,
                models.Requirement.rule_id.is_not(None),
            )
            .order_by(models.Requirement.created_at, models.Requirement.id)
        ))
        existing: dict[tuple[str, str, str], models.Requirement] = {}
        for requirement in generated:
            key = (requirement.rule_id, requirement.document_type, requirement.owner_role)
            if key in existing:
                raise DomainValidationError(f"duplicate generated requirement identity for {key}")
            existing[key] = requirement

        created: list[models.Requirement] = []
        reactivated: list[models.Requirement] = []
        deactivated: list[models.Requirement] = []
        unchanged: list[models.Requirement] = []

        for key, item in desired.items():
            requirement = existing.get(key)
            if requirement is None:
                requirement = models.Requirement(
                    case_id=case_id,
                    document_type=item.document_type,
                    owner_role=item.owner_role,
                    owner_person_id=item.owner_person_id,
                    requirement_level=item.requirement_level,
                    rule_id=item.rule_id,
                    reason=item.reason,
                    is_blocking=item.is_blocking,
                    active=True,
                )
                self.session.add(requirement)
                created.append(requirement)
                continue

            requirement.owner_person_id = item.owner_person_id
            requirement.requirement_level = item.requirement_level
            requirement.reason = item.reason
            requirement.is_blocking = item.is_blocking
            if requirement.active:
                unchanged.append(requirement)
            else:
                requirement.active = True
                reactivated.append(requirement)

        for key, requirement in existing.items():
            if key in desired:
                continue
            if requirement.active:
                requirement.active = False
                deactivated.append(requirement)
            else:
                unchanged.append(requirement)

        self.session.commit()
        for requirement in (*created, *reactivated, *deactivated, *unchanged):
            self.session.refresh(requirement)
        from .quality import RequirementCompletenessService

        completeness = RequirementCompletenessService(self.session)
        reevaluate = [*reactivated]
        reevaluate.extend(
            requirement for requirement in unchanged
            if requirement.active and requirement.document_matches
        )
        for requirement in reevaluate:
            completeness.evaluate(requirement.id, trigger="requirement_rule_evaluation")
        return RequirementEvaluationResult(
            created=tuple(created),
            reactivated=tuple(reactivated),
            deactivated=tuple(deactivated),
            unchanged=tuple(unchanged),
        )


class CaseApplicationService:
    """Orchestrates CRUD mutations that must trigger deterministic rule evaluation."""

    def __init__(self, session: Session):
        self.core = CoreDataService(session)
        self.engine = RequirementEngine(session)

    def create_case(self, payload: schemas.CaseCreate) -> models.Case:
        case = self.core.create_case(payload)
        self.engine.evaluate(case.id)
        return case

    def update_case(
        self, case_id: uuid.UUID, payload: schemas.CaseUpdate
    ) -> models.Case:
        case = self.core.update_case(case_id, payload)
        self.engine.evaluate(case.id)
        return case

    def create_fact(
        self, case_id: uuid.UUID, payload: schemas.FactCreate
    ) -> models.Fact:
        fact = self.core.create_fact(case_id, payload)
        if fact.key in self.engine.RELEVANT_FACT_KEYS:
            self.engine.evaluate(case_id)
        return fact

    def create_person(
        self, case_id: uuid.UUID, payload: schemas.PersonCreate
    ) -> models.Person:
        person = self.core.create_person(case_id, payload)
        self.engine.evaluate(case_id)
        return person

    def update_person(
        self, person_id: uuid.UUID, payload: schemas.PersonUpdate
    ) -> models.Person:
        person = self.core.update_person(person_id, payload)
        self.engine.evaluate(person.case_id)
        return person

    def update_fact(
        self, fact_id: uuid.UUID, payload: schemas.FactUpdate
    ) -> models.Fact:
        before = self.core.get_fact(fact_id)
        old_key = before.key
        fact = self.core.update_fact(fact_id, payload)
        if old_key in self.engine.RELEVANT_FACT_KEYS or fact.key in self.engine.RELEVANT_FACT_KEYS:
            self.engine.evaluate(fact.case_id)
        return fact
