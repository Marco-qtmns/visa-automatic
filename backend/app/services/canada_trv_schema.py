from __future__ import annotations

import csv
import collections
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Literal


SCHEMA_JSON_SHA256 = "6840f9f95b6fa0f31cc719c7b63cc02ada4f5f68a08b0c5e10a73934712a51ad"
SCHEMA_YAML_SHA256 = "af0abdd6050061e86b6acb909f6ed8d59eefafe78380d701c56824377d7f479a"
ConditionResult = Literal["true", "false", "unknown"]


class SchemaConfigurationError(RuntimeError):
    pass


class CsvSchemaMismatch(ValueError):
    def __init__(self, message: str, *, detail: dict[str, Any]):
        super().__init__(message)
        self.detail = detail


@dataclass(frozen=True)
class ParsedCsv:
    variant_id: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class NormalizedRow:
    fields: tuple[dict[str, Any], ...]
    data: dict[str, Any]
    issues: tuple[dict[str, Any], ...]


class SchemaRegistry:
    """Loads the immutable v3 schema and rejects accidental asset drift."""

    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[1] / "config" / "canada_trv"
        json_path = self.root / "canada_trv_review_schema_v3.json"
        yaml_path = self.root / "canada_trv_review_schema_v3.yaml"
        self._verify_asset(json_path, SCHEMA_JSON_SHA256)
        self._verify_asset(yaml_path, SCHEMA_YAML_SHA256)
        try:
            self.schema = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SchemaConfigurationError(f"Cannot load Canada TRV review schema: {error}") from error
        self._validate()

    @staticmethod
    def _verify_asset(path: Path, expected: str) -> None:
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise SchemaConfigurationError(f"Missing Canada TRV schema asset: {path.name}") from error
        if actual != expected:
            raise SchemaConfigurationError(
                f"Canada TRV schema asset {path.name} changed without a reviewed schema-version update"
            )

    def _validate(self) -> None:
        schema = self.schema
        fields, sections = schema.get("fields", []), schema.get("sections", [])
        if schema.get("schema_version") != "3.0.0":
            raise SchemaConfigurationError("Expected immutable Canada TRV schema version 3.0.0")
        ids = [item.get("field_id") for item in fields]
        targets = [item.get("target_path") for item in fields]
        section_ids = {item.get("id") for item in sections}
        if len(fields) != 235 or len(set(ids)) != 235:
            raise SchemaConfigurationError("Expected 235 unique Canada TRV fields")
        if len(sections) != 28 or len(section_ids) != 28:
            raise SchemaConfigurationError("Expected 28 unique Canada TRV sections")
        if len(set(targets)) != 235 or any(item.get("section_id") not in section_ids for item in fields):
            raise SchemaConfigurationError("Canada TRV targets or section references are inconsistent")
        if sorted(item.get("csv_column_1based") for item in fields) != list(range(1, 236)):
            raise SchemaConfigurationError("Canada TRV source columns are not contiguous")
        if fields[113].get("normalized_type") != "choice_raw":
            raise SchemaConfigurationError("GF_114 must remain a choice_raw state field")
        if fields[128].get("csv_header") != "País de nascimento do genitor 1" or fields[128].get("label_pt") != "País de nascimento do genitor 2":
            raise SchemaConfigurationError("GF_129 source/header correction contract changed")

    @property
    def fields(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.schema["fields"])

    @property
    def sections(self) -> tuple[dict[str, Any], ...]:
        return tuple(sorted(self.schema["sections"], key=lambda item: item["order"]))

    def public_schema(self) -> dict[str, Any]:
        return {
            key: self.schema[key]
            for key in ("schema_id", "schema_version", "schema_status", "sections", "fields", "ui")
        }


