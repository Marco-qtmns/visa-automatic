"""Field origins and source-bound overrides on the existing canonical case."""
import hashlib
import json
from .models import ValueOrigin


def source_digest(case):
    return hashlib.sha256(json.dumps([case.source_headers, case.raw_response],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def context_digest(case, path):
    values = [case.contact.address, case.identity.residence_country] if path == 'contact.country' else []
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def mark(case, path, value, source_type, source_ref, confirmed=False):
    case.provenance[path] = ValueOrigin(value, source_type, source_ref,
                                       confirmed, source_digest(case), context_digest(case,path))


def seed_source(case, columns=None):
    from .review import editable_fields
    case.case_id = case.case_id or source_digest(case)[:24]
    refs = {path: f'csv:{case.schema_version}:column[{col}]:{case.source_headers[col]}'
            for col, path in (columns or {}).items()}
    for path, value in editable_fields(case).items():
        if value and path not in case.provenance:
            mark(case, path, value, 'csv_explicit', refs.get(path, 'csv:' + path), True)


def override(case, path, value, confirmed=False, reference='staff review'):
    from .review import _assign, editable_fields
    if path not in editable_fields(case):
        raise ValueError('This field is not editable')
    _assign(case, path, value)
    mark(case, path, value, 'staff_confirmed' if confirmed else 'staff_entered', reference, True)
    case.overrides[path] = case.provenance[path]


def apply_overrides(case):
    from .review import editable_fields, _assign
    available = editable_fields(case)
    digest = source_digest(case)
    for path, item in case.overrides.items():
        # Changed source requires review again, never reuse approval blindly.
        if item.source_digest == digest and path in available:
            _assign(case, path, item.value)
            case.provenance[path] = item
    return case


def confirmed(case, path, value):
    p = case.provenance.get(path)
    return bool(p and p.confirmed and p.value == value and
                p.source_digest == source_digest(case) and p.context_digest == context_digest(case,path))
