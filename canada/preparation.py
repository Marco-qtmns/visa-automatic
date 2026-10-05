"""Conservative, repeatable intake preparation; source answers remain immutable."""
from datetime import datetime
import hashlib
import json
import re
import unicodedata

from .models import Activity, HistoryRecord


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(c)).strip()


def date_value(value):
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%Y-%m', '%m/%Y'):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            return parsed.strftime('%Y-%m') if fmt in ('%Y-%m', '%m/%Y') else parsed.strftime('%Y-%m-%d')
        except ValueError:
            pass
    raise ValueError('Use YYYY-MM-DD, DD/MM/YYYY or a month as YYYY-MM / MM/YYYY')


def date_bounds(value):
    from calendar import monthrange
    result=date_value(value)
    if len(result)==10: return result,result
    year,month=map(int,result.split('-'))
    return result+'-01',result+f'-{monthrange(year,month)[1]:02d}'


def record_digest(record):
    values = [record.country, record.status_or_purpose, record.start_date,
              record.end_date, record.source_text, record.source_role]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def record_errors(record):
    errors = []
    if not record.country.strip(): errors.append('Country is missing')
    if not record.status_or_purpose.strip(): errors.append('Status/purpose is missing')
    try:
        start, end = date_value(record.start_date), date_value(record.end_date)
        if date_bounds(record.start_date)[0] > date_bounds(record.end_date)[1]: errors.append('End date precedes start date')
    except ValueError as error:
        errors.append(str(error))
    return errors


def is_confirmed(record):
    return not record_errors(record) and (record.confirmation_digest == record_digest(record) or record.parsed_digest == record_digest(record))


DATE = r'(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{4}-\d{2}|\d{2}/\d{4})'


def parse_narrative(text, role):
    """Parse explicit delimited rows; preserve every unparsed phrase for review.

    Never guess a country from a city or dates from a year alone. Suggestions
    require confirmation, including rows that match the supported grammar.
    """
    if not text.strip(): return []
    records = []
    # Semicolons separate records only where each segment contains a date pair.
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    for line in lines:
        pieces = line.split(';')
        if len(pieces) > 1 and all(len(re.findall(DATE, p)) == 2 for p in pieces):
            lines_to_parse = pieces
        else:
            lines_to_parse = [line]
        for raw in lines_to_parse:
            record = HistoryRecord(source_text=raw.strip(), source_role=role,
                                   source_block_index=len(records) + 1)
            dates = list(re.finditer(DATE, raw))
            if len(dates) == 2:
                try:
                    record.start_date = date_value(dates[0][0])
                    record.end_date = date_value(dates[1][0])
                except ValueError:
                    record.start_date = record.end_date = ''
                prefix = raw[:dates[0].start()].strip(' ,;|+-')
                # Explicit country + status/purpose columns only.
                parts = [p.strip() for p in re.split(r'\s*[|;+]\s*|,\s*', prefix) if p.strip()]
                if len(parts) == 2 and not raw[dates[1].end():].strip(' ,;|.'):
                    record.country = re.sub(r'^(?:país|pais|country)\s*:\s*', '', parts[0], flags=re.I)
                    record.status_or_purpose = re.sub(r'^(?:status(?: migratório)?|purpose|motivo)\s*:\s*', '', parts[1], flags=re.I)
                else:
                    # Common free-text phrasing still produces proposals, never
                    # facts: the complete original sentence stays next to them.
                    narrative = re.fullmatch(
                        r'(?:(?:morei|residi|vivi|viajei)\s+(?:em|no|na)|(?:lived|travelled)\s+in)\s+'
                        r'(.+?)\s+(?:como|as|para|for)\s+(.+?)\s+(?:de|entre|from)?\s*',
                        prefix, flags=re.I)
                    if narrative:
                        record.country, record.status_or_purpose = narrative.groups()
                    else:
                        columns = [s.strip() for s in re.split(r'[|;+]',raw)]
                        if len(columns) == 4:
                            non_dates = [s for s in columns if not re.fullmatch(DATE,s)]
                            if len(non_dates) == 2:
                                record.country,record.status_or_purpose = non_dates
            # Only the explicit four-column travel grammar is auto-accepted.
            if role == 'travel':
                match = re.fullmatch(r'(.+?)\s+-\s+(' + DATE + r')\s+-\s+(' + DATE + r')\s+-\s+(.+)', raw.strip())
                if match:
                    record.country, record.start_date, record.end_date, record.status_or_purpose = match.groups()
                explicit = bool(match) or len(re.split(r'[|;+]', raw)) == 4
                if explicit and not record_errors(record):
                    record.parsed_digest = record_digest(record)
            records.append(record)
    return records