class CsvParser:
    def __init__(self, registry: SchemaRegistry):
        self.registry = registry

    def parse(self, content: bytes) -> ParsedCsv:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise CsvSchemaMismatch(
                "CSV must be UTF-8 or UTF-8 with BOM",
                detail={"code": "CSV_ENCODING_INVALID", "schema_version": "3.0.0"},
            ) from error
        try:
            rows = list(csv.reader(io.StringIO(text, newline="")))
        except csv.Error as error:
            raise CsvSchemaMismatch(
                "CSV quoting or embedded line breaks are malformed",
                detail={"code": "CSV_PARSE_INVALID", "schema_version": "3.0.0", "reason": str(error)},
            ) from error
        if not rows:
            raise CsvSchemaMismatch("CSV is empty", detail={"code": "CSV_EMPTY", "schema_version": "3.0.0"})
        headers = rows[0]
        variant = self._match(headers)
        self._validate_occurrences(headers, variant)
        responses = []
        for number, row in enumerate(rows[1:], start=2):
            if not any(value != "" for value in row):
                continue
            if len(row) != len(headers):
                raise CsvSchemaMismatch(
                    f"CSV row {number} has {len(row)} cells; expected {len(headers)}",
                    detail={"code": "CSV_ROW_WIDTH_MISMATCH", "row": number,
                            "expected_count": len(headers), "actual_count": len(row), "schema_version": "3.0.0"},
                )
            responses.append(tuple(row))
        if not responses:
            raise CsvSchemaMismatch(
                "CSV has no response rows", detail={"code": "CSV_NO_RESPONSES", "schema_version": "3.0.0"}
            )
        return ParsedCsv(variant, tuple(headers), tuple(responses))

    def _validate_occurrences(self, headers: list[str], variant: str) -> None:
        definitions = [item for item in self.registry.fields
                       if not (variant == "username_absent" and item["field_id"] == "GF_002")]
        by_key = {(item["csv_header"], item["header_occurrence_1based"]): item["field_id"] for item in definitions}
        counts: collections.Counter[str] = collections.Counter()
        resolved: list[str] = []
        for header in headers:
            counts[header] += 1
            field_id = by_key.get((header, counts[header]))
            if field_id is None:
                raise self._diagnostic(headers, [item["csv_header"] for item in definitions], "duplicate_occurrence_unmapped")
            resolved.append(field_id)
        if len(resolved) != len(set(resolved)):
            raise self._diagnostic(headers, [item["csv_header"] for item in definitions], "duplicate_field_resolution")

    def _match(self, headers: list[str]) -> str:
        expected = [item["csv_header"] for item in self.registry.fields]
        if len(headers) == 235 and len(headers) > 1 and headers[1] == "Nome de usuário":
            variant, comparable = "username_present", headers
        elif len(headers) == 234:
            variant, comparable = "username_absent", headers
            expected = expected[:1] + expected[2:]
        else:
            raise self._diagnostic(headers, expected, "unsupported_column_count")
        if comparable != expected:
            raise self._diagnostic(comparable, expected, "ordered_headers_changed")
        digest = hashlib.sha256(
            json.dumps(headers if variant == "username_absent" else headers[:1] + headers[2:],
                       ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        required = self.registry.schema["matching"]["canonical_headers_sha256_json_utf8"]
        if digest != required:
            raise self._diagnostic(comparable, expected, "header_signature_changed")
        return variant

    def _diagnostic(self, actual: list[str], expected: list[str], reason: str) -> CsvSchemaMismatch:
        limit = max(len(actual), len(expected))
        mismatch = next((index for index in range(limit)
                         if index >= len(actual) or index >= len(expected) or actual[index] != expected[index]), None)
        position = None if mismatch is None else mismatch + 1
        detail = {
            "code": "CSV_SCHEMA_MISMATCH", "reason": reason, "schema_version": "3.0.0",
            "expected_count": len(expected), "actual_count": len(actual), "position_1based": position,
            "expected_header": expected[mismatch] if mismatch is not None and mismatch < len(expected) else None,
            "actual_header": actual[mismatch] if mismatch is not None and mismatch < len(actual) else None,
            "suggested_correction": "Register a new reviewed schema version; do not map this file approximately.",
        }
        return CsvSchemaMismatch(
            f"Unknown Canada TRV CSV structure at column {position or 'unknown'}", detail=detail
        )


class ConditionEvaluator:
    def evaluate(self, node: dict[str, Any], values: dict[str, Any]) -> ConditionResult:
        op = node.get("op")
        if op == "any":
            results = [self.evaluate(item, values) for item in node.get("conditions", [])]
            if "true" in results:
                return "true"
            return "unknown" if "unknown" in results else "false"
        path = node.get("path")
        if not isinstance(path, str) or path not in values or values[path] in (None, ""):
            return "unknown"
        actual = str(values[path]).strip().casefold()
        if op == "eq":
            return "true" if actual == str(node.get("value", "")).strip().casefold() else "false"
        if op == "in":
            options = {str(item).strip().casefold() for item in node.get("values", [])}
            return "true" if actual in options else "false"
        raise SchemaConfigurationError(f"Unsupported applicability operator: {op!r}")


class Normalizer:
    def __init__(self, registry: SchemaRegistry):
        self.registry = registry
        self.conditions = ConditionEvaluator()

    def normalize(self, parsed: ParsedCsv, row: tuple[str, ...], row_number: int) -> NormalizedRow:
        source_by_field = self._source_values(parsed, row)
        raw_paths = {field["target_path"]: source_by_field[field["field_id"]][1] for field in self.registry.fields}
        fields: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        data: dict[str, Any] = {}
        for definition in self.registry.fields:
            field_id, path = definition["field_id"], definition["target_path"]
            source_column, raw = source_by_field[field_id]
            condition = definition.get("applicability", {"mode": "always"})
            condition_result: ConditionResult = "true"
            if field_id == "GF_002" and parsed.variant_id == "username_absent":
                condition_result = "false"
            elif condition.get("mode") == "conditional":
                condition_result = self.conditions.evaluate(condition["condition"], raw_paths)
            applicability, status = self._field_state(definition, raw, condition_result)
            normalized, normalization_issue = self._normalize_value(definition, raw)
            if normalization_issue:
                status = "needs_review"
                issues.append(self._issue("invalid_value", "error", normalization_issue, field_id, definition["section_id"]))
            if condition_result == "false" and raw != "":
                status = "needs_review"
                issues.append(self._issue(
                    "condition_conflict", "error", "A value was supplied although its branch is inactive.",
                    field_id, definition["section_id"],
                ))
            item = {
                "field_id": field_id,
                "source_csv_column_1based": source_column,
                "source_header": definition["csv_header"],
                "source_section_id": definition["section_id"],
                "target_path": path,
                "raw_value": raw,
                "normalized_value": normalized,
                "applicability": applicability,
                "review_status": status,
                "schema_version": self.registry.schema["schema_version"],
                "import_row_number": row_number,
                "evidence": definition.get("evidence"),
                "requirement_mode": definition.get("requirement", {}).get("mode", "optional"),
            }
            fields.append(item)
            self._set_path(data, path, normalized)
        self._prune_repeated_arrays(data, fields)
        self._prepare_unstructured_collections(data)
        issues.extend(self._cross_validate(fields))
        self._mark_issue_fields(fields, issues)
        return NormalizedRow(tuple(fields), data, tuple(issues))

    def _prune_repeated_arrays(self, data: dict[str, Any], fields: list[dict[str, Any]]) -> None:
        for config in self.registry.schema.get("normalization", {}).get("arrays", []):
            path = config["path"]
            records = data.get(path)
            if not isinstance(records, list):
                continue
            kept = []
            for slot, record in enumerate(records):
                prefix = f"{path}[{slot}]."
                source_fields = [item for item in fields if item["target_path"].startswith(prefix)]
                if not any(item["raw_value"] != "" for item in source_fields):
                    continue
                if isinstance(record, dict):
                    record = {"_source_slot": slot + 1, **record}
                kept.append(record)
            data[path] = kept

    def _prepare_unstructured_collections(self, data: dict[str, Any]) -> None:
        for config in self.registry.schema.get("normalization", {}).get("unstructured_collections", []):
            parent_path = config["source_path"].rsplit(".", 1)[0]
            parent = self._get_path(data, parent_path)
            if isinstance(parent, dict):
                parent.setdefault("candidates", [])
                parent["requires_manual_review"] = bool(parent.get("raw_text"))

    @staticmethod
    def _get_path(root: dict[str, Any], path: str) -> Any:
        current: Any = root
        for name, array_index in re.findall(r"([^.[\]]+)|\[(\d+)\]", path):
            token: str | int = int(array_index) if array_index else name
            if isinstance(token, int):
                if not isinstance(current, list) or token >= len(current):
                    return None
                current = current[token]
            else:
                if not isinstance(current, dict) or token not in current:
                    return None
                current = current[token]
        return current

    def _source_values(self, parsed: ParsedCsv, row: tuple[str, ...]) -> dict[str, tuple[int | None, str]]:
        result: dict[str, tuple[int | None, str]] = {}
        offset = 0
        for definition in self.registry.fields:
            field_id = definition["field_id"]
            if field_id == "GF_002" and parsed.variant_id == "username_absent":
                result[field_id] = (None, "")
                offset = -1
                continue
            index = definition["csv_index_0based"] + offset
            result[field_id] = (index + 1, row[index])
        return result

    @staticmethod
    def _field_state(definition: dict[str, Any], raw: str, condition: ConditionResult) -> tuple[str, str]:
        required = definition.get("requirement", {}).get("mode") == "review_when_applicable"
        reviewable = bool(definition.get("ui", {}).get("show_in_review"))
        if condition == "false" and raw == "":
            return "not_applicable", "not_applicable"
        if condition == "unknown":
            return "unknown", "needs_review"
        if raw == "":
            return "applicable", "missing" if required else ("pending" if reviewable else "not_applicable")
        return "applicable", "pending" if reviewable else "confirmed"

    @staticmethod
    def _normalize_value(definition: dict[str, Any], raw: str) -> tuple[Any, str | None]:
        if raw == "":
            return None, None
        kind = definition.get("normalized_type")
        if kind == "date_raw":
            for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(raw.strip(), pattern).date().isoformat(), None
                except ValueError:
                    continue
            return None, "Enter a real date as DD/MM/YYYY or YYYY-MM-DD; the original value was preserved."
        if kind == "yes_no_raw":
            choices = {"sim": True, "não": False, "nao": False}
            value = choices.get(raw.strip().casefold())
            return (value, None) if value is not None else (None, "Expected Sim or Não; the original value was preserved.")
        if kind == "email":
            address = parseaddr(raw)[1]
            if address != raw.strip() or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
                return raw, "Email syntax is invalid; the original value was preserved."
        if kind == "file_reference_raw" and raw.strip() == "SIMULADO_NAO_ANEXADO":
            return {"raw_text": raw, "status": "simulated_placeholder", "references": []}, None
        if kind == "file_reference_raw":
            references = re.findall(r"https?://[^\s,]+", raw)
            return {"raw_text": raw, "status": "reference_unverified", "references": references}, None
        return raw, None

    def _cross_validate(self, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_path = {item["target_path"]: item for item in fields}
        issues: list[dict[str, Any]] = []
        for rule in self.registry.schema.get("validation_rules", []):
            if rule.get("check") != "start_not_after_end":
                continue
            start, end = by_path.get(rule["path_start"]), by_path.get(rule["path_end"])
            if start and end and start["normalized_value"] and end["normalized_value"]:
                try:
                    invalid = date.fromisoformat(str(start["normalized_value"])) > date.fromisoformat(str(end["normalized_value"]))
                except ValueError:
                    invalid = False
                if invalid:
                    issues.append(self._issue(rule["id"], rule["severity"], "Start date is after end date.", end["field_id"], end["source_section_id"]))
        for item in fields:
            if item["review_status"] == "missing":
                issues.append(self._issue("required_review_value_missing", "error", "Applicable review information is missing.", item["field_id"], item["source_section_id"]))
        return issues

    @staticmethod
    def _mark_issue_fields(fields: list[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
        affected = {item.get("field_id") for item in issues if item.get("severity") in {"block", "blocking", "error"}}
        for field in fields:
            if field["field_id"] in affected and field["review_status"] not in {"missing", "not_applicable"}:
                field["review_status"] = "needs_review"

    @staticmethod
    def _issue(code: str, severity: str, message: str, field_id: str | None, section_id: str | None) -> dict[str, Any]:
        return {"code": code, "severity": "blocking" if severity in {"block", "blocking"} else severity,
                "message": message, "field_id": field_id, "section_id": section_id}

    @staticmethod
    def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
        parts = re.findall(r"([^.[\]]+)|\[(\d+)\]", path)
        current: Any = root
        for index, (name, array_index) in enumerate(parts):
            token: str | int = int(array_index) if array_index else name
            last = index == len(parts) - 1
            if isinstance(token, str):
                if last:
                    current[token] = value
                else:
                    next_is_array = bool(parts[index + 1][1])
                    current = current.setdefault(token, [] if next_is_array else {})
            else:
                while len(current) <= token:
                    current.append({})
                if last:
                    current[token] = value
                else:
                    current = current[token]


DEFAULT_SCHEMA_REGISTRY = SchemaRegistry()
