from __future__ import annotations

import os

from .base import (
    ClassificationProviderUnavailable,
    ClassifierResult,
    DocumentClassifier,
    ExtractedDocumentContent,
)
from .local_text import LocalTextDocumentClassifier


class UnavailableDocumentClassifier:
    name = "disabled"
    model_version = None

    def __init__(self, reason: str = "Classification provider is not configured"):
        self.reason = reason

    def classify(self, content: ExtractedDocumentContent) -> ClassifierResult:
        raise ClassificationProviderUnavailable(self.reason)


def classifier_from_environment() -> DocumentClassifier:
    provider = os.environ.get("AI_PROVIDER", "").strip().casefold()
    if provider in {"local_text", "local-text"}:
        return LocalTextDocumentClassifier()
    if not provider or provider == "disabled":
        return UnavailableDocumentClassifier()
    return UnavailableDocumentClassifier(
        f"Configured classification provider '{provider}' is not supported"
    )
