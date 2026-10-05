"""MVP rules exercised only with invented cases and exact header fixtures."""
import csv
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from canada.models import CanadaCase, Activity, FamilyMember
from canada.preparation import prepare_case, parse_narrative, is_confirmed
from canada.validation import validate_case, deduplicate, ensure_generation_allowed
from canada.review import ReviewSession
from canada.provenance import apply_overrides
from canada.case_store import save_case, load_case
from canada.source_readers import read_google_forms_csv


def case():
    c=CanadaCase(import_profile='verified_20260929')
    c.raw_response={'Carimbo de data/hora':['29/09/2026 10:00:00']}
    c.identity.date_of_birth='2000-01-01'
    c.identity.state_of_birth='SP'
    c.identity.residence_country='Brazil'
    c.contact.address='  Quadra 1, Bloco B\nApartamento 2  '
    return c


def codes(c):
    return [i.code for i in validate_case(c).issues]


class PipelineTests(unittest.TestCase):
    def test_schema_fail_closed_and_original_unchanged(self):
        source=Path(__file__).parent/'fixtures/canada_20260929_synthetic.csv'
        before=source.read_bytes()
        self.assertEqual(read_google_forms_csv(source)[0].schema_version,'canada_trv_google_form_v1')
        rows=list(csv.reader(before.decode().splitlines()))
        rows[0][48]='Changed city header'
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'changed.csv'
            with p.open('w',newline='') as f: csv.writer(f).writerows(rows)
            with self.assertRaisesRegex(ValueError,'CSV_SCHEMA_MISMATCH'): read_google_forms_csv(p)
        self.assertEqual(source.read_bytes(),before)

    def test_parents_separate_names_and_roles(self):
        source=Path(__file__).parent/'fixtures/canada_20260929_synthetic.csv'
        c=read_google_forms_csv(source)[0]
        prepare_case(c)
        self.assertEqual([p.confirmed_role for p in c.family.parents],['father','mother'])
        self.assertTrue(all(p.given_names for p in c.family.parents))
        self.assertNotIn('PARENT_ROLE_MISSING',codes(c))
        self.assertFalse(any(i.code=='FAMILY_NAME_INCOMPLETE' and i.entity_type=='parent' for i in validate_case(c).issues))
        self.assertEqual(c.provenance['family.parents[0].confirmed_role'].source_type,'derived_rule')

    def test_adult_minor_and_birthday_boundary(self):
        c=case(); c.family.parents=[FamilyMember(source_block_index=1)]
        prepare_case(c)
        self.assertEqual(c.family.parents[0].guardian_status,'not_required')
        self.assertNotIn('LEGAL_GUARDIAN_REQUIRED',codes(c))
        c.identity.date_of_birth='2008-09-30'
        self.assertIn('LEGAL_GUARDIAN_REQUIRED',codes(c))
        c.identity.date_of_birth='2008-09-29'
        self.assertNotIn('LEGAL_GUARDIAN_REQUIRED',codes(c))
        c.identity.date_of_birth='2010-01-01'; c.staff_review.legal_guardian='both'
        self.assertNotIn('LEGAL_GUARDIAN_REQUIRED',codes(c))

    def test_birth_suggestion_and_sex_are_not_inferred(self):
        c=case(); result=validate_case(c)
        self.assertIn('APPLICANT_SEX_MISSING',[i.code for i in result.issues])
        issue=next(i for i in result.issues if i.code=='BIRTH_COUNTRY_MISSING')
        self.assertEqual(issue.suggested_value,'Brazil')
        self.assertEqual(c.identity.birth_country,'')
        self.assertEqual(c.identity.sex,'')

    def test_address_confirmation_and_persisted_override(self):
        c=case(); original=c.contact.address
        session=ReviewSession(c)
        issue=next(i for i in session.issues() if i.code=='ADDRESS_COUNTRY_CONFIRMATION')
        session.resolve_issue(issue,confirm=True); session.apply()
        self.assertEqual(c.contact.address,original)
        self.assertEqual(c.contact.country,'Brazil')
        self.assertEqual(c.provenance['contact.country'].source_type,'staff_confirmed')
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.canada-case.json'; save_case(c,p); c=load_case(p)
        self.assertNotIn('ADDRESS_COUNTRY_CONFIRMATION',codes(c))
        rebuilt=case(); rebuilt.overrides=deepcopy(c.overrides); apply_overrides(rebuilt)
        self.assertEqual(rebuilt.contact.country,'Brazil')
        rebuilt.raw_response['changed']=['new address']
        self.assertIn('ADDRESS_COUNTRY_CONFIRMATION',codes(rebuilt))

    def test_activity_status_rules_and_batch(self):
        c=case()
        c.activities=[Activity(start_date='2020-01-01',end_date='2021-01-01',position='Old'),
            Activity(start_date='2022-01-01',end_date='2026-09-29',position='Placeholder'),
            Activity(start_date='2024-01-01',source_role='current_employment',position='Current')]
        prepare_case(c)
        self.assertEqual([a.status for a in c.activities],['completed','needs_confirmation','ongoing'])
        issues=validate_case(c).issues
        self.assertEqual(sum(i.code=='ACTIVITY_STATUS_CONFIRMATION' for i in issues),1)
        self.assertEqual(sum(i.code=='ACTIVITY_COUNTRIES_MISSING_BATCH' for i in issues),1)
        self.assertNotIn('ACTIVITY_COUNTRY_MISSING',codes(c))
        session=ReviewSession(c); issue=next(i for i in session.issues() if i.code=='ACTIVITY_COUNTRIES_MISSING_BATCH')
        session.resolve_issue(issue,confirm=True); session.apply()
        self.assertEqual([a.country for a in c.activities],['Brazil']*3)
        self.assertNotIn('ACTIVITY_COUNTRIES_MISSING_BATCH',codes(c))
        self.assertTrue(all(c.provenance[f'activities[{i}].country'].source_type=='staff_confirmed' for i in range(3)))

    def test_individual_countries_and_cancel(self):
        c=case(); c.activities=[Activity(position='A'),Activity(position='B')]
        s=ReviewSession(c); i=next(i for i in s.issues() if i.code=='ACTIVITY_COUNTRIES_MISSING_BATCH')
        s.resolve_issue(i,{'activities[0].country':'Brazil','activities[1].country':'Argentina'})
        self.assertEqual(c.activities[0].country,'')
        s.apply(); self.assertEqual(c.activities[1].country,'Argentina')

    def test_invalid_and_future_activities(self):
        c=case(); c.activities=[Activity(start_date='2022-01-01',end_date='2021-01-01')]
        self.assertIn('ACTIVITY_DATE_RANGE_INVALID',codes(c))
        with self.assertRaisesRegex(ValueError,'ACTIVITY_DATE_RANGE_INVALID'): ensure_generation_allowed(c)
        c.activities[0].end_date='2027-01-01'
        self.assertIn('ACTIVITY_DATE_FUTURE',codes(c))
        c.activities[0].end_date=''
        self.assertIn('ACTIVITY_STATUS_CONFIRMATION',codes(c))

    def test_residence_no_skips_na_and_yes_parses(self):
        c=case(); c.identity.previous_residence_5y='Não'; c.history.previous_residences='N/A'
        prepare_case(c); self.assertEqual(c.residence_records,[])
        c=case(); c.identity.previous_residence_5y='Sim'
        c.history.previous_residences='Portugal | Student | 2020-01-01 | 2021-01-01'
        prepare_case(c); self.assertEqual(len(c.residence_records),1)

    def test_complete_travel_and_one_incomplete_issue(self):
        c=case(); c.history.travel_details='Argentina - 2024-03-10 - 2024-03-20 - turismo'
        prepare_case(c)
        self.assertTrue(is_confirmed(c.travel_records[0]))
        self.assertFalse(any(i.entity_type=='travel' for i in validate_case(c).issues))
        self.assertEqual(c.provenance['travel_records[0].country'].source_type,'parsed_explicit')
        c.travel_records[0].end_date='2024-03-21'
        self.assertIn('HISTORY_CONFIRMATION',codes(c))
        c=case(); c.history.travel_details='Argentina, dates unknown'
        self.assertEqual(codes(c).count('TRAVEL_RECORD_INCOMPLETE'),1)

    def test_travel_reversed_dates_error(self):
        c=case(); c.history.travel_details='Argentina - 2024-03-20 - 2024-03-10 - turismo'
        self.assertIn('TRAVEL_DATE_RANGE_INVALID',codes(c))

    def test_education_and_funds_separate(self):
        c=case(); c.education.level='Pós-graduação'; c.trip.estimated_spend='12500'
        self.assertEqual(codes(c).count('EDUCATION_LOCATION_INCOMPLETE'),1)
        self.assertIn('AVAILABLE_FUNDS_CAD_MISSING',codes(c))
        self.assertEqual(c.trip.available_funds_cad,'')
        s=ReviewSession(c); s.set_value('trip.available_funds_cad','10000'); s.set_value('trip.funds_source_reference','Synthetic bank statement'); s.apply()
        self.assertNotIn('AVAILABLE_FUNDS_CAD_MISSING',codes(c))
        self.assertEqual(c.trip.estimated_spend,'12500')

    def test_dedup_pure_validation_and_final_gate(self):
        c=case(); before=deepcopy(c); issues=validate_case(c).issues
        self.assertEqual(c,before)
        self.assertEqual(deduplicate(issues+issues),issues)
        ensure_generation_allowed(c)  # Incomplete draft, not a final document.
        with self.assertRaisesRegex(ValueError,'APPLICANT_SEX_MISSING'): ensure_generation_allowed(c,final=True)

    def test_raw_address_exact_from_csv(self):
        source=Path(__file__).parent/'fixtures/canada_20260929_synthetic.csv'
        with source.open() as f: rows=list(csv.reader(f))
        raw='  Quadra 1, Bloco B\nApartment 2  '
        rows[1][47]=raw
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'sample.csv'
            with p.open('w',newline='') as f: csv.writer(f).writerows(rows)
            c=read_google_forms_csv(p)[0]
            self.assertEqual(c.contact.address,raw)
            prepare_case(c); self.assertEqual(c.contact.address,raw)

    def test_google_timestamp_and_derived_status_reopens(self):
        c=case(); c.raw_response={'Carimbo de data/hora':['2026/09/29 6:42:55 AM GMT-3']}
        c.activities=[Activity(start_date='2020-01-01',end_date='2024-01-01')]
        prepare_case(c)
        self.assertEqual(c.activities[0].status,'completed')
        self.assertNotIn('APPLICATION_DATE_MISSING',codes(c))
        s=ReviewSession(c); s.set_value('activities[0].end_date','2026-09-29'); s.apply()
        self.assertIn('ACTIVITY_STATUS_CONFIRMATION',codes(c))

    def test_staff_status_confirmation_survives_preparation(self):
        c=case(); c.activities=[Activity(start_date='2020-01-01',end_date='2026-09-29')]
        prepare_case(c); s=ReviewSession(c)
        i=next(i for i in s.issues() if i.code=='ACTIVITY_STATUS_CONFIRMATION')
        s.resolve_issue(i,{'activities[0].ongoing_answer':'No'}); s.apply()
        prepare_case(c)
        self.assertNotIn('ACTIVITY_STATUS_CONFIRMATION',codes(c))

    def test_confirmed_record_removal_does_not_reassign_overrides(self):
        c=case(); c.history.previous_residences='Portugal | Student | 2020-01-01 | 2021-01-01\nCanada | Worker | 2022-01-01 | 2023-01-01'
        prepare_case(c); s=ReviewSession(c); s.confirm_record('residence',0); s.apply()
        s=ReviewSession(c); s.remove_record('residence',0); s.apply(); prepare_case(c)
        self.assertEqual(len(c.residence_records),1)
        self.assertEqual(c.residence_records[0].country,'Canada')

    def test_changed_narrative_does_not_keep_old_approval(self):
        c=case(); c.history.travel_details='Argentina - 2024-03-10 - 2024-03-20 - turismo'
        prepare_case(c); self.assertTrue(is_confirmed(c.travel_records[0]))
        c.history.travel_details='Missing dates for new trip'
        prepare_case(c)
        self.assertFalse(is_confirmed(c.travel_records[0]))
        self.assertEqual(codes(c).count('TRAVEL_RECORD_INCOMPLETE'),1)

    def test_underlying_source_change_marks_overrides_stale(self):
        c=case(); s=ReviewSession(c); s.set_value('identity.sex','Female'); s.apply()
        c.raw_response['new source answer']=['changed']
        self.assertIn('STAFF_OVERRIDE_STALE',codes(c))
        s=ReviewSession(c); i=next(i for i in s.issues() if i.code=='STAFF_OVERRIDE_STALE')
        s.resolve_issue(i,confirm=True); s.apply()
        self.assertNotIn('STAFF_OVERRIDE_STALE',codes(c))

    def test_errors_block_actual_pdf_entrypoint(self):
        from canada.pdf_drafts import generate_drafts
        c=case(); c.history.travel_details='Argentina - 2024-03-20 - 2024-03-10 - turismo'
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'must-not-exist'
            with self.assertRaisesRegex(ValueError,'TRAVEL_DATE_RANGE_INVALID'): generate_drafts(c,p)
            self.assertFalse(p.exists())

    def test_month_precision_does_not_invent_an_impossible_date_range(self):
        c=case(); c.activities=[Activity(start_date='2026-09-15',end_date='2026-09')]
        prepare_case(c)
        self.assertEqual(c.activities[0].status,'needs_confirmation')
        self.assertNotIn('ACTIVITY_DATE_RANGE_INVALID',codes(c))

    def test_editing_address_reopens_country_confirmation(self):
        c=case(); s=ReviewSession(c)
        s.resolve_issue(next(i for i in s.issues() if i.code=='ADDRESS_COUNTRY_CONFIRMATION'),confirm=True)
        s.apply()
        s=ReviewSession(c); s.set_value('contact.address','A different address'); s.apply()
        self.assertIn('ADDRESS_COUNTRY_CONFIRMATION',codes(c))


if __name__=='__main__': unittest.main()
