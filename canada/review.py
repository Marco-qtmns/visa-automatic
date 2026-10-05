"""Transactional manual corrections; original source answers are immutable."""
from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
import json

from .models import Activity, FamilyMember, HistoryRecord, ReviewChange
from .official_options import choices_for

READ_ONLY = {'raw_response', 'source_text', 'confirmation_digest', 'source_email', 'source_role', 'source_block_index', 'review_changes', 'import_profile', 'source_headers', 'source_header_sha256', 'declaration_acceptance', 'category'}
READ_ONLY.update({'narrative_proposals_digest', 'case_id', 'schema_version', 'provenance', 'overrides', 'id', 'status', 'raw_source', 'guardian_status', 'parsed_digest'})
PARENT_ROLES = ('', 'mother', 'father')


def editable_fields(case):
    """Return allowlisted scalar paths; provenance and logs cannot be edited."""
    result = {}

    def walk(obj, path=''):
        if is_dataclass(obj):
            for field in fields(obj):
                if field.name not in READ_ONLY or (path == 'representative' and field.name == 'category'):
                    walk(getattr(obj, field.name), f'{path}.{field.name}'.lstrip('.'))
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                walk(value, f'{path}[{index}]')
        elif isinstance(obj, str):
            # Only parents require a manually confirmed role.
            if not (path.endswith('.confirmed_role') and path.startswith('family.children')):
                result[path] = obj
    walk(case)
    return result


def _assign(case, path, value):
    parts = path.split('.')
    obj = case
    for part in parts[:-1]:
        if '[' in part:
            name, index = part.rstrip(']').split('[')
            obj = getattr(obj, name)[int(index)]
        else:
            obj = getattr(obj, part)
    setattr(obj, parts[-1], value)


