from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..conversation_parsers import WhatsAppConversationParser
from ..fact_extractors import ExtractionMessage, FactExtractor
from ..schemas import core as schemas
from .core import CoreDataService, DomainNotFound, DomainValidationError
from .fact_catalog import DEFAULT_FACT_CATALOG, FactCatalogError
from .requirements import RequirementEngine


class DuplicateConversationImport(DomainValidationError):
    pass


class ConversationImportService:
    def __init__(self, session: Session, parser: WhatsAppConversationParser | None = None):
        self.session = session
        self.core = CoreDataService(session)
        self.parser = parser or WhatsAppConversationParser()

    def import_text(
        self,
        case_id: uuid.UUID,
        text: str,
        *,
        source_type: models.ConversationSourceType,
        imported_by: str | None = None,
        original_filename: str | None = None,
    ) -> models.ConversationImport:
        self.core.get_case(case_id)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
        if not normalized.strip():
            raise DomainValidationError("conversation text must not be empty")
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        existing = self.session.scalar(select(models.ConversationImport).where(
            models.ConversationImport.case_id == case_id,
            models.ConversationImport.content_hash == content_hash,
        ))
        if existing is not None:
            raise DuplicateConversationImport(
                f"conversation was already imported as {existing.id}"
            )
        parsed = self.parser.parse(normalized)
        if not parsed.messages:
            raise DomainValidationError("conversation contains no parseable text messages")
        conversation = models.ConversationImport(
            case_id=case_id,
            source_type=source_type,
            original_filename=original_filename,
            imported_by=imported_by,
            content_hash=content_hash,
            raw_text=normalized,
            parse_status=(
                models.ConversationParseStatus.PARSED_WITH_WARNINGS
                if parsed.warnings else models.ConversationParseStatus.PARSED
            ),
            parse_warnings_json=parsed.warnings,
            message_count=len(parsed.messages),
        )
        self.session.add(conversation)
        self.session.flush()
        for item in parsed.messages:
            self.session.add(models.ConversationMessage(
                conversation_import_id=conversation.id,
                case_id=case_id,
                sequence_number=item.sequence_number,
                sender=item.sender,
                message_timestamp=item.timestamp,
                text=item.text,
                source_reference=f"conversation:{conversation.id};message:{item.sequence_number}",
            ))
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DuplicateConversationImport("conversation was already imported") from error
        self.session.refresh(conversation)
        return conversation

    def get(self, conversation_id: uuid.UUID) -> models.ConversationImport:
        conversation = self.session.get(models.ConversationImport, conversation_id)
        if conversation is None:
            raise DomainNotFound("ConversationImport not found")
        return conversation

    def list_case(self, case_id: uuid.UUID) -> list[models.ConversationImport]:
        self.core.get_case(case_id)
        return list(self.session.scalars(select(models.ConversationImport).where(
            models.ConversationImport.case_id == case_id
        ).order_by(models.ConversationImport.imported_at.desc(), models.ConversationImport.id.desc())))

    def list_messages(self, conversation_id: uuid.UUID) -> list[models.ConversationMessage]:
        self.get(conversation_id)
        return list(self.session.scalars(select(models.ConversationMessage).where(
            models.ConversationMessage.conversation_import_id == conversation_id
        ).order_by(models.ConversationMessage.sequence_number)))


