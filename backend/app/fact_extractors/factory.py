from __future__ import annotations

import os

from .base import FactExtractionProviderUnavailable, FactExtractor
from .local_rules import LocalRuleFactExtractor


class DisabledFactExtractor:
    name = "disabled"
    model_version = None

    def extract(self, messages):
        raise FactExtractionProviderUnavailable(
            "Fact extraction is disabled; review the conversation manually or configure a provider"
        )


def fact_extractor_from_environment() -> FactExtractor:
    provider = os.environ.get("FACT_EXTRACTION_PROVIDER", "disabled").strip().casefold()
    if provider in {"", "disabled"}:
        return DisabledFactExtractor()
    if provider in {"local_rules", "local-rules"}:
        return LocalRuleFactExtractor()
    return DisabledFactExtractor()
