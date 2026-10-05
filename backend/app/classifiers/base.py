from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ClassificationProviderError(RuntimeError):
    """Controlled provider failure without exposing document content."""


class ClassificationProviderUnavailable(ClassificationProviderError):
    pass


@dataclass(frozen=True)
class ExtractedDocumentContent:
    text: str
    page_count: int | None
    mime_type: str
    binary_content: bytes = field(repr=False)
    document_hash: str


@dataclass(frozen=True)
class ClassificationEvidenceItem:
    type: str
    value: str


@dataclass(frozen=True)
class ClassifierResult:
    document_type: str | None
    owner_name: str | None
    confidence: float | None
    evidence: list[ClassificationEvidenceItem]


class DocumentClassifier(Protocol):
    """Vendor-neutral classifier boundary used by the application service."""

    name: str
    model_version: str | None

    def classify(self, content: ExtractedDocumentContent) -> ClassifierResult: ...
