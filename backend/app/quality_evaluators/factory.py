from __future__ import annotations

import os

from .base import TypeSpecificQualityEvaluator
from .manual import ManualOnlyQualityEvaluator


def quality_evaluator_from_environment() -> TypeSpecificQualityEvaluator:
    provider = os.environ.get("QUALITY_PROVIDER", "").strip().casefold()
    if provider in {"", "disabled", "manual_only", "manual-only"}:
        return ManualOnlyQualityEvaluator()
    # Unknown providers fail closed to employee review instead of transmitting data.
    return ManualOnlyQualityEvaluator()