class ReviewSession:
    def __init__(self, case):
        self.case = case
        self.original = deepcopy(case)
        self.draft = deepcopy(case)
        self.values = editable_fields(case)
        self.resolutions = {}

    def set_value(self, path, value):
        if path not in self.values:
            raise ValueError('This field is not editable')
        if not isinstance(value, str):
            raise ValueError('Corrections must be text')
        if path.endswith('.confirmed_role') and value not in PARENT_ROLES:
            raise ValueError('Select a parent role from the list')
        options = choices_for(path)
        if options is not None and value not in options:
            raise ValueError('Select an explicit option from the list, or leave the field blank')
        self.values[path] = value

    def preview(self):
        draft = deepcopy(self.draft)
        for path, value in self.values.items():
            _assign(draft, path, value)
        from .provenance import override
        previous = editable_fields(self.draft)
        for path,value in self.values.items():
            if value != previous.get(path, '') or path in self.resolutions:
                confirmed,reference = self.resolutions.get(path,(False,'staff review'))
                override(draft,path,value,confirmed,reference)
        return draft

    def issues(self):
        from .validation import validate_case
        return validate_case(self.preview()).issues

    def tasks(self):
        from .review_tasks import review_tasks
        return review_tasks(self.preview())

    def resolve_task(self, task, values, confirmed_paths=()):
        from .review_tasks import task_fields
        current=next((t for t in self.tasks() if t.id==task.id),None)
        if current is None or current.issues != task.issues:
            raise ValueError('Review task changed; refresh it before saving')
        if not set(values) <= set(task_fields(current,self.preview())):
            raise ValueError('A field does not belong to this review task')
        if not set(confirmed_paths) <= set(values):
            raise ValueError('Confirmation must refer to a supplied task field')
        before_values=dict(self.values); before_resolutions=dict(self.resolutions)
        try:
            for path,value in values.items():
                self.set_value(path,value)
                if value.strip(): self.resolutions[path]=(path in confirmed_paths or value==before_values[path],'review task:'+task.id)
        except ValueError:
            self.values=before_values;self.resolutions=before_resolutions
            raise

    def resolve_issue(self, issue, values=None, confirm=False):
        current = next((i for i in self.issues() if i.identity == issue.identity), None)
        if current is None or current.source_values != issue.source_values:
            raise ValueError('Issue changed; refresh review before applying a resolution')
        values = values or {}
        if issue.resolution_type == 'batch_confirm_or_edit':
            paths=list(issue.source_values)
            if confirm:
                values={path:issue.suggested_value for path in paths}
            if set(values) != set(paths):
                raise ValueError('Enter a country for every listed activity')
        elif confirm and not values:
            if not issue.suggested_value:
                raise ValueError('Enter an explicit value; no suggestion is available')
            values={issue.field:issue.suggested_value}
        if not values or any(not value.strip() for value in values.values()):
            raise ValueError('Enter or confirm a non-empty value')
        for path,value in values.items():
            self.set_value(path,value)
            self.resolutions[path]=(confirm,issue.code)

    def add_record(self, kind):
        """Staff may add WhatsApp follow-ups beyond the five client form slots."""
        if kind not in {'child', 'activity', 'mother', 'father', 'residence', 'travel'}:
            raise ValueError('Unsupported record kind')
        self.draft = self.preview()
        if kind in {'residence', 'travel'}:
            records = getattr(self.draft, kind + '_records')
            record = HistoryRecord(source_role='staff_' + kind)
        elif kind == 'activity':
            records = self.draft.activities
            record = Activity(source_role='staff')
        elif kind == 'child':
            records = self.draft.family.children
            record = FamilyMember(source_role='staff_child')
        else:
            records = self.draft.family.parents
            if any(p.confirmed_role == kind for p in records):
                raise ValueError('This parent already exists; edit the existing record')
            record = FamilyMember(source_role='staff_parent', confirmed_role=kind)
        record.source_block_index = max((r.source_block_index for r in records), default=0) + 1
        records.append(record)
        self.values = editable_fields(self.draft)

    def confirm_record(self, kind, index):
        from .preparation import record_errors, record_digest
        if kind not in ('residence', 'travel'):
            raise ValueError('Select a residence or travel record')
        draft = self.preview()
        record = getattr(draft, kind + '_records')[index]
        errors = record_errors(record)
        if errors:
            raise ValueError('; '.join(errors))
        record.confirmation_digest = record_digest(record)
        from .provenance import mark
        for name in ('country','status_or_purpose','start_date','end_date'):
            path=f'{kind}_records[{index}].{name}'
            mark(draft,path,getattr(record,name),'staff_confirmed','history confirmation',True)
            draft.overrides[path]=draft.provenance[path]
        self.draft = draft

    def remove_record(self, kind, index):
        if kind not in ('residence', 'travel'):
            raise ValueError('Only history proposals can be removed here')
        self.draft = self.preview()
        del getattr(self.draft, kind + '_records')[index]
        # Index paths move after removal; never apply a deleted record's override
        # to its successor. The remaining canonical values stay intact.
        prefix = kind + '_records['
        self.draft.overrides = {p:v for p,v in self.draft.overrides.items() if not p.startswith(prefix)}
        self.draft.provenance = {p:v for p,v in self.draft.provenance.items() if not p.startswith(prefix)}
        self.resolutions = {p:v for p,v in self.resolutions.items() if not p.startswith(prefix)}
        self.values = editable_fields(self.draft)

    def apply(self):
        if self.case != self.original:
            raise ValueError('The case changed while this review was open. Reopen the review.')
        previous = editable_fields(self.original)
        draft = self.preview()
        timestamp = datetime.now(timezone.utc).isoformat()
        changes = [ReviewChange(path, previous[path], value, timestamp)
                   for path, value in self.values.items() if path in previous and (value != previous[path] or path in self.resolutions)]
        for path, before, after in (
            ('family.children', self.original.family.children, draft.family.children),
            ('family.parents', self.original.family.parents, draft.family.parents),
            ('activities', self.original.activities, draft.activities),
        ):
            for i in range(len(before), len(after)):
                changes.append(ReviewChange(f'{path}[{i}]', '', json.dumps(asdict(after[i]), ensure_ascii=False), timestamp))
        draft.review_changes.extend(changes)
        # Track edits, deletions and confirmations to proposed structured history.
        for name in ('residence_records', 'travel_records'):
            before, after = getattr(self.original, name), getattr(draft, name)
            if before != after:
                change = ReviewChange(name, json.dumps([asdict(r) for r in before], ensure_ascii=False),
                                      json.dumps([asdict(r) for r in after], ensure_ascii=False), timestamp)
                changes.append(change)
                draft.review_changes.append(change)
        from .preparation import prepare_case
        from .validation import validate_case
        prepare_case(draft)
        validate_case(draft)
        for field in fields(draft):
            setattr(self.case, field.name, deepcopy(getattr(draft, field.name)))
        self.original = deepcopy(self.case)
        self.draft = deepcopy(self.case)
        self.values = editable_fields(self.case)
        self.resolutions = {}
        return changes
