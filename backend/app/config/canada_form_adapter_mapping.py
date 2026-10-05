"""Versioned M9D canonical-payload to legacy CanadaCase adapter contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .canada_preparation_policy import PAYLOAD_PROJECTIONS


ADAPTER_MAPPING_VERSION = "m9d-1"


@dataclass(frozen=True)
class AdapterMapping:
    audited_path: str
    payload_selector: str
    legacy_destination: str
    transformation: str
    supply_mode: str
    expected_legacy_value: str
    forms: tuple[str, ...]


def _forms(path: str) -> tuple[str, ...]:
    group, field = path.rsplit(".", 1)
    if group == "identity":
        forms = ["IMM5257"]
        if field in {"family_name", "given_names", "date_of_birth", "birth_country", "marital_status"}: forms.append("IMM5707")
        if field in {"family_name", "given_names", "date_of_birth"}: forms.append("IMM5476")
        return tuple(forms)
    if group == "passport": return ("IMM5257",) if field in {"number", "issuing_country", "issue_date", "expiry_date"} else ()
    if group == "contact": return ("IMM5257", "IMM5476") if field == "email" else ("IMM5257",)
    if group == "trip": return ("IMM5257",) if field in {"purpose", "arrival_date", "departure_date", "available_funds_cad", "host_name", "host_address", "relationship"} else ()
    if group == "education": return ("IMM5257",)
    if group == "activities[*]": return ("IMM5257", "IMM5257-CONTINUATION")
    if group == "relationships": return ("IMM5257", "IMM5707")
    if group == "family.members[*]": return ("IMM5707",)
    if group in {"residence_records[*]", "travel_records[*]"}: return ("IMM5257", "IMM5257-CONTINUATION")
    if group == "official_review": return ("IMM5257",)
    if group == "representative": return ("IMM5476",)
    return ()


def _transformation(path: str) -> tuple[str, str, str]:
    if path.endswith(("date", "start_date", "end_date", "date_of_birth", "residence_since")):
        return "date.isoformat", "direct", "ISO-8601 date string or empty optional value"
    if path.endswith(("ongoing_answer", "has_other_valid_passport", "has_previous_relationship", "spouse_accompanying_answer")):
        return "semantic boolean to Yes/No", "derived", "explicit Yes or No string"
    if "[*]" in path or path.startswith("relationships."):
        return "ordered canonical collection projection", "direct", "legacy dataclass field in canonical order"
    return "semantic value to legacy string", "direct", "legacy semantic string without XFA encoding"


_projection = {item.legacy_path: item for item in PAYLOAD_PROJECTIONS}
ADAPTER_MAPPINGS = tuple(
    AdapterMapping(
        audited_path=path,
        payload_selector=("trip.imm5257_purpose_code" if path == "trip.purpose" else _projection[path].payload_path),
        legacy_destination=path,
        transformation=_transformation(path)[0],
        supply_mode=_transformation(path)[1],
        expected_legacy_value=_transformation(path)[2],
        forms=_forms(path),
    )
    for path in _projection
)

assert len(ADAPTER_MAPPINGS) == 138
assert len({item.audited_path for item in ADAPTER_MAPPINGS}) == 138

ADAPTER_MAPPING_SPEC_JSON = tuple(asdict(item) for item in ADAPTER_MAPPINGS)
