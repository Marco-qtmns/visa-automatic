from __future__ import annotations

from datetime import date
import re

from .base import (
    ConfiguredQualityCheck,
    QualityCheckFinding,
    QualityContent,
    TypeSpecificQualityResult,
)


_PERIOD_PATTERN = re.compile(
    r"statement\s+period\s*:\s*(\d{4}-\d{2}-\d{2})\s+(?:to|through|-)\s+(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_HOLDER_PATTERN = re.compile(
    r"account\s+holder\s*:\s*([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'\- ]{2,80})",
    re.IGNORECASE,
)


def _months_between(start: date, end: date) -> list[str]:
    if end < start:
        return []
    result: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year += 1
            month = 1
    return result


class ManualOnlyQualityEvaluator:
    """Conservative default: collect candidates, leave content judgment to staff."""

    name = "manual_only"
    version = "profiles-v1"

    def evaluate(
        self,
        content: QualityContent,
        checks: tuple[ConfiguredQualityCheck, ...],
    ) -> TypeSpecificQualityResult:
        metadata: dict[str, object] = {}
        findings: list[QualityCheckFinding] = []
        holder = _HOLDER_PATTERN.search(content.text)
        if holder:
            metadata["account_holder_candidate"] = holder.group(1).strip()[:255]

        periods: list[dict[str, str]] = []
        coverage: set[str] = set()
        for match in _PERIOD_PATTERN.finditer(content.text):
            try:
                start = date.fromisoformat(match.group(1))
                end = date.fromisoformat(match.group(2))
            except ValueError:
                continue
            if end < start:
                continue
            periods.append({"start": start.isoformat(), "end": end.isoformat()})
            coverage.update(_months_between(start, end))
        if periods:
            metadata["statement_period_candidates"] = periods[:12]
            metadata["coverage_months"] = sorted(coverage)

        for check in checks:
            evidence = None
            if check.assessment == "candidate_text_manual" and holder:
                evidence = "Account holder candidate detected from an explicit text label"
            elif check.assessment == "candidate_period_manual" and periods:
                evidence = f"Detected {len(periods)} explicit statement period candidate(s)"
            findings.append(QualityCheckFinding(
                check_id=check.check_id,
                status="manual_review",
                evidence=evidence,
                issue=f"Employee confirmation required: {check.label}",
                evaluator=self.name,
            ))
        return TypeSpecificQualityResult(findings, metadata)
