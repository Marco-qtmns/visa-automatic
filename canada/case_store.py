"""Versioned local case files preserve source answers, reviews and staff additions."""
from dataclasses import MISSING, asdict, fields, is_dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import get_args, get_origin, get_type_hints

from .models import CanadaCase

FORMAT = 'visa-automatic-canada-case'
VERSION = 1
SUFFIX = '.canada-case.json'


def _decode(kind, value):
    if is_dataclass(kind):
        if not isinstance(value, dict):
            raise ValueError('Expected a case object')
        names = {field.name for field in fields(kind)}
        if set(value) - names:
            raise ValueError('Unsupported case fields; this file may require a newer app')
        required = {f.name for f in fields(kind) if f.default is MISSING and f.default_factory is MISSING}
        if required - value.keys():
            raise ValueError('Incomplete case record')
        hints = get_type_hints(kind)
        return kind(**{key: _decode(hints[key], item) for key, item in value.items()})
    origin = get_origin(kind)
    if origin is list:
        if not isinstance(value, list):
            raise ValueError('Expected a case list')
        return [_decode(get_args(kind)[0], item) for item in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError('Expected source answers')
        key_type, item_type = get_args(kind)
        return {_decode(key_type, key): _decode(item_type, item) for key, item in value.items()}
    if type(value) is not kind:
        raise ValueError('Invalid case value type')
    return value


def save_case(case, path):
    path = Path(path)
    if not path.name.endswith(SUFFIX):
        raise ValueError('Use a .canada-case.json file; source CSV/PDF files cannot be overwritten')
    data = {'format': FORMAT, 'version': VERSION, 'case': asdict(case)}
    _decode(CanadaCase, data['case'])
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.canada-case-', delete=False) as output:
            temp_path = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def load_case(path):
    path = Path(path)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Case file exceeds the 20 MB limit')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('format') != FORMAT or type(data.get('version')) is not int or data['version'] != VERSION:
            raise ValueError('Unsupported Canada case format/version')
        case = _decode(CanadaCase, data['case'])
        return case
    except (KeyError, TypeError, RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid Canada case file') from error
