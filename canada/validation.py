"""Structured, deduplicated validation of CanadaCase, independent of widgets."""
from dataclasses import dataclass, field as dc_field
from copy import deepcopy
from .preparation import prepare_case, norm, date_value, application_date, is_confirmed, record_errors, date_bounds
from .provenance import confirmed


@dataclass
class ValidationIssue:
    code: str
    entity_type: str
    entity_id: str
    field: str
    severity: str = 'blocking'
    resolution_type: str = 'staff_input'
    suggested_value: str = ''
    source_values: dict[str, str] = dc_field(default_factory=dict)
    status: str = 'REVIEW'

    @property
    def identity(self):
        return self.code, self.entity_type, self.entity_id, self.field


def deduplicate(issues):
    return list({issue.identity: issue for issue in issues}.values())


@dataclass
class ValidationResult:
    issues: list[ValidationIssue]

    @property
    def status(self):
        return 'ERROR' if any(i.status == 'ERROR' for i in self.issues) else 'REVIEW' if self.issues else 'VALID'


LABELS = {
    'OFFICIAL_DETAILS_MISSING': 'Provide details for the confirmed Yes answer',
    'OFFICIAL_SOURCE_CONFLICT': 'The official answer contradicts an explicit intake answer; reconcile both',
    'RESIDENCE_RECORD_INCOMPLETE': 'Complete this previous-residence record from the original text',
    'RESIDENCE_DATE_RANGE_INVALID': 'Residence end precedes start or contains an invalid date',
    'OFFICIAL_ANSWER_MISSING': 'Confirm the complete official question in Official questions',
    'STAFF_OVERRIDE_STALE': 'Source changed; confirm or replace this previous staff correction',
    'APPLICANT_SEX_MISSING': 'Sex is missing; confirm explicitly',
    'BIRTH_COUNTRY_MISSING': 'Missing birth country; confirm explicitly',
    'ADDRESS_COUNTRY_CONFIRMATION': 'Staff: confirm address country; keep the complete address line intact',
    'ACTIVITY_COUNTRIES_MISSING_BATCH': 'Confirm the countries for all listed activities together, or edit individually',
    'ACTIVITY_COUNTRY_MISSING': 'Confirm activity country',
    'ACTIVITY_START_MISSING': 'Enter the start date for this activity',
    'ACTIVITY_END_MISSING': 'Enter the end date for this completed activity',
    'ACTIVITY_STATUS_CONFIRMATION': "Confirm ongoing status; source permits today's date as an end-date placeholder",
    'ACTIVITY_DATE_RANGE_INVALID': 'Activity dates are invalid or end precedes start',
    'ACTIVITY_DATE_FUTURE': 'Activity dates extend beyond the application date; review',
    'TRAVEL_RECORD_INCOMPLETE': 'Travel narrative: complete this record from the original text',
    'TRAVEL_DATE_RANGE_INVALID': 'Travel exit precedes entry or contains an invalid date',
    'HISTORY_CONFIRMATION': 'Review and confirm the residence/travel narrative record',
    'EDUCATION_LOCATION_INCOMPLETE': 'Enter institution city and state for post-secondary education',
    'AVAILABLE_FUNDS_CAD_MISSING': 'Enter available funds in CAD; estimated spending is a separate fact',
    'FUNDS_SOURCE_MISSING': 'Record the source reference for available funds',
    'LEGAL_GUARDIAN_REQUIRED': 'Confirm legal guardian: father, mother, both or other',
    'APPLICATION_DATE_MISSING': 'Enter the application date to determine age and activity status',
    'PARENT_ROLE_MISSING': 'Confirm mother or father for this unverified parent block',
    'FAMILY_NAME_INCOMPLETE': 'Confirm separate name components',
    'FAMILY_BIRTH_COUNTRY_MISSING': 'Confirm birth country',
    'CHILDREN_CONFLICT': 'Children declared No but child names are present; review source answers',
    'PARENT_ROLE_CONFLICT': 'Multiple records assigned to the same mother/father role',
    'CSV_SCHEMA_MISMATCH': 'Header support is provisional; reconcile the CSV schema',
    'REQUIRED_FIELD_MISSING': 'Required field is missing',
    'ACTIVITY_TIMELINE_GAP': 'Activity timeline gap: review uncovered periods',
    'BIRTH_DATE_INVALID': 'Birth date is invalid or after the application date',
    'AVAILABLE_FUNDS_INVALID': 'Available funds must be a non-negative CAD amount',
}


def issue_text(issue):
    label = LABELS.get(issue.code, issue.code.replace('_', ' ').capitalize())
    prefix = issue.entity_id
    if issue.entity_type in ('parent','child'):
        prefix = f'{issue.entity_type.title()} block {issue.source_values.get("block", issue.entity_id)}'
    return f'{prefix}: {label} ({issue.field}) [{issue.code}]'


