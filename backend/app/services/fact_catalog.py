from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class FactCatalogError(ValueError):
    pass


class FactDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=255)
    value_type: Literal["boolean", "enum"]
    allowed_values: list[str] | None = None
    singleton: bool
    requirement_relevant: bool

    @model_validator(mode="after")
    def validate_allowed_values(self):
        if self.value_type == "enum":
            if not self.allowed_values or len(self.allowed_values) != len(set(self.allowed_values)):
                raise ValueError("enum facts require unique allowed_values")
        elif self.allowed_values is not None:
            raise ValueError("boolean facts must not define allowed_values")
        return self

    def validate_value(self, value: Any) -> Any:
        if self.value_type == "boolean":
            if not isinstance(value, bool):
                raise FactCatalogError("fact value must be boolean")
            return value
        if not isinstance(value, str) or value not in (self.allowed_values or []):
            raise FactCatalogError("fact value is not in the supported enumeration")
        return value


class FactCatalogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    facts: dict[str, FactDefinition]


def load_fact_catalog(path: Path | None = None) -> FactCatalogConfig:
    source = path or Path(__file__).resolve().parents[1] / "config" / "facts" / "extraction_catalog.json"
    try:
        catalog = FactCatalogConfig.model_validate_json(source.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError) as error:
        raise FactCatalogError(f"invalid fact extraction catalog: {error}") from error
    expected = {"sponsor.exists", "host.exists", "trip.payer"}
    if set(catalog.facts) != expected:
        raise FactCatalogError("fact extraction catalog must contain exactly the reviewed Milestone 8 keys")
    return catalog


DEFAULT_FACT_CATALOG = load_fact_catalog()
