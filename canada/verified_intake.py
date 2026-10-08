"""Index mapping valid ONLY for the verified 234-column September 2026 schema.

The exact ordered header hash guards the duplicate/mislabelled parent-country
column. A changed, missing or reordered header must never reuse these offsets.
The owner defines the first parent block as father, the second as mother, and
the parent column following surname as given names in this exact schema. These
semantics come from the fingerprint-bound mapping, never from a person's name.
"""
from .models import Activity, CanadaCase, DocumentReference, FamilyMember

HEADER_SHA256 = '81820c7095e89bb2809f1c674838a95a088524b15efa4e70827a7b535ac0117b'
PROFILE = 'verified_20260929'


def _group(start, prefix, names):
    return {start + i: prefix + '.' + name for i, name in enumerate(names)}


COLUMN_TARGETS = {
    **_group(1, 'identity', ['family_name', 'given_names', 'other_names', 'date_of_birth',
        'city_of_birth', 'state_of_birth', 'nationality', 'other_citizenship',
        'residence_country', 'residence_status', 'residence_since', 'previous_residence_5y']),
    13: 'history.previous_residences', 14: 'identity.marital_status',
    **_group(15, 'relationships', ['marriage_start_date', 'spouse_family_name', 'spouse_given_names',
        'spouse_date_of_birth', 'spouse_birth_country', 'spouse_occupation', 'spouse_residence_answer',
        'spouse_accompanying_answer', 'has_previous_relationship', 'former_spouse_family_name',
        'former_spouse_given_names', 'former_spouse_date_of_birth', 'former_spouse_birth_country',
        'previous_relationship_type', 'previous_start_date', 'previous_end_date',
        'former_spouse_birth_city', 'former_spouse_occupation', 'former_spouse_address']),
    34: 'identity.languages', 35: 'identity.language_test_answer',
    **_group(36, 'passport', ['number', 'issuing_country', 'issue_date', 'expiry_date',
        'has_other_valid_passport', 'other_passport_details', 'identity_number', 'identity_country',
        'identity_issue_date', 'identity_expiry_date', 'green_card_details']),
    **_group(47, 'contact', ['address', 'city', 'state', 'postcode', 'email', 'phone']),
    **_group(53, 'trip', ['purpose', 'arrival_date', 'departure_date', 'duration_days',
        'estimated_spend', 'payer', 'payer_details', 'visiting_person_or_institution',
        'host_name', 'relationship', 'family_relationship', 'host_status', 'host_address',
        'host_postcode', 'host_phone', 'host_email']),
    **_group(69, 'education', ['level', 'institution', 'course', 'start_date', 'end_date', 'country']),
    **_group(75, 'employment', ['start_date', 'profession', 'duties', 'organization', 'city', 'state',
        'has_other_activities_answer']),
    133: 'family.has_children_answer',
    193: 'family.siblings_abroad_answer', 194: 'family.siblings_abroad_details',
    **_group(195, 'history', ['travelled_abroad_answer', 'travel_details', 'previous_canada_visa_answer',
        'canada_refusal_answer', 'other_refusal_answer', 'previously_in_canada_answer']),
    **_group(201, 'letters', ['introduction', 'occupation_in_brazil', 'reason_for_canada',
        'planned_activities', 'close_relatives_abroad', 'return_plans']),
    **_group(207, 'history', ['criminal_history_answer', 'service_history_answer',
        'immigration_problems_answer', 'overstay_answer', 'declaration_details']),
    233: 'declaration_acceptance',
}
for block, start in enumerate((82, 90, 98, 106)):
    COLUMN_TARGETS.update(_group(start, f'activities[{block}]', [
        'activity_type', 'start_date', 'end_date', 'position', 'organization', 'city', 'state']))
    if block < 3:
        COLUMN_TARGETS[start + 7] = f'activities[{block}].has_more_activities_answer'
for block, start in enumerate((113, 123)):
    COLUMN_TARGETS.update(_group(start, f'family.parents[{block}]', [
        'family_name', 'given_names', 'date_of_birth', 'birth_place', 'birth_country',
        'marital_status', 'occupation', 'address', 'death_details', 'accompanying_answer']))
for block, start in enumerate((134, 146, 158, 170, 182)):
    COLUMN_TARGETS.update(_group(start, f'family.children[{block}]', [
        'relationship', 'family_name', 'given_names', 'date_of_birth', 'marital_status',
        'birth_place', 'birth_country', 'occupation', 'address', 'postcode', 'accompanying_answer']))
    if block < 4:
        COLUMN_TARGETS[start + 11] = f'family.children[{block}].has_more_children_answer'
for column in range(212, 233):
    COLUMN_TARGETS[column] = f'documents[{column - 212}].references'


def _assign(case, path, value):
    obj = case
    parts = path.split('.')
    for part in parts[:-1]:
        if '[' in part:
            name, index = part.rstrip(']').split('[')
            obj = getattr(obj, name)[int(index)]
        else:
            obj = getattr(obj, part)
    setattr(obj, parts[-1], value)


def read_verified(row, header_sha256):
    from .source_readers import header_fingerprint
    if header_sha256 != HEADER_SHA256 or header_fingerprint(row.headers) != HEADER_SHA256:
        raise ValueError('Verified Canada column mapping cannot be used for a changed schema')
    if len(row.values) != 234:
        raise ValueError('Canada response width does not match the verified 234-column schema')
    case = CanadaCase(
        import_profile=PROFILE, source_headers=list(row.headers), source_header_sha256=header_sha256,
        raw_response=row.raw_dict(),
        activities=[Activity(source_block_index=i + 1, source_role='csv') for i in range(4)],
    )
    case.family.parents = [
        FamilyMember(source_block_index=i + 1, source_role=role, confirmed_role=role)
        for i, role in enumerate(('father', 'mother'))
    ]
    case.family.children = [FamilyMember(source_block_index=i + 1, source_role='child') for i in range(5)]
    case.documents = [DocumentReference(
        source_role='applicant' if i < 226 else 'sponsor', source_block_index=i,
        category=row.headers[i].strip()) for i in range(212, 233)]
    for column, path in COLUMN_TARGETS.items():
        # Preserve the entered date/amount/text. No name or money transformation.
        _assign(case, path, str(row.values[column] or '') if path == 'contact.address' else str(row.values[column] or '').strip())
    from .provenance import seed_source
    case.schema_version = 'canada_trv_google_form_v1'
    seed_source(case, COLUMN_TARGETS)
    case.source_email = case.contact.email
    return case


def restore_explicit_applicant(case):
    """Re-establish verified source facts unless a source-bound override wins.

    Old saved cases can contain stale derived/override values. Reuse the
    verified mapping contract here; PDF code never interprets source cells.
    """
    from .source_readers import header_fingerprint
    from .provenance import mark, source_digest
    if header_fingerprint(case.source_headers) != HEADER_SHA256:
        return
    occurrences = {}
    protected = {1,2,9,47,48,49,50}
    for index,header in enumerate(case.source_headers):
        occurrence = occurrences.get(header,0)
        occurrences[header] = occurrence+1
        if index not in protected:
            continue
        answers = case.raw_response.get(header,[])
        if occurrence >= len(answers):
            continue
        path = COLUMN_TARGETS[index]
        correction = case.overrides.get(path)
        if correction and correction.source_digest == source_digest(case):
            continue
        value = answers[occurrence] if index == 47 else answers[occurrence].strip()
        _assign(case,path,value)
        mark(case,path,value,'csv_explicit',f'csv:{case.schema_version}:column[{index}]:{header}',True)