BRAZIL_STATES = set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.lower().split())
BRAZIL_STATES.update(norm(s) for s in ('Acre','Alagoas','Amapá','Amazonas','Bahia','Ceará','Distrito Federal','Espírito Santo','Goiás','Maranhão','Mato Grosso','Mato Grosso do Sul','Minas Gerais','Pará','Paraíba','Paraná','Pernambuco','Piauí','Rio de Janeiro','Rio Grande do Norte','Rio Grande do Sul','Rondônia','Roraima','Santa Catarina','São Paulo','Sergipe','Tocantins'))


def validate_case(source):
    # Validation is pure for the caller. All consumers use the same preparation.
    case = prepare_case(deepcopy(source))
    issues = []
    def add(code, field, entity='applicant', id='applicant', resolution='staff_input',
            suggestion='', values=None, status='REVIEW', severity='blocking'):
        issues.append(ValidationIssue(code,entity,id,field,severity,resolution,suggestion,values or {},status))
    for path,value in [('identity.family_name',case.identity.family_name),('identity.given_names',case.identity.given_names),
                       ('identity.date_of_birth',case.identity.date_of_birth),('passport.number',case.passport.number)]:
        if not value.strip(): add('REQUIRED_FIELD_MISSING',path)
    if not case.identity.sex: add('APPLICANT_SEX_MISSING','identity.sex')
    if not case.identity.birth_country:
        add('BIRTH_COUNTRY_MISSING','identity.birth_country',resolution='confirm_or_edit',
            suggestion='Brazil' if norm(case.identity.state_of_birth) in BRAZIL_STATES else '')
    if case.contact.address and not (case.contact.country and confirmed(case,'contact.country',case.contact.country)):
        add('ADDRESS_COUNTRY_CONFIRMATION','contact.country',resolution='confirm_or_edit',
            suggestion=case.contact.country or case.identity.residence_country,
            values={'raw_line':case.contact.address})
    from .provenance import source_digest
    for path,item in case.overrides.items():
        if item.source_digest != source_digest(case):
            add('STAFF_OVERRIDE_STALE',path,'case',case.case_id,resolution='confirm_or_edit',suggestion=item.value)
    submitted = application_date(case)
    if not submitted: add('APPLICATION_DATE_MISSING','staff_review.application_date')
    if case.identity.date_of_birth:
        try:
            born = date_value(case.identity.date_of_birth)
            if len(born) != 10 or (submitted and born > submitted): raise ValueError()
            if submitted:
                by,bm,bd = map(int,born.split('-')); ay,am,ad = map(int,submitted.split('-'))
                if ay-by-((am,ad)<(bm,bd)) < 18 and case.staff_review.legal_guardian not in ('father','mother','both','other'):
                    add('LEGAL_GUARDIAN_REQUIRED','staff_review.legal_guardian')
        except ValueError: add('BIRTH_DATE_INVALID','identity.date_of_birth',status='ERROR')
    for group in ('parents','children'):
        for i,p in enumerate(getattr(case.family,group)):
            if not any((p.family_name,p.given_names,p.full_name)): continue
            entity='parent' if group=='parents' else 'child'
            path=f'family.{group}[{i}]'; values={'block':str(p.source_block_index or i+1)}
            if entity=='parent' and p.confirmed_role not in ('father','mother'):
                add('PARENT_ROLE_MISSING',path+'.confirmed_role',entity,p.id or str(i),values=values)
            if not p.family_name or not p.given_names:
                add('FAMILY_NAME_INCOMPLETE',path,entity,p.id or str(i),values=values)
            if not p.birth_country:
                add('FAMILY_BIRTH_COUNTRY_MISSING',path+'.birth_country',entity,p.id or str(i),values=values)
    roles=[p.confirmed_role for p in case.family.parents if p.confirmed_role]
    if any(roles.count(r)>1 for r in ('father','mother')):
        add('PARENT_ROLE_CONFLICT','family.parents',status='ERROR')
    if norm(case.family.has_children_answer) in ('no','nao') and any(
        norm(v) not in ('','n/a','nao se aplica') for p in case.family.children for v in (p.full_name,p.family_name,p.given_names)):
        add('CHILDREN_CONFLICT','family.children',status='ERROR')
    missing=[]; intervals=[]
    for i,a in enumerate(case.activities):
        if not any((a.position,a.activity_type,a.organization,a.start_date,a.end_date)): continue
        path=f'activities[{i}]'
        if not a.country: missing.append((path+'.country',a.id))
        if not a.start_date:
            add('ACTIVITY_START_MISSING',path+'.start_date','activity',a.id)
        elif norm(a.ongoing_answer) in ('no','nao') and not a.end_date:
            add('ACTIVITY_END_MISSING',path+'.end_date','activity',a.id)
        elif a.status=='invalid': add('ACTIVITY_DATE_RANGE_INVALID',path,'activity',a.id,status='ERROR')
        elif a.status=='invalid_or_future': add('ACTIVITY_DATE_FUTURE',path,'activity',a.id)
        elif a.status in ('unknown','needs_confirmation'):
            add('ACTIVITY_STATUS_CONFIRMATION',path+'.ongoing_answer','activity',a.id,resolution='confirm_or_edit')
        if a.status in ('ongoing','completed'):
            try:
                intervals.append((date_value(a.start_date)[:7], (submitted or '')[:7] if a.status=='ongoing' else date_value(a.end_date)[:7]))
            except ValueError: pass
    if missing:
        add('ACTIVITY_COUNTRIES_MISSING_BATCH' if len(missing)>1 else 'ACTIVITY_COUNTRY_MISSING',
            'activities' if len(missing)>1 else missing[0][0], 'activity','batch' if len(missing)>1 else missing[0][1],
            resolution='batch_confirm_or_edit' if len(missing)>1 else 'confirm_or_edit',suggestion='Brazil',values=dict(missing))
    if intervals and submitted:
        intervals.sort(); end=intervals[0][1]
        gaps=[]
        for start,stop in intervals[1:]:
            if not end: continue
            y,m=map(int,end.split('-')); next_month=f'{y+(m==12):04d}-{1 if m==12 else m+1:02d}'
            if start>next_month: gaps.append(end+' / '+start)
            end=max(end,stop)
        cutoff=f'{int(submitted[:4])-10:04d}'+submitted[4:7]
        if intervals[0][0]>cutoff: gaps.append('Beginning of ten-year period / applicable age scope')
        if end<submitted[:7]: gaps.append('Through application date')
        if gaps: add('ACTIVITY_TIMELINE_GAP','activities','activity','timeline',values={'gaps':'; '.join(gaps)})
    for kind in ('residence','travel'):
        for i,r in enumerate(getattr(case,kind+'_records')):
            errors=record_errors(r)
            if errors:
                invalid=False
                if r.start_date and r.end_date:
                    try: invalid=date_bounds(r.end_date)[1]<date_bounds(r.start_date)[0]
                    except ValueError: invalid=True
                add(('TRAVEL_' if kind=='travel' else 'RESIDENCE_')+('DATE_RANGE_INVALID' if invalid else 'RECORD_INCOMPLETE'),
                    f'{kind}_records[{i}]',kind,r.id,status='ERROR' if invalid else 'REVIEW',values={'raw_text':r.source_text})
            elif not is_confirmed(r):
                add('HISTORY_CONFIRMATION',f'{kind}_records[{i}]',kind,r.id,resolution='confirm_or_edit',values={'raw_text':r.source_text})
    level=norm(case.education.level)
    if (any(v in level for v in ('ensino superior','superior completo','superior incompleto','pos-graduacao','mestrado','doutorado')) or norm(case.official_review.post_secondary_education) in ('yes','sim')) and (not case.education.city or not case.education.state):
        add('EDUCATION_LOCATION_INCOMPLETE','education','education','education')
    spending={'estimated_trip_spending':case.trip.estimated_spend,'estimated_trip_spending_currency':case.trip.estimated_spend_currency}
    if not case.trip.available_funds_cad: add('AVAILABLE_FUNDS_CAD_MISSING','trip.available_funds_cad','finances','finances',values=spending)
    else:
        from decimal import Decimal, InvalidOperation
        try:
            amount=Decimal(case.trip.available_funds_cad)
            if not amount.is_finite() or amount<0: raise InvalidOperation()
        except InvalidOperation: add('AVAILABLE_FUNDS_INVALID','trip.available_funds_cad','finances','finances',status='ERROR')
        if not case.trip.funds_source_reference: add('FUNDS_SOURCE_MISSING','trip.funds_source_reference','finances','finances')
    from .preparation import supported_official_answers
    for name,(answer,source_ref) in supported_official_answers(case).items():
        if getattr(case.official_review,name) and norm(getattr(case.official_review,name)) not in (('yes','sim') if answer=='Yes' else ('no','nao')):
            add('OFFICIAL_SOURCE_CONFLICT','official_review.'+name,'official','IMM5257',
                values={'source_fields':source_ref,'source_implies':answer})
    detail_rules={
        'medical_details':('tuberculosis_or_close_contact_last_two_years','disorder_requiring_social_or_health_services'),
        'immigration_explanation':('canada_overstay_unauthorized_work_or_study','visa_refusal_denied_entry_or_removal_any_country','previously_applied_to_enter_or_remain_canada'),
        'criminal_details':('committed_arrested_charged_or_convicted_any_country',),
        'service_details':('military_militia_civil_defence_security_or_police',),
    }
    for detail,questions in detail_rules.items():
        if any(norm(getattr(case.official_review,q)) in ('yes','sim') for q in questions) and not getattr(case.official_review,detail).strip():
            add('OFFICIAL_DETAILS_MISSING','official_review.'+detail,'official','IMM5257')
    from .official_options import YES_NO_FIELDS
    for name in YES_NO_FIELDS:
        if not getattr(case.official_review,name):
            add('OFFICIAL_ANSWER_MISSING','official_review.'+name,'official','IMM5257')
    if case.import_profile.endswith('unverified'): add('CSV_SCHEMA_MISMATCH','source_headers',status='ERROR')
    return ValidationResult(deduplicate(issues))


def ensure_generation_allowed(case, final=False):
    result=validate_case(case)
    blocked=[i for i in result.issues if i.status=='ERROR' or (final and i.severity=='blocking')]
    if blocked:
        raise ValueError('Canada validation prevents generation: '+', '.join(i.code for i in blocked))
    return result
