from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class FactExtractionProviderError(RuntimeError):
    pass


class FactExtractionProviderUnavailable(FactExtractionProviderError):
    pass


@dataclass(frozen=True)
class ExtractionMessage:
    id: str
    sequence_number: int
    sender: str | None
    text: str


@dataclass(frozen=True)
class ExtractedFactCandidate:
    key: str
    value: Any
    confidence: float
    source_message_ids: list[str]
    evidence: str


class FactExtractor(Protocol):
    name: str
    model_version: str | None

    def extract(self, messages: list[ExtractionMessage]) -> list[ExtractedFactCandidate]: ...
