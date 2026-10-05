from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from canada.models import CanadaCase, Activity
from canada.preparation import prepare_case
from canada.provenance import override
from canada.review import ReviewSession
from canada.review_tasks import review_tasks, task_fields, automated_answers
from canada.validation import validate_case, ensure_generation_allowed
from canada.case_store import save_case, load_case


def example():
    c=CanadaCase(import_profile='verified_20260929')
    c.raw_response={'Carimbo de data/hora':['2026/09/29 10:00:00']}
    c.identity.date_of_birth='1990-01-01'
    return c


class ReviewTasksTests(unittest.TestCase):
    def test_explicit_positive_answers_are_derived_with_provenance(self):
        c=example(); c.history.canada_refusal_answer='Sim'
        c.history.previous_canada_visa_answer='Sim';c.history.criminal_history_answer='Sim'
        raw=deepcopy(c.raw_response); prepare_case(c)
        self.assertEqual(c.official_review.visa_refusal_denied_entry_or_removal_any_country,'Yes')
        self.assertEqual(c.official_review.previously_applied_to_enter_or_remain_canada,'Yes')
        self.assertEqual(c.official_review.committed_arrested_charged_or_convicted_any_country,'Yes')
        self.assertEqual(len(automated_answers(c)),3)
        self.assertTrue(all(a['acceptance']=='can_be_automated' for a in automated_answers(c)))
        self.assertEqual(c.raw_response,raw)
        snapshot=deepcopy(c);prepare_case(c);self.assertEqual(c,snapshot)

    def test_narrow_negative_answers_never_become_broad_no(self):
        c=example();c.history.canada_refusal_answer='Não';c.history.other_refusal_answer='Não'
        c.history.previous_canada_visa_answer='Não';c.history.overstay_answer='Não'
        c.history.service_history_answer='Não';prepare_case(c)
        self.assertEqual(c.official_review.visa_refusal_denied_entry_or_removal_any_country,'')
        self.assertEqual(c.official_review.previously_applied_to_enter_or_remain_canada,'')
        self.assertEqual(c.official_review.canada_overstay_unauthorized_work_or_study,'')
        self.assertEqual(c.official_review.military_militia_civil_defence_security_or_police,'')

    def test_equivalent_criminal_question_allows_explicit_no(self):
        c=example();c.history.criminal_history_answer='Não';prepare_case(c)
        self.assertEqual(c.official_review.committed_arrested_charged_or_convicted_any_country,'No')
        self.assertFalse(any(i.field=='official_review.criminal_details' for i in validate_case(c).issues))

    def test_rules_are_scoped_to_verified_profile(self):
        c=example();c.import_profile='legacy';c.history.criminal_history_answer='Sim'
        prepare_case(c);self.assertEqual(c.official_review.committed_arrested_charged_or_convicted_any_country,'')

    def test_unknown_answers_are_not_interpreted(self):
        c=example();c.history.criminal_history_answer='Possibly';c.history.canada_refusal_answer='N/A'
        prepare_case(c);self.assertEqual(automated_answers(c),[])

    def test_post_secondary_positive_only_and_unknown_level(self):
        for level in ('Ensino superior incompleto','Pós-graduação','Mestrado','Doutorado'):
            c=example();c.education.level=level;prepare_case(c)
            self.assertEqual(c.official_review.post_secondary_education,'Yes')
        for level in ('Ensino médio','Unknown institution type',''):
            c=example();c.education.level=level;prepare_case(c)
            self.assertEqual(c.official_review.post_secondary_education,'')

    def test_broad_residence_no_covers_narrow_question_but_yes_does_not(self):
        c=example();c.identity.previous_residence_5y='Não';prepare_case(c)
        self.assertEqual(c.official_review.previous_residence_over_six_months,'No')
        c.identity.previous_residence_5y='Sim';prepare_case(c)
        self.assertEqual(c.official_review.previous_residence_over_six_months,'')

    def test_missing_details_remain_a_final_generation_gate(self):
        c=example();c.history.criminal_history_answer='Sim'
        with self.assertRaisesRegex(ValueError,'OFFICIAL_DETAILS_MISSING'):
            ensure_generation_allowed(c,final=True)

    def test_residence_errors_keep_their_correct_identity(self):
        c=example();c.identity.previous_residence_5y='Sim'
        c.history.previous_residences='Portugal | Student | 2024-01-01 | 2023-01-01'
        self.assertTrue(any(i.code=='RESIDENCE_DATE_RANGE_INVALID' and i.status=='ERROR' for i in validate_case(c).issues))

    def test_source_bound_staff_blank_is_not_automatically_replaced(self):
        c=example();c.history.criminal_history_answer='Sim';prepare_case(c)
        override(c,'official_review.committed_arrested_charged_or_convicted_any_country','')
        prepare_case(c)
        self.assertEqual(c.official_review.committed_arrested_charged_or_convicted_any_country,'')

    def test_source_changes_invalidate_derived_yes(self):
        c=example();c.history.previous_canada_visa_answer='Sim';prepare_case(c)
        c.history.previous_canada_visa_answer='Não';prepare_case(c)
        self.assertEqual(c.official_review.previously_applied_to_enter_or_remain_canada,'')
        self.assertEqual(automated_answers(c),[])

    def test_staff_override_preserved_but_contradiction_stays_visible(self):
        c=example();c.history.canada_refusal_answer='Sim';prepare_case(c)
        override(c,'official_review.visa_refusal_denied_entry_or_removal_any_country','No')
        prepare_case(c)
        self.assertEqual(c.official_review.visa_refusal_denied_entry_or_removal_any_country,'No')
        self.assertTrue(any(i.code=='OFFICIAL_SOURCE_CONFLICT' for i in validate_case(c).issues))

    def test_positive_answers_require_attributable_details(self):
        c=example();c.history.criminal_history_answer='Sim';c.history.other_refusal_answer='Sim'
        issues=validate_case(c).issues
        fields={i.field for i in issues if i.code=='OFFICIAL_DETAILS_MISSING'}
        self.assertEqual(fields,{'official_review.criminal_details','official_review.immigration_explanation'})
        self.assertNotIn('official_review.committed_arrested_charged_or_convicted_any_country',
                         {i.field for i in issues if i.code=='OFFICIAL_ANSWER_MISSING'})

    def test_residence_is_not_labelled_as_travel(self):
        c=example();c.history.previous_residences='Missing residence dates'
        c.history.travel_details='Missing travel dates'
        codes=[i.code for i in validate_case(c).issues]
        self.assertIn('RESIDENCE_RECORD_INCOMPLETE',codes)
        self.assertIn('TRAVEL_RECORD_INCOMPLETE',codes)

    def test_grouping_preserves_every_issue_and_error(self):
        c=example();c.activities=[Activity(position='A',start_date='2020-01',end_date='2019-01'),
                                  Activity(position='B',start_date='2021-01')]
        tasks=review_tasks(c)
        self.assertEqual({i.identity for t in tasks for i in t.issues},
                         {i.identity for i in validate_case(c).issues})
        activity=next(t for t in tasks if t.id=='activities')
        self.assertEqual(activity.acceptance,'badly_presented');self.assertEqual(activity.status,'ERROR')
        with self.assertRaises(ValueError):ensure_generation_allowed(c)

    def test_official_questions_group_into_human_topics(self):
        tasks=review_tasks(example())
        self.assertTrue({'health','immigration','security','education'} <= {t.id for t in tasks})
        self.assertLess(len(tasks),len(validate_case(example()).issues))

    def test_conditional_details_are_available_in_the_same_task(self):
        c=example();s=ReviewSession(c);task=next(t for t in s.tasks() if t.id=='health')
        self.assertIn('official_review.medical_details',task_fields(task,c))
        s.resolve_task(task,{
            'official_review.tuberculosis_or_close_contact_last_two_years':'Yes',
            'official_review.disorder_requiring_social_or_health_services':'No',
            'official_review.medical_details':'Synthetic explanation for this test',
        });s.apply()
        self.assertFalse(any(t.id=='health' for t in s.tasks()))

    def test_finances_collect_amount_and_evidence_together(self):
        c=example();s=ReviewSession(c)
        task=next(t for t in s.tasks() if t.id=='finances')
        self.assertEqual(task_fields(task,c),['trip.available_funds_cad','trip.funds_source_reference'])
        s.resolve_task(task,{'trip.available_funds_cad':'15000','trip.funds_source_reference':'Synthetic bank statement'})
        self.assertEqual(c.trip.available_funds_cad,'')
        s.apply()
        self.assertFalse(any(t.id=='finances' for t in s.tasks()))
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'case.canada-case.json';save_case(c,p)
            self.assertFalse(any(t.id=='finances' for t in review_tasks(load_case(p))))

    def test_task_resolution_is_atomic_and_field_scoped(self):
        s=ReviewSession(example());task=next(t for t in s.tasks() if t.id=='health')
        before=deepcopy(s.values)
        with self.assertRaises(ValueError):
            s.resolve_task(task,{'official_review.tuberculosis_or_close_contact_last_two_years':'Yes',
                                'official_review.disorder_requiring_social_or_health_services':'Guess'})
        self.assertEqual(s.values,before)
        with self.assertRaises(ValueError):s.resolve_task(task,{'identity.family_name':'Not a health field'})

    def test_stale_task_cannot_apply_unseen_changes(self):
        s=ReviewSession(example());task=next(t for t in s.tasks() if t.id=='finances')
        s.set_value('trip.available_funds_cad','5000')
        with self.assertRaisesRegex(ValueError,'changed'):s.resolve_task(task,{'trip.funds_source_reference':'Synthetic evidence'})

    def test_grouped_country_confirmation_keeps_explicit_other_country(self):
        c=example();c.activities=[Activity(position='A',start_date='2020-01',end_date='2021-01'),
            Activity(position='B',start_date='2021-02',end_date='2022-01',country='Argentina'),
            Activity(position='C',start_date='2022-02',ongoing_answer='Yes')]
        prepare_case(c);s=ReviewSession(c);task=next(t for t in s.tasks() if t.id=='activities')
        fields={'activities[0].country':'Brazil','activities[2].country':'Brazil'}
        s.resolve_task(task,fields,confirmed_paths=set(fields));s.apply()
        self.assertEqual(c.activities[1].country,'Argentina')
        for path in fields:self.assertEqual(c.provenance[path].source_type,'staff_confirmed')

    def test_export_report_includes_tasks_and_automatic_provenance(self):
        from canada.pdf_drafts import generate_drafts
        c=example();c.history.criminal_history_answer='Não'
        with tempfile.TemporaryDirectory() as folder:
            report=generate_drafts(c,Path(folder)/'draft')
            self.assertTrue(report['review_tasks'])
            self.assertEqual(report['automated_answers'][0]['value'],'No')
            self.assertEqual(report['automated_answers'][0]['acceptance'],'can_be_automated')


if __name__=='__main__':unittest.main()