def child_given_names(surname, entered):
    """Owner-confirmed surname/child-name contract for the verified CSV only."""
    family, name = surname.split(), entered.split()
    if not family or not name: return ''
    a, b = [norm(w) for w in family], [norm(w) for w in name]
    if len(b) > len(a):
        prefix, suffix = b[:len(a)] == a, b[-len(a):] == a
        if prefix and suffix: return ''
        if suffix: return ' '.join(name[:-len(a)])
        if prefix: return ' '.join(name[len(a):])
    # If the complete surname is absent, the second field already contains
    # given names under the owner's contract. Partial overlap needs review.
    if set(a) & set(b): return ''
    return entered.strip()


def _prepare(case):
    """Fill unambiguous empty derived fields; never overwrite staff corrections."""
    reviewed = {change.path for change in case.review_changes}
    if case.import_profile == 'verified_20260929':
        for i,child in enumerate(case.family.children):
            if not child.given_names and f'family.children[{i}].given_names' not in reviewed:
                child.given_names = child_given_names(child.family_name, child.full_name)
        answer = case.relationships.spouse_residence_answer.strip()
        if answer and not case.relationships.spouse_address and 'relationships.spouse_address' not in reviewed:
            if norm(answer) in ('sim', 'yes'):
                case.relationships.spouse_address = case.contact.address
            elif norm(answer) not in ('nao', 'no', 'outro', 'other', 'n/a', 'nao se aplica'):
                case.relationships.spouse_address = re.sub(r'^(?:outro|other)\s*:\s*', '', answer, flags=re.I).strip()
    if not case.narrative_proposals_digest and (case.history.previous_residences.strip() or case.history.travel_details.strip()):
        if norm(case.identity.previous_residence_5y) not in ('no', 'nao') and not case.residence_records and case.history.previous_residences.strip():
            case.residence_records = parse_narrative(case.history.previous_residences, 'residence')
        if not case.travel_records and case.history.travel_details.strip():
            case.travel_records = parse_narrative(case.history.travel_details, 'travel')
        case.narrative_proposals_digest = hashlib.sha256(json.dumps([
            case.history.previous_residences, case.history.travel_details]).encode()).hexdigest()
    # Current employment is a distinct source block and is not lost behind the
    # four historical activity slots. Existing staff records keep their order.
    job = case.employment
    if any((job.profession, job.organization, job.start_date)) and not any(a.source_role == 'current_employment' for a in case.activities):
        case.activities.append(Activity(position=job.profession, organization=job.organization,
            city=job.city, state=job.state, start_date=job.start_date, ongoing_answer='',
            source_role='current_employment'))
    for activity in case.activities:
        if not activity.position and activity.activity_type:
            labels = {'desempregado':'Unemployed', 'desempregada':'Unemployed', 'estudante':'Student', 'aposentado':'Retired', 'aposentada':'Retired'}
            activity.position = labels.get(norm(activity.activity_type), '')
    return case


def ordered_activities(case):
    """Return original model indices, allowing every exported row to be traced."""
    rows = [(i,a) for i,a in enumerate(case.activities)
            if any((a.position,a.organization,a.activity_type,a.start_date,a.end_date,a.city,a.country))]
    def key(row):
        _, a = row
        try: start = date_value(a.start_date)
        except ValueError: start = ''
        return (norm(a.ongoing_answer) in ('yes','sim'), start)
    return sorted(rows, key=key, reverse=True)


