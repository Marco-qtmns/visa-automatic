"""Conservative reusable address parsing for imported application addresses."""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from .country_normalization import normalize_country


@dataclass(frozen=True)
class NormalizedAddress:
    raw: str
    country_code: str | None = None
    province_or_state: str | None = None
    city: str | None = None
    district: str | None = None
    street_name: str | None = None
    street_number: str | None = None
    unit: str | None = None
    postal_code: str | None = None
    unresolved_text: str | None = None
    parse_issues: tuple[str, ...] = field(default_factory=tuple)
    review_status: str = "needs_review"


def normalize_address(
    raw: object,
    *,
    country: object = None,
    city: object = None,
    province_or_state: object = None,
    postal_code: object = None,
) -> NormalizedAddress:
    """Parse only high-confidence components and retain every unresolved fragment."""
    source = str(raw or "").strip()
    issues: list[str] = []
    country_result = normalize_country(country) if str(country or "").strip() else None
    if country_result and not country_result.code:
        issues.append("country_not_recognized")

    postcode = str(postal_code or "").strip() or None
    remaining = source
    if not postcode:
        match = re.search(r"\b(\d{5}-?\d{3}|[A-Z]\d[A-Z][ -]?\d[A-Z]\d)\b", source, re.I)
        if match:
            postcode = match.group(1).upper()
            remaining = (remaining[:match.start()] + remaining[match.end():]).strip(" ,-")

    parts = [part.strip() for part in re.split(r"\s*,\s*", remaining) if part.strip()]
    street = parts[0] if parts else None
    trailing = parts[1:] if len(parts) > 1 else []
    unresolved: list[str] = []
    number = unit = district = None
    if street:
        unit_match = re.search(r"\b(?:apt|apto|apartamento|unit|unidade|sala)\.?\s*([\w-]+)\b", street, re.I)
        if unit_match:
            unit = unit_match.group(1)
            street = (street[:unit_match.start()] + street[unit_match.end():]).strip(" ,-#")
        number_match = re.search(r"(?:,|\s)\s*(\d+[A-Za-z]?)\s*$", street)
        if number_match:
            number = number_match.group(1)
            street = street[:number_match.start()].strip(" ,-")
        leading_number = re.match(r"^(\d+[A-Za-z]?)\s+(.+)$", street)
        if leading_number and not number:
            number, street = leading_number.group(1), leading_number.group(2)
    for fragment in trailing:
        if number is None and re.fullmatch(r"\d+[A-Za-z]?", fragment):
            number = fragment
            continue
        unit_fragment = re.fullmatch(
            r"(?:apt|apto|apartamento|unit|unidade|sala)\.?\s*([\w-]+)",
            fragment, re.I,
        )
        if unit is None and unit_fragment:
            unit = unit_fragment.group(1)
            continue
        district_fragment = re.fullmatch(r"(?:bairro\s+)?(.+)", fragment, re.I)
        if district is None and fragment.casefold().startswith("bairro "):
            district = district_fragment.group(1)
            continue
        unresolved.append(fragment)

    explicit_city = str(city or "").strip() or None
    explicit_state = str(province_or_state or "").strip() or None
    if not source:
        issues.append("missing_street_address")
    if not street:
        issues.append("street_not_identified")
    if unresolved:
        issues.append("unresolved_address_fragments")
    return NormalizedAddress(
        raw=source,
        country_code=country_result.code if country_result else None,
        province_or_state=explicit_state,
        city=explicit_city,
        district=district,
        street_name=street,
        street_number=number,
        unit=unit,
        postal_code=postcode,
        unresolved_text=", ".join(unresolved) or None,
        parse_issues=tuple(issues),
        review_status="needs_review",
    )
