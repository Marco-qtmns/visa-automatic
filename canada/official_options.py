"""Explicit staff choices, verified against the hash-pinned XFA templates."""

REPRESENTATIVE_ACTIONS = {
    'Appoint a representative': '1',
    'Update representative contact information': '2',
    'Cancel a representative': '3',
    'Cancel and appoint a new representative': '4',
    'Withdraw as representative': '5',
}

# Dataset group, selection code, membership path relative to question6.
# Unpaid radio order differs from visual order: other=3, law society=4.
REPRESENTATIVE_CATEGORIES = {
    'Unpaid - friend or family': ('questionI', '1', ''),
    'Unpaid - CICC member': ('questionI', '2', 'questionI/membership[1]'),
    'Unpaid - other': ('questionI', '3', ''),
    'Unpaid - law society or student-at-law': ('questionI', '4', 'questionI/membership2'),
    'Unpaid - Quebec notary': ('questionI', '5', 'questionI/membership[2]'),
    'Paid - CICC member': ('questionII', '1', 'questionII/ICCRCMember'),
    'Paid - law society or student-at-law': ('questionII', '2', 'questionII/membership'),
    'Paid - Quebec notary': ('questionII', '3', 'questionII/quebecLaw'),
}

YES_NO_FIELDS = (
    'previous_residence_over_six_months', 'applying_from_residence_country',
    'post_secondary_education', 'tuberculosis_or_close_contact_last_two_years',
    'disorder_requiring_social_or_health_services',
    'canada_overstay_unauthorized_work_or_study',
    'visa_refusal_denied_entry_or_removal_any_country',
    'previously_applied_to_enter_or_remain_canada',
    'committed_arrested_charged_or_convicted_any_country',
    'military_militia_civil_defence_security_or_police',
    'associated_with_violent_or_criminal_organization',
    'witnessed_or_participated_in_ill_treatment_looting_desecration',
)

CHOICES = {
    'staff_review.legal_guardian': ('','father','mother','both','other'),
    'representative.action': ('', *REPRESENTATIVE_ACTIONS),
    'representative.category': ('', *REPRESENTATIVE_CATEGORIES),
    **{'official_review.'+field: ('', 'Yes', 'No') for field in YES_NO_FIELDS},
}


def choices_for(path):
    if path.endswith('.confirmed_role'):
        return ('', 'mother', 'father')
    if path.endswith('.ongoing_answer'):
        return ('', 'Yes', 'No', 'Sim', 'Não')
    return CHOICES.get(path)