def application_date(case):
    value = case.staff_review.application_date or next((v[0] for k,v in case.raw_response.items()
        if norm(k) == 'carimbo de data/hora' and v), '')
    try:
        parsed = date_value(value.split(' ')[0])
        return parsed if len(parsed) == 10 else ''
    except ValueError:
        return ''


def activity_status(activity, submitted):
    if not activity.start_date: return 'unknown'
    try:
        start = date_value(activity.start_date)
        end = date_value(activity.end_date) if activity.end_date and norm(activity.end_date) not in ('atual','presente','present','ongoing','ate o momento') else ''
        if end and date_bounds(activity.end_date)[1] < date_bounds(activity.start_date)[0]: return 'invalid'
        if submitted and date_bounds(activity.start_date)[0] > submitted: return 'invalid_or_future'
        if activity.source_role == 'current_employment': return 'ongoing'
        if norm(activity.ongoing_answer) in ('yes','sim'): return 'ongoing'
        if submitted and end and date_bounds(activity.end_date)[0] > submitted: return 'invalid_or_future'
        if norm(activity.ongoing_answer) in ('no','nao') and end: return 'completed'
        if not end: return 'unknown'
        if submitted and date_bounds(activity.end_date)[1] < submitted: return 'completed'
        return 'needs_confirmation'
    except ValueError:
        return 'invalid'


def prepare_case(case):
    from .review import editable_fields
    from .provenance import mark, apply_overrides
    from uuid import uuid4
    from .verified_intake import restore_explicit_applicant
    restore_explicit_applicant(case)
    apply_overrides(case)
    before = editable_fields(case)
    for i,a in enumerate(case.activities):
        path=f'activities[{i}].ongoing_answer'
        origin=case.provenance.get(path)
        if origin and origin.source_type=='derived_rule' and path not in case.overrides:
            a.ongoing_answer=''
    narrative_values=[case.history.previous_residences,case.history.travel_details]
    old_digest=hashlib.sha256(json.dumps(narrative_values).encode()).hexdigest()
    new_digest=hashlib.sha256(json.dumps(narrative_values+[case.identity.previous_residence_5y]).encode()).hexdigest()
    if case.narrative_proposals_digest and case.narrative_proposals_digest not in (old_digest,new_digest):
        case.residence_records=[]
        case.travel_records=[]
        case.narrative_proposals_digest=''
    if norm(case.identity.previous_residence_5y) in ('no','nao'):
        case.residence_records = []
    _prepare(case)
    if case.narrative_proposals_digest: case.narrative_proposals_digest=new_digest
    submitted = application_date(case)
    for i,p in enumerate(case.family.parents):
        p.id = p.id or f'parent-{p.source_block_index or i+1}'
        if case.import_profile == 'verified_20260929' and not p.confirmed_role:
            p.confirmed_role = {1:'father',2:'mother'}.get(p.source_block_index, '')
        if case.import_profile == 'verified_20260929' and not p.given_names and p.full_name and f'family.parents[{i}].given_names' not in case.overrides:
            # Older saved cases used full_name for the now-confirmed given-name column.
            p.given_names = p.full_name
        p.guardian_status = ''
        try:
            born = date_value(case.identity.date_of_birth)
            if len(born) == 10 and submitted:
                by,bm,bd = map(int,born.split('-')); ay,am,ad = map(int,submitted.split('-'))
                age = ay-by-((am,ad)<(bm,bd))
                p.guardian_status = 'not_required' if age >= 18 else case.staff_review.legal_guardian
        except ValueError: pass
        mark(case,f'family.parents[{i}].guardian_status',p.guardian_status,'derived_rule','age_at_application',True)
    for i,a in enumerate(case.activities):
        a.id = a.id or (f'{a.source_role or "activity"}-{a.source_block_index or i+1}' if a.source_role != 'staff' else str(uuid4()))
        a.raw_source = a.raw_source or json.dumps({k:v for k,v in before.items() if k.startswith('employment.' if a.source_role == 'current_employment' else f'activities[{i}].')},ensure_ascii=False)
        a.status = activity_status(a, submitted)
        if a.status == 'ongoing': a.ongoing_answer = 'Yes'
        elif a.status == 'completed': a.ongoing_answer = 'No'
        if not a.ongoing_answer and f'activities[{i}].ongoing_answer' not in case.overrides:
            case.provenance.pop(f'activities[{i}].ongoing_answer',None)
        mark(case,f'activities[{i}].status',a.status,'derived_rule','activity_dates_and_source_block',True)
        if not a.description and a.source_role == 'current_employment': a.description=case.employment.duties
    for kind in ('residence','travel'):
        for i,r in enumerate(getattr(case,kind+'_records')):
            r.id = r.id or f'{kind}-{r.source_block_index or i+1}'
    for path,value in editable_fields(case).items():
        if value and value != before.get(path,''):
            mark(case,path,value,'derived_rule','prepare_case:'+path,True)
    for kind in ('residence','travel'):
        for i,r in enumerate(getattr(case,kind+'_records')):
            for name in ('country','status_or_purpose','start_date','end_date'):
                path=f'{kind}_records[{i}].{name}'
                if path not in case.overrides and getattr(r,name):
                    mark(case,path,getattr(r,name),'parsed_explicit',r.source_text,is_confirmed(r))
    prepare_official_answers(case)
    # Reapplying the same staff choice must retain its provenance.
    apply_overrides(case)
    return case


