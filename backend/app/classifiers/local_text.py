from __future__ import annotations

import re

from .base import (
    ClassificationEvidenceItem,
    ClassifierResult,
    ExtractedDocumentContent,
)


class LocalTextDocumentClassifier:
    """Small deterministic development classifier for embedded PDF text only."""

    name = "local_text"
    model_version = "rules-v1"

    _TYPE_RULES = (
        ("passport_bio_page", ("passport", "passport no", "nationality"), "Passport text markers detected"),
        ("bank_statements", ("bank statement", "account holder", "transaction"), "Bank statement text markers detected"),
        ("civil_status_document", ("birth certificate", "marriage certificate", "civil status"), "Civil-status certificate text markers detected"),
        ("identity_document", ("identity card", "identity document", "national id"), "Identity-document text markers detected"),
    )
    _OWNER_PATTERN = re.compile(
        r"(?:account holder|passport holder|holder|full name|name)\s*[:\-]\s*"
        r"([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'\- ]{2,80})",
        re.IGNORECASE,
    )

    def classify(self, content: ExtractedDocumentContent) -> ClassifierResult:
        text = content.text.strip()
        if not text:
            return ClassifierResult(
                document_type=None,
                owner_name=None,
                confidence=None,
                evidence=[ClassificationEvidenceItem(
                    type="classification",
                    value="No embedded text was available to the configured local text classifier",
                )],
            )

        folded = text.casefold()
        best: tuple[str, int, str] | None = None
        for document_type, markers, reason in self._TYPE_RULES:
            score = sum(marker in folded for marker in markers)
            if score and (best is None or score > best[1]):
                best = (document_type, score, reason)

        owner_match = self._OWNER_PATTERN.search(text)
        owner_name = owner_match.group(1).strip() if owner_match else None
        evidence: list[ClassificationEvidenceItem] = []
        if best:
            evidence.append(ClassificationEvidenceItem(type="classification", value=best[2]))
        else:
            evidence.append(ClassificationEvidenceItem(
                type="classification",
                value="Embedded text did not map confidently to the document type catalog",
            ))
        if owner_name:
            evidence.append(ClassificationEvidenceItem(
                type="text", value=f"Owner name marker: {owner_name}"
            ))
        confidence = min(0.55 + 0.12 * best[1], 0.91) if best else None
        return ClassifierResult(
            document_type=best[0] if best else None,
            owner_name=owner_name,
            confidence=confidence,
            evidence=evidence,
        )
