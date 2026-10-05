from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz

from canada.models import CanadaCase, FamilyMember, Activity
from canada.preparation import prepare_case, parse_narrative, is_confirmed, ordered_activities, child_given_names
from canada.review import ReviewSession
from canada.case_store import save_case, load_case
from canada.pdf_drafts import generate_drafts
from canada.representative_store import save_profile, apply_default_profile
from canada.compact_review import review_findings
from tests.test_canada_pdf_drafts import data


class PreparationTests(unittest.TestCase):
    def test_child_name_contract_and_ambiguous_partial_surname(self):
        self.assertEqual(child_given_names('da Silva Costa','Ana Maria da Silva Costa'),'Ana Maria')
        self.assertEqual(child_given_names('da Silva Costa','da Silva Costa Ana Maria'),'Ana Maria')
        self.assertEqual(child_given_names('Ali','Ali Sami Ali'),'')
        self.assertEqual(child_given_names('da Silva Costa','Ana Maria'),'Ana Maria')
        self.assertEqual(child_given_names('da Silva Costa','Ana Silva'),'')
        self.assertEqual(child_given_names('Silva','Silva'),'')
        case=CanadaCase(import_profile='verified_20260929')
        case.family.children=[FamilyMember(family_name='EXAMPLE',full_name='Ana EXAMPLE')]
        case.family.parents=[FamilyMember(family_name='EXAMPLE',full_name='Parent EXAMPLE')]
        prepare_case(case)
        self.assertEqual(case.family.children[0].given_names,'Ana')
        self.assertEqual(case.family.parents[0].given_names,'Parent EXAMPLE')
        case.family.children[0].given_names='Confirmed different'
        prepare_case(case)
        self.assertEqual(case.family.children[0].given_names,'Confirmed different')

    def test_spouse_other_address_and_same_residence(self):
        for answer,expected in [('Quadra 12 Bloco B','Quadra 12 Bloco B'),('Outro: Rua A 10','Rua A 10'),('Sim','Applicant address'),('Não','')]:
            case=CanadaCase(import_profile='verified_20260929')
            case.contact.address='Applicant address'
            case.relationships.spouse_residence_answer=answer
            prepare_case(case)
            self.assertEqual(case.relationships.spouse_address,expected)
            self.assertEqual(case.relationships.spouse_residence_answer,answer)

    def test_narratives_preserve_source_and_need_confirmation(self):
        text='Portugal | Student | 01/02/2020 | 03/04/2021\nUnclear account with no dates'
        records=parse_narrative(text,'residence')
        self.assertEqual(len(records),2)
        self.assertEqual(records[0].country,'Portugal')
        self.assertEqual(records[0].start_date,'2020-02-01')
        self.assertEqual(records[1].source_text,'Unclear account with no dates')
        self.assertFalse(is_confirmed(records[0]))
        natural=parse_narrative('Morei em Portugal como estudante de 01/02/2020 a 03/04/2021','residence')[0]
        self.assertEqual(natural.country,'Portugal')
        self.assertEqual(natural.status_or_purpose,'estudante')

    def test_confirmation_invalidated_by_edit_and_round_trips(self):
        case=CanadaCase()
        case.history.previous_residences='Portugal | Student | 2020-01-01 | 2021-01-01'
        prepare_case(case)
        review=ReviewSession(case)
        review.confirm_record('residence',0)
        self.assertFalse(is_confirmed(case.residence_records[0]))
        review.apply()
        self.assertTrue(is_confirmed(case.residence_records[0]))
        self.assertTrue(any(c.path=='residence_records' for c in case.review_changes))
        review=ReviewSession(case)
        review.set_value('residence_records[0].country','Canada')
        review.apply()
        self.assertFalse(is_confirmed(case.residence_records[0]))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'case.canada-case.json'
            save_case(case,path)
            self.assertEqual(case,load_case(path))

    def test_invalid_history_cannot_be_confirmed_or_silently_recreated(self):
        case=CanadaCase()
        case.history.travel_details='Dates unknown'
        prepare_case(case)
        session=ReviewSession(case)
        with self.assertRaises(ValueError): session.confirm_record('travel',0)
        session.remove_record('travel',0)
        session.apply()
        prepare_case(case)
        self.assertEqual(case.travel_records,[])
        self.assertEqual(case.history.travel_details,'Dates unknown')

    def test_current_job_and_history_order_no_duplicates_or_guessed_country(self):
        case=CanadaCase(import_profile='verified_20260929')
        case.raw_response={'Carimbo de data/hora':['29/09/2026 15:00:00']}
        case.employment.profession='Engineer'
        case.employment.start_date='2024-01'
        case.activities=[Activity(position='Earlier',start_date='2010-01',end_date='2020-01'),
                         Activity(position='Unknown end',start_date='2020-01',end_date='29/09/2026')]
        prepare_case(case)
        once=deepcopy(case)
        prepare_case(case)
        self.assertEqual(case,once)
        self.assertEqual(len(case.activities),3)
        self.assertEqual(case.activities[2].ongoing_answer,'Yes')
        self.assertEqual(case.activities[0].ongoing_answer,'No')
        self.assertEqual(case.activities[1].ongoing_answer,'')
        self.assertEqual(case.activities[2].country,'')
        self.assertEqual([a.position for _,a in ordered_activities(case)],['Engineer','Unknown end','Earlier'])

    def test_defaults_remembered_without_mixing_representatives_or_actions(self):
        source=CanadaCase()
        source.representative.family_name='EXAMPLE'
        source.representative.category='Unpaid - friend or family'
        source.representative.action='Cancel a representative'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'default.canada-representative.json'
            save_profile(source.representative,path)
            with patch('canada.representative_store.default_profile_path',return_value=path):
                target=CanadaCase()
                apply_default_profile(target)
                self.assertEqual(target.representative.family_name,'EXAMPLE')
                self.assertEqual(target.representative.action,'')
                target.representative.family_name='OTHER'
                target.representative.category=''
                apply_default_profile(target)
                self.assertEqual(target.representative.category,'')

    def test_export_current_job_child_spouse_and_confirmed_history_only(self):
        case=CanadaCase(import_profile='verified_20260929')
        case.identity.family_name='EXAMPLE'
        case.identity.given_names='Alex'
        case.identity.marital_status='Solteiro'
        case.identity.nationality='Brasileiro'
        case.family.children=[FamilyMember(family_name='EXAMPLE',full_name='Ana EXAMPLE')]
        case.relationships.spouse_residence_answer='Quadra 9 Bloco B'
        case.employment.profession='Engineer'
        case.employment.start_date='2024-01'
        case.history.previous_residences='Portugal | Student | 2020-01-01 | 2021-01-01'
        case.official_review.previous_residence_over_six_months='Yes'
        prepare_case(case)
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'unconfirmed'
            generate_drafts(case,output)
            visa=data(output/'IMM5257-DRAFT.pdf')
            self.assertEqual(visa.find('.//OccupationRow1/Occupation/Occupation').text,'Engineer')
            self.assertEqual(visa.find('.//OccupationRow1/FromYear').text,'2024')
            self.assertIsNone(visa.find('.//PreviousCOR/Row2/Country').text)
            family=data(output/'IMM5707-DRAFT.pdf')
            self.assertEqual(family.find('.//Child/PaddedEntry/PersonalData[1]/GivenNames').text,'Ana')
            self.assertEqual(family.find('.//Spouse/PaddedEntry/PersonalData[2]/Address').text,'Quadra 9 Bloco B')
            session=ReviewSession(case)
            session.confirm_record('residence',0)
            session.apply()
            output=Path(folder)/'confirmed'
            report=generate_drafts(case,output)
            visa=data(output/'IMM5257-DRAFT.pdf')
            self.assertTrue(visa.find('.//PreviousCOR/Row2/Country').text)
            self.assertEqual(visa.find('.//PreviousCOR/Row2/FromDate').text,'2020-01-01')
            self.assertEqual(report['continuation']['residence_count'],1)

    def test_continuation_paginated_no_activity_dropped(self):
        case=CanadaCase()
        case.identity.family_name='EXAMPLE'
        case.identity.given_names='Synthetic'
        case.activities=[Activity(position=f'UNIQUE ROLE {i}',organization='Long company description '*45,
             city='Brasília',state='DF',country='Brazil',start_date=f'{2025-i}-01',end_date=f'{2025-i}-12',ongoing_answer='No') for i in range(12)]
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'drafts'
            report=generate_drafts(case,output)
            self.assertEqual(report['continuation']['activity_count'],9)
            with fitz.open(output/'IMM5257-CONTINUATION-DRAFT.pdf') as doc:
                self.assertGreater(len(doc),1)
                text=''.join(page.get_text() for page in doc)
                for i in range(3,12): self.assertIn(f'UNIQUE ROLE {i}',text)
                self.assertIn('Brasília',text)
            visa=data(output/'IMM5257-DRAFT.pdf')
            self.assertEqual(visa.find('.//OccupationRow1/Occupation/Occupation').text,'UNIQUE ROLE 0')

    def test_timeline_gaps_are_reported(self):
        case=CanadaCase(activities=[Activity(start_date='2010-01',end_date='2015-01',ongoing_answer='No'),
                                  Activity(start_date='2020-01',ongoing_answer='Yes')])
        case.staff_review.application_date='2026-09-29'
        self.assertTrue(any('gap' in f for f in review_findings(case)))

    def test_official_city_characters_normalized_without_changing_case(self):
        case=CanadaCase(activities=[Activity(position='Engineer',city='Brasília',start_date='2020-01',ongoing_answer='Yes')])
        before=deepcopy(case)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'drafts'
            report=generate_drafts(case,out)
            visa=data(out/'IMM5257-DRAFT.pdf')
            self.assertEqual(visa.find('.//OccupationRow1/CityTown/CityTown').text,'Brasilia')
            self.assertEqual(case,before)
            row=next(w for w in report['forms']['IMM5257']['writes'] if w['source']=='activities[0].city')
            self.assertIn('normalization',row['transformation'])


if __name__=='__main__': unittest.main()