class ConversationFactExtractionService:
    def __init__(self, session: Session, extractor: FactExtractor):
        self.session = session
        self.extractor = extractor
        self.imports = ConversationImportService(session)
        self.core = CoreDataService(session)

    def extract(self, conversation_id: uuid.UUID) -> models.FactExtractionRun:
        conversation = self.imports.get(conversation_id)
        messages = self.imports.list_messages(conversation_id)
        run = models.FactExtractionRun(
            conversation_import_id=conversation_id,
            provider=self.extractor.name[:64],
            model_version=(self.extractor.model_version or None),
            status=models.FactExtractionRunStatus.RUNNING,
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        try:
            provider_messages = [ExtractionMessage(
                id=str(message.id), sequence_number=message.sequence_number,
                sender=message.sender, text=message.text,
            ) for message in messages]
            output = self.extractor.extract(provider_messages)
            message_ids = {str(message.id) for message in messages}
            valid: list[tuple[object, object]] = []
            rejected = 0
            existing_candidates = self.list_candidates(conversation_id)
            seen: set[str] = {
                f"{item.key}:{item.value_json!r}:{','.join(sorted(item.source_message_ids_json))}"
                for item in existing_candidates
            }
            for item in output:
                definition = DEFAULT_FACT_CATALOG.facts.get(item.key)
                if definition is None:
                    rejected += 1
                    continue
                try:
                    value = definition.validate_value(item.value)
                except FactCatalogError:
                    rejected += 1
                    continue
                if (
                    not math.isfinite(item.confidence)
                    or not 0 <= item.confidence <= 1
                    or not item.source_message_ids
                    or not set(item.source_message_ids) <= message_ids
                    or not item.evidence.strip()
                ):
                    rejected += 1
                    continue
                identity = f"{item.key}:{value!r}:{','.join(sorted(item.source_message_ids))}"
                if identity in seen:
                    rejected += 1
                    continue
                seen.add(identity)
                valid.append((item, value))

            values_by_key: dict[str, set[str]] = {}
            for item, value in valid:
                values_by_key.setdefault(item.key, set()).add(repr(value))
            for item, value in valid:
                current = self._latest_confirmed(conversation.case_id, item.key)
                conflict = (
                    (current is not None and current.value_json != value)
                    or len(values_by_key[item.key]) > 1
                )
                self.session.add(models.FactExtractionCandidate(
                    case_id=conversation.case_id,
                    conversation_import_id=conversation.id,
                    extraction_run_id=run.id,
                    key=item.key,
                    value_json=value,
                    confidence=item.confidence,
                    evidence=item.evidence.strip()[:500],
                    source_message_ids_json=item.source_message_ids,
                    provider=self.extractor.name[:64],
                    model_version=self.extractor.model_version,
                    status=(models.FactCandidateStatus.CONFLICT if conflict else models.FactCandidateStatus.PROPOSED),
                    conflicting_fact_id=current.id if current is not None and current.value_json != value else None,
                ))
            run.status = models.FactExtractionRunStatus.COMPLETED
            run.candidate_count = len(valid)
            run.rejected_output_count = rejected
            run.completed_at = datetime.now(timezone.utc)
            self.session.commit()
        except Exception as error:
            self.session.rollback()
            run = self.session.get(models.FactExtractionRun, run.id)
            if run is None:
                raise
            run.status = models.FactExtractionRunStatus.FAILED
            run.failure_reason = self._safe_failure(error)
            run.completed_at = datetime.now(timezone.utc)
            self.session.commit()
        self.session.refresh(run)
        return run

    def list_runs(self, conversation_id: uuid.UUID) -> list[models.FactExtractionRun]:
        self.imports.get(conversation_id)
        return list(self.session.scalars(select(models.FactExtractionRun).where(
            models.FactExtractionRun.conversation_import_id == conversation_id
        ).order_by(models.FactExtractionRun.created_at.desc(), models.FactExtractionRun.id.desc())))

    def list_candidates(self, conversation_id: uuid.UUID) -> list[models.FactExtractionCandidate]:
        self.imports.get(conversation_id)
        return list(self.session.scalars(select(models.FactExtractionCandidate).where(
            models.FactExtractionCandidate.conversation_import_id == conversation_id
        ).order_by(models.FactExtractionCandidate.created_at.desc(), models.FactExtractionCandidate.id.desc())))

    def accept(self, candidate_id: uuid.UUID, payload: schemas.FactCandidateReview):
        return self._confirm(candidate_id, payload.reviewed_by, payload.reason, corrected=False)

    def correct(self, candidate_id: uuid.UUID, payload: schemas.FactCandidateCorrection):
        return self._confirm(
            candidate_id, payload.reviewed_by, payload.reason,
            corrected=True, corrected_value=payload.value_json,
        )

    def reject(self, candidate_id: uuid.UUID, payload: schemas.FactCandidateReview):
        candidate = self._reviewable(candidate_id)
        candidate.status = models.FactCandidateStatus.REJECTED
        candidate.reviewed_by = payload.reviewed_by
        candidate.review_reason = payload.reason
        candidate.reviewed_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(candidate)
        return candidate

    def _confirm(self, candidate_id, reviewed_by, reason, *, corrected, corrected_value=None):
        candidate = self._reviewable(candidate_id)
        definition = DEFAULT_FACT_CATALOG.facts[candidate.key]
        value = definition.validate_value(corrected_value if corrected else candidate.value_json)
        current = self._latest_confirmed(candidate.case_id, candidate.key)
        if current is not None and current.value_json == value:
            fact = current
        else:
            if definition.singleton:
                confirmed = self.session.scalars(select(models.Fact).where(
                    models.Fact.case_id == candidate.case_id,
                    models.Fact.key == candidate.key,
                    models.Fact.status == "confirmed",
                ))
                for old in confirmed:
                    old.status = "rejected"
            fact = models.Fact(
                case_id=candidate.case_id,
                person_id=None,
                key=candidate.key,
                value_json=value,
                source_type="whatsapp",
                source_reference=(
                    f"conversation:{candidate.conversation_import_id};"
                    f"fact-candidate:{candidate.id};"
                    f"messages:{','.join(candidate.source_message_ids_json)}"
                ),
                confidence=candidate.confidence,
                status="confirmed",
            )
            self.session.add(fact)
            self.session.flush()
        candidate.status = (
            models.FactCandidateStatus.CORRECTED if corrected else models.FactCandidateStatus.ACCEPTED
        )
        candidate.corrected_value_json = value if corrected else None
        candidate.authoritative_fact_id = fact.id
        candidate.reviewed_by = reviewed_by
        candidate.review_reason = reason
        candidate.reviewed_at = datetime.now(timezone.utc)
        self.session.commit()
        RequirementEngine(self.session).evaluate(candidate.case_id)
        self.session.refresh(candidate)
        return candidate

    def _reviewable(self, candidate_id: uuid.UUID) -> models.FactExtractionCandidate:
        candidate = self.session.get(models.FactExtractionCandidate, candidate_id)
        if candidate is None:
            raise DomainNotFound("FactExtractionCandidate not found")
        if candidate.status not in {
            models.FactCandidateStatus.PROPOSED, models.FactCandidateStatus.CONFLICT
        }:
            raise DomainValidationError("fact candidate is not awaiting review")
        return candidate

    def _latest_confirmed(self, case_id, key):
        return self.session.scalar(select(models.Fact).where(
            models.Fact.case_id == case_id,
            models.Fact.key == key,
            models.Fact.status == "confirmed",
        ).order_by(models.Fact.created_at.desc(), models.Fact.id.desc()).limit(1))

    @staticmethod
    def _safe_failure(error: Exception) -> str:
        if error.__class__.__name__ in {"FactExtractionProviderUnavailable", "FactExtractionProviderError"}:
            return str(error)[:255]
        return "Fact extraction could not be completed"
