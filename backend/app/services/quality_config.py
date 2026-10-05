from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..quality_evaluators import ConfiguredQualityCheck
from .requirements import DEFAULT_RULE_CATALOG


class QualityConfigurationError(ValueError):
    pass


class QualityCheckConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=500)
    assessment: str = Field(pattern="^(manual|candidate_text_manual|candidate_period_manual)$")


class QualityProfilesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    profiles: dict[str, list[QualityCheckConfig]]


def load_quality_profiles(path: Path | None = None) -> dict[str, tuple[ConfiguredQualityCheck, ...]]:
    source = path or Path(__file__).resolve().parents[1] / "config" / "quality" / "document_quality.json"
    try:
        parsed = QualityProfilesConfig.model_validate_json(source.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError) as error:
        raise QualityConfigurationError(f"invalid quality configuration: {error}") from error
    expected = set(DEFAULT_RULE_CATALOG.document_types)
    configured = set(parsed.profiles)
    if configured != expected:
        missing = sorted(expected - configured)
        unknown = sorted(configured - expected)
        raise QualityConfigurationError(
            f"quality profiles must match document catalog; missing={missing}, unknown={unknown}"
        )
    result: dict[str, tuple[ConfiguredQualityCheck, ...]] = {}
    for document_type, checks in parsed.profiles.items():
        ids = [check.check_id for check in checks]
        if len(ids) != len(set(ids)):
            raise QualityConfigurationError(f"duplicate quality check ID for {document_type}")
        result[document_type] = tuple(
            ConfiguredQualityCheck(**check.model_dump()) for check in checks
        )
    return result


DEFAULT_QUALITY_PROFILES = load_quality_profiles()