def supported_official_answers(case):
    """Only implications justified by the exact verified question contract."""
    if case.import_profile != 'verified_20260929': return {}
    yes = lambda value: norm(value) in ('yes','sim')
    answers={}
    if yes(case.history.canada_refusal_answer) or yes(case.history.other_refusal_answer):
        sources=[name for name in ('canada_refusal_answer','other_refusal_answer') if yes(getattr(case.history,name))]
        answers['visa_refusal_denied_entry_or_removal_any_country']=('Yes',','.join('history.'+name for name in sources))
    if yes(case.history.previous_canada_visa_answer):
        answers['previously_applied_to_enter_or_remain_canada']=('Yes','history.previous_canada_visa_answer')
    # Explicit attendance at a post-secondary level proves 'ever attended'; a
    # lower/unknown most-recent level does not prove the opposite.
    level=norm(case.education.level)
    if any(label in level for label in ('ensino superior','superior completo','superior incompleto','pos-graduacao','mestrado','doutorado')):
        answers['post_secondary_education']=('Yes','education.level')
    # Intake asks any other country for >=6 months in the last five years.
    # No covers the official narrower >6-month/excluded-country condition;
    # Yes does not resolve that threshold or those exclusions.
    if norm(case.identity.previous_residence_5y) in ('no','nao'):
        answers['previous_residence_over_six_months']=('No','identity.previous_residence_5y')
    criminal=norm(case.history.criminal_history_answer)
    if criminal in ('yes','sim','no','nao'):
        answers['committed_arrested_charged_or_convicted_any_country']=('Yes' if criminal in ('yes','sim') else 'No','history.criminal_history_answer')
    return answers


def prepare_official_answers(case):
    from .provenance import mark, source_digest
    supported=supported_official_answers(case)
    # Invalidate this rule's prior result when its source changes or disappears.
    for path,origin in list(case.provenance.items()):
        item=case.overrides.get(path)
        if origin.source_ref.startswith('official-answer:') and not (item and item.source_digest==source_digest(case)):
            setattr(case.official_review,path.split('.')[1],'')
            del case.provenance[path]
    for name,(answer,source) in supported.items():
        path='official_review.'+name
        override=case.overrides.get(path)
        if override and override.source_digest==source_digest(case): continue
        if override: setattr(case.official_review,name,'')
        if not getattr(case.official_review,name):
            setattr(case.official_review,name,answer)
            mark(case,path,answer,'derived_rule','official-answer:'+source,True)
