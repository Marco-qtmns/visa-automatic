"""Human-readable internal questions; no answer is defaulted to No."""
from .preparation import is_confirmed, ordered_activities, date_value, norm

QUESTIONS = {
 'staff_review.application_date': 'Application date (YYYY-MM-DD); overrides the submission date when needed',
 'staff_review.legal_guardian': 'For minors only: father, mother, both or other',
 'trip.funds_source_reference': 'Available-funds source: bank statement, financial document or other verified reference',
 'identity.sex': 'Sex, exactly as confirmed for the applicant',
 'identity.birth_country': 'Country of birth of the applicant',
 'trip.available_funds_cad': 'Funds available for this stay, in CAD (not estimated costs)',
 'staff_review.uci': 'Existing UCI, if known; otherwise leave blank',
 'staff_review.native_language': 'Native language / mother tongue',
 'staff_review.service_language': 'IRCC service language: English or French',
 'contact.country': 'Country of the residential address',
 'contact.mailing_same_as_residential': 'Is the mailing address the same as the residential address?',
 'official_review.previous_residence_over_six_months': 'In the past five years, lived in another country for more than six months (outside citizenship/current residence)?',
 'official_review.applying_from_residence_country': 'Applying from the same country as current residence?',
 'official_review.post_secondary_education': 'Ever had post-secondary education, including university, college or apprenticeship?',
 'official_review.tuberculosis_or_close_contact_last_two_years': 'In the past two years, you or a family member had lung tuberculosis, or close contact with someone with tuberculosis?',
 'official_review.disorder_requiring_social_or_health_services': 'Physical or mental disorder requiring social and/or health services during the stay, other than medication?',
 'official_review.medical_details': 'If either health answer is Yes: details and accompanying family member, if applicable',
 'official_review.canada_overstay_unauthorized_work_or_study': 'Ever stayed beyond status validity, attended school without authorization or worked without authorization in Canada?',
 'official_review.visa_refusal_denied_entry_or_removal_any_country': 'Ever refused a visa/permit, denied entry or ordered to leave Canada or any other country?',
 'official_review.previously_applied_to_enter_or_remain_canada': 'Previously applied to enter or remain in Canada?',
 'official_review.immigration_explanation': 'If overstay/unauthorized work or study, refusal/removal, or previous application is Yes: details attributable to that answer',
 'official_review.committed_arrested_charged_or_convicted_any_country': 'Ever committed, been arrested for, charged with or convicted of any criminal offence in any country?',
 'official_review.criminal_details': 'If Yes: criminal-history details',
 'official_review.military_militia_civil_defence_security_or_police': 'Served in any military, militia, civil defence, security organization or police force, including non-obligatory national service, reserve or volunteer units?',
 'official_review.service_details': 'If Yes: dates of service and countries/territories',
 'official_review.associated_with_violent_or_criminal_organization': 'Member of or associated with a political party or organization that used or advocated violence to achieve a political/religious objective, or was associated with criminal activity?',
 'official_review.witnessed_or_participated_in_ill_treatment_looting_desecration': 'Witnessed or participated in ill-treatment of prisoners/civilians, looting or desecration of religious buildings?',
 'representative.action': 'Action for this case: appointment, update, cancellation, replacement or withdrawal',
}


def review_findings(case):
    # Compatibility API; one validator owns issue identity and deduplication.
    from .validation import validate_case, issue_text
    return [issue_text(issue) for issue in validate_case(case).issues]
