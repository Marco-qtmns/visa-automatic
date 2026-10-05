"""Reusable Canada representative details, without case-specific authorization."""
from dataclasses import asdict, fields
import json
import os
from pathlib import Path
import tempfile

from .models import CanadaRepresentative
from .official_options import REPRESENTATIVE_CATEGORIES
from .review import ReviewSession

FORMAT = 'visa-automatic-canada-representative'
SUFFIX = '.canada-representative.json'
PROFILE_FIELDS = frozenset(f.name for f in fields(CanadaRepresentative)
                          if f.name != 'action' and not f.name.startswith('cancelled_'))


def _validate(values):
    if not isinstance(values, dict) or set(values) != PROFILE_FIELDS:
        raise ValueError('Unsupported or incomplete Canada representative profile')
    if any(type(value) is not str for value in values.values()):
        raise ValueError('Representative profile values must be text')
    if values['category'] and values['category'] not in REPRESENTATIVE_CATEGORIES:
        raise ValueError('Unknown representative category')
    return values


def save_profile(representative, path):
    path = Path(path)
    if not path.name.endswith(SUFFIX):
        raise ValueError('Use a .canada-representative.json file')
    values = _validate({k:v for k,v in asdict(representative).items() if k in PROFILE_FIELDS})
    payload = json.dumps({'format':FORMAT,'version':1,'representative':values},ensure_ascii=False,indent=2)+'\n'
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                         prefix='.canada-representative-',delete=False) as stream:
            temp = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def load_profile_into_case(case, path, *, empty_only=False):
    path = Path(path)
    if path.stat().st_size > 1024*1024:
        raise ValueError('Representative profile exceeds the 1 MB limit')
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(document,dict) or document.get('format') != FORMAT
                or type(document.get('version')) is not int or document['version'] != 1):
            raise ValueError('Unsupported Canada representative profile format/version')
        values = _validate(document.get('representative'))
    except (UnicodeError,json.JSONDecodeError) as error:
        raise ValueError('Invalid Canada representative profile') from error
    session = ReviewSession(case)
    for key,value in values.items():
        if empty_only and getattr(case.representative,key):
            continue
        session.set_value('representative.'+key,value)
    return session.apply()


def default_profile_path():
    from settings import app_data_dir
    return app_data_dir() / ('canada-default' + SUFFIX)


def apply_default_profile(case):
    """Only a pristine representative block can receive the saved default.

    Mixing an existing representative's name with a different profile's license
    or email would be unsafe. Explicit Load remains available for replacement.
    """
    path = default_profile_path()
    if path.exists() and not any(getattr(case.representative,key) for key in PROFILE_FIELDS):
        return load_profile_into_case(case,path)
    return []
