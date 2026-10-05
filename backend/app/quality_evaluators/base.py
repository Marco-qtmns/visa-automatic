from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class QualityContent:
    text: str
    page_count: int | None
    mime_type: str
    binary_content: bytes = field(repr=False)
    document_hash: str
    image_width: int | None = None
    image_height: int | None = None


@dataclass(frozen=True)
class ConfiguredQualityCheck:
    check_id: str
    label: str
    assessment: str


@dataclass(frozen=True)
class QualityCheckFinding:
    check_id: str
    status: str
    evidence: str | None
    issue: str | None
    evaluator: str
    confidence: float | None = None


@dataclass(frozen=True)
class TypeSpecificQualityResult:
    checks: list[QualityCheckFinding]
    extracted_metadata: dict[str, Any]


class TypeSpecificQualityEvaluator(Protocol):
    name: str
    version: str | None

    def evaluate(
        self,
        content: QualityContent,
        checks: tuple[ConfiguredQualityCheck, ...],
    ) -> TypeSpecificQualityResult: ...
