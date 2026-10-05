from __future__ import annotations

import re

from .base import ExtractedFactCandidate, ExtractionMessage


def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


class LocalRuleFactExtractor:
    """Small development extractor for explicit phrases; never a general semantic model."""

    name = "local_rules"
    model_version = "m8-v1"

    def extract(self, messages: list[ExtractionMessage]) -> list[ExtractedFactCandidate]:
        output: list[ExtractedFactCandidate] = []
        for message in messages:
            text = " ".join(message.text.split())
            lowered = text.casefold()
            ids = [message.id]

            sponsor_positive = _has(lowered, r"\b(my )?(father|dad|mother|company|sponsor) (will |is going to )?(pay|cover)") or _has(lowered, r"\b(meu|minha) (pai|m[aã]e|empresa) (vai |ir[aá] )?(pagar|custear)")
            sponsor_negated = _has(lowered, r"\b(not|won't|will not|n[aã]o)\b.{0,30}\b(pay|pagar|cover|custear)\b")
            self_pays = _has(lowered, r"\b(i (will |am going to )?(pay|cover)( for)? (myself|the trip)|eu (vou )?pagar( a viagem)?|no sponsor)\b")
            if sponsor_positive and not sponsor_negated:
                output.extend([
                    self._candidate("sponsor.exists", True, 0.92, ids, text),
                    self._candidate("trip.payer", "sponsor", 0.9, ids, text),
                ])
            elif self_pays:
                output.extend([
                    self._candidate("sponsor.exists", False, 0.9, ids, text),
                    self._candidate("trip.payer", "applicant", 0.9, ids, text),
                ])

            host_positive = _has(lowered, r"\b(stay|staying|ficar|ficarei)\b.{0,35}\b(sister|brother|friend|family|irm[aã]|amig[oa]|fam[ií]lia)\b")
            host_negative = _has(lowered, r"\b(not stay with anyone|won't stay with anyone|n[aã]o vou ficar com ningu[eé]m|hotel)\b")
            if host_positive and not host_negative:
                output.append(self._candidate("host.exists", True, 0.9, ids, text))
            elif host_negative:
                output.append(self._candidate("host.exists", False, 0.88, ids, text))
        return output

    @staticmethod
    def _candidate(key, value, confidence, message_ids, text):
        return ExtractedFactCandidate(key, value, confidence, message_ids, text[:500])
