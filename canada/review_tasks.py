"""Human tasks over existing validation issues; grouping never clears a gate."""
from dataclasses import dataclass, field
from .validation import ValidationIssue, validate_case, issue_text
from .review import editable_fields


@dataclass
class ReviewTask:
    id: str
    title: str
    acceptance: str
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def status(self):
        return 'ERROR' if any(i.status == 'ERROR' for i in self.issues) else 'REVIEW'


TITLES = {
    'identity':'Complete applicant identity',
    'address':'Confirm residential address',
    'activities':'Complete the activity timeline and countries',
    'finances':'Confirm available CAD funds and evidence',
    'education':'Complete education details',
    'health':'Answer health questions and provide details',
    'immigration':'Review immigration history and explanations',
    'security':'Review criminal, service and security history',
    'source':'Reconcile the changed source',
}


def task_key(issue):
    path=issue.field
    if issue.code in ('CSV_SCHEMA_MISMATCH','STAFF_OVERRIDE_STALE'): return 'source'
    if path.startswith('activities'): return 'activities'
    if path.startswith('contact.'): return 'address'
    if path.startswith('trip.'): return 'finances'
    if path.startswith('education.') or path=='education' or path=='official_review.post_secondary_education': return 'education'
    if path.startswith(('residence_records[','travel_records[')):
        return path.split('].')[0].rstrip(']')+']'
    if path.startswith('family.'):
        return path.split('].')[0].rstrip(']')+']' if '[' in path else path
    if path.startswith('official_review.'):
        if any(word in path for word in ('medical','tuberculosis','disorder')): return 'health'
        if any(word in path for word in ('committed','criminal','military','service','violent','witnessed')): return 'security'
        return 'immigration'
    return 'identity'


def review_tasks(case):
    grouped={}
    for issue in validate_case(case).issues:
        key=task_key(issue)
        if key not in grouped:
            title=TITLES.get(key)
            if title is None:
                label='Residence' if key.startswith('residence') else 'Trip' if key.startswith('travel') else 'Parent' if key.startswith('family.parents') else 'Child' if key.startswith('family.children') else 'Family member'
                number=key.split('[')[-1].rstrip(']')
                title=f'Complete {label.lower()} {int(number)+1}' if number.isdigit() else 'Review family information'
            grouped[key]=ReviewTask(key,title,'necessary')
        grouped[key].issues.append(issue)
    for task in grouped.values():
        if len(task.issues)>1: task.acceptance='badly_presented'
    return list(grouped.values())


def task_fields(task, case):
    """Only relevant canonical fields, no new form-specific data model."""
    available=editable_fields(case)
    paths=[]
    for issue in task.issues:
        if issue.resolution_type=='batch_confirm_or_edit': paths.extend(issue.source_values)
        elif issue.field in available: paths.append(issue.field)
        elif issue.code=='FAMILY_NAME_INCOMPLETE':
            paths.extend(issue.field+'.'+f for f in ('family_name','given_names'))
        elif issue.code=='EDUCATION_LOCATION_INCOMPLETE': paths.extend(('education.city','education.state'))
        elif issue.field.startswith(('residence_records[','travel_records[')):
            paths.extend(issue.field+'.'+f for f in ('country','status_or_purpose','start_date','end_date'))
        elif issue.field.startswith('activities['):
            paths.extend(issue.field+'.'+f for f in ('start_date','end_date','ongoing_answer','country'))
        elif issue.field=='activities':
            for i,a in enumerate(case.activities):
                if any((a.position,a.activity_type,a.organization,a.start_date,a.end_date)):
                    paths.extend(f'activities[{i}].'+f for f in ('position','start_date','end_date','ongoing_answer','country'))
    # Keep conditional explanations beside their questions, so a Yes answer
    # does not require reopening the task merely to enter its details.
    if task.id=='health': paths.append('official_review.medical_details')
    if task.id=='immigration': paths.append('official_review.immigration_explanation')
    if task.id=='security': paths.extend(('official_review.criminal_details','official_review.service_details'))
    if task.id=='education': paths.extend(('education.city','education.state'))
    if task.id=='finances': paths.extend(('trip.available_funds_cad','trip.funds_source_reference'))
    return list(dict.fromkeys(path for path in paths if path in available))


def field_label(path):
    from .compact_review import QUESTIONS
    if path in QUESTIONS: return QUESTIONS[path]
    if path in ('education.city','education.state'): return 'If post-secondary education is Yes: institution '+path.split('.')[1]
    words=path.replace('family.','').split('.')
    group=words[0]
    if '[' in group:
        name,index=group.rstrip(']').split('[')
        group=f'{name.replace("_records", "").replace("_", " ").title()} {int(index)+1}'
    return group.title()+': '+words[-1].replace('_',' ')


def task_text(task):
    from .compact_review import QUESTIONS
    lines=[task.title]
    for issue in task.issues:
        lines.append('- '+QUESTIONS.get(issue.field,issue_text(issue)))
        if issue.suggested_value: lines.append('  Suggestion (not yet confirmed): '+issue.suggested_value)
        lines.extend('  '+key+': '+value for key,value in issue.source_values.items())
    return '\n'.join(lines)


def automated_answers(case):
    from copy import deepcopy
    from .preparation import prepare_case
    prepared=prepare_case(deepcopy(case))
    return [{'field':path,'value':origin.value,'acceptance':'can_be_automated','source_ref':origin.source_ref}
            for path,origin in prepared.provenance.items()
            if origin.source_type=='derived_rule' and origin.source_ref.startswith('official-answer:')]
