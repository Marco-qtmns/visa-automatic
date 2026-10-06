import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

import pymupdf as fitz

from canada.case_store import load_case, save_case
from canada.models import CanadaCase, FamilyMember, Activity
from canada.pdf_drafts import DATA, FORMS, ROOT, generate_drafts, packets
from canada.review import ReviewSession
from canada.official_options import REPRESENTATIVE_CATEGORIES


def synthetic_case():
    case = CanadaCase()
    case.identity.family_name = 'EXAMPLE'
    case.identity.given_names = 'Alex'
    case.identity.date_of_birth = '1990-02-03'
    case.identity.birth_country = 'Brazil'
    case.identity.sex = 'Male'
    case.identity.nationality = 'Brazil'
    case.identity.city_of_birth = 'Brasilia'
    case.passport.number = 'SYNTHETIC000'
    case.passport.issuing_country = 'Brazil'
    case.passport.issue_date = '2024-01-05'
    case.passport.expiry_date = '2034-01-04'
    case.contact.email = 'applicant@example.test'
    case.contact.address = 'SYNTHETIC QUADRA 10 BLOCO B'
    case.trip.host_name = 'Synthetic Host'
    case.trip.host_email = 'host@example.test'
    case.trip.host_address = '1 Synthetic Road, Ottawa'
    case.trip.available_funds_cad = '5000.00'
    case.trip.estimated_spend = '999999'
    case.trip.purpose = 'Tourism'
    case.trip.arrival_date = '2027-06-01'
    case.trip.departure_date = '2027-06-15'
    case.staff_review.service_language = 'English'
    case.family.parents = [FamilyMember(family_name='PARENTONE',given_names='Jamie',date_of_birth='1960-01-01',birth_country='Brazil'),
                           FamilyMember(family_name='PARENTTWO',given_names='Robin',date_of_birth='1961-02-02',birth_country='Brazil')]
    case.family.children = [FamilyMember(family_name='EXAMPLE',given_names=f'Child {i+1}',date_of_birth='2015-03-04',birth_country='Brazil',accompanying_answer='No',relationship='Child') for i in range(6)]
    case.activities = [Activity(position=f'Synthetic role {i+1}',organization='Example Company',city='Brasilia',state='DF',start_date='2020-01-01',end_date='2021-01-01',ongoing_answer='No') for i in range(5)]
    case.representative.family_name = 'REPRESENTATIVE'
    case.representative.given_names = 'Taylor'
    case.representative.email = 'representative@example.test'
    case.declaration_acceptance = 'Sim'
    return case


def data(path):
    with fitz.open(path) as doc:
        return ET.fromstring(doc.xref_stream(packets(doc)['datasets'][1])).find(DATA)


class CanadaDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.case = synthetic_case()
        self.output = self.root/'drafts'

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_all_forms_and_distinct_contacts(self):
        report = generate_drafts(self.case,self.output)
        self.assertFalse(report['submission_ready'])
        self.assertEqual(set(report['forms']),set(FORMS))
        visa = data(self.output/'IMM5257-DRAFT.pdf')
        self.assertEqual(visa.find('.//Name/FamilyName').text,'EXAMPLE')
        self.assertEqual(visa.find('.//FaxEmail/Email').text,'applicant@example.test')
        self.assertEqual(visa.find('.//Funds/Funds').text,'5000.00')
        self.assertEqual(visa.find('.//Sex/Sex').text,'Male')
        self.assertEqual(visa.find('.//Passport/CountryofIssue/CountryofIssue').text,'709')
        self.assertIsNone(visa.find('.//OccupationRow1/ProvState').text)
        self.assertIn('activities[0].state',report['populated_fields_not_exported'])
        rep = data(self.output/'IMM5476-DRAFT.pdf')
        self.assertEqual(rep.find('.//SectionA/familyName').text,'EXAMPLE')
        self.assertEqual(rep.find('.//SectionB/familyName').text,'REPRESENTATIVE')
        self.assertEqual(rep.find('.//question7/email').text,'representative@example.test')
        self.assertEqual(rep.find('.//SectionA/office[1]').text,'applicant@example.test')
        self.assertIsNone(rep.find('.//SectionA/office[2]').text)
        self.assertIsNone(rep.find('.//SectionA/office[3]').text)
        for section in ('sectionC','sectionD'):
            node = rep.find('.//'+section+'/familyName')
            self.assertIsNone(node.text)
            self.assertEqual(len(node),0)
        self.assertIsNone(rep.find('.//RadioButtonList').text)
        self.assertNotIn('contact.address',report['populated_fields_not_exported'])
        self.assertIn('trip.host_email',report['populated_fields_not_exported'])
        from canada.preparation import prepare_case
        from copy import deepcopy
        self.assertEqual(load_case(self.output/'source.canada-case.json'),prepare_case(deepcopy(self.case)))

    def test_repeated_children_and_parent_order(self):
        generate_drafts(self.case,self.output)
        family = data(self.output/'IMM5707-DRAFT.pdf')
        children = family.findall('.//SectionB/Child')
        self.assertEqual(len(children),6)
        for i,node in enumerate(children):
            self.assertEqual(node.find('.//GivenNames').text,f'Child {i+1}')
        self.assertEqual(family.find('.//Parent1//GivenNames').text,'Jamie')
        self.assertEqual(family.find('.//Parent2//GivenNames').text,'Robin')

    def test_no_guessing_or_consent_signatures(self):
        self.case.identity.given_names = ''
        self.case.identity.full_name = 'DO NOT SPLIT ME'
        self.case.identity.sex = ''
        self.case.identity.birth_country = ''
        self.case.trip.available_funds_cad = ''
        generate_drafts(self.case,self.output)
        visa = data(self.output/'IMM5257-DRAFT.pdf')
        self.assertIsNone(visa.find('.//Name/GivenName').text)
        self.assertIsNone(visa.find('.//Sex/Sex').text)
        self.assertIsNone(visa.find('.//Funds/Funds').text)
        self.assertIsNone(visa.find('.//Consent0/Choice').text)
        for name in FORMS:
            for node in data(self.output/f'{name}-DRAFT.pdf').iter():
                if any(x in node.tag.lower() for x in ('signature','signatrure','datesigned','dateapplicantsigned','datespousesigned')):
                    self.assertFalse((node.text or '').strip())

    def test_template_identity_and_no_partial_bundle(self):
        templates = self.root/'templates'
        shutil.copytree(ROOT/'templates/canada',templates)
        with (templates/'IMM5707.pdf').open('ab') as output:
            output.write(b'\nchanged')
        with self.assertRaisesRegex(ValueError,'identity changed'):
            generate_drafts(self.case,self.output,templates)
        self.assertFalse(self.output.exists())

    def test_original_packets_unchanged_except_datasets(self):
        generate_drafts(self.case,self.output)
        for name in FORMS:
            with fitz.open(ROOT/f'templates/canada/{name}.pdf') as original, fitz.open(self.output/f'{name}-DRAFT.pdf') as draft:
                before,after = packets(original),packets(draft)
                self.assertEqual(before,after)
                for packet in before:
                    if packet != 'datasets':
                        self.assertEqual(original.xref_stream(before[packet][1]),draft.xref_stream(after[packet][1]))

    def test_existing_folder_not_overwritten(self):
        self.output.mkdir()
        marker = self.output/'keep.txt'
        marker.write_text('keep')
        with self.assertRaises(ValueError):
            generate_drafts(self.case,self.output)
        self.assertEqual(marker.read_text(),'keep')

    def test_invalid_values_remain_manual_and_overflow_reported(self):
        self.case.identity.date_of_birth = '31/02/1990'
        self.case.identity.sex = 'guess'
        self.case.trip.available_funds_cad = 'R$ 9000'
        self.case.import_profile = 'verified_20260929'
        self.case.activities[0].ongoing_answer = ''
        with self.assertRaisesRegex(ValueError,'BIRTH_DATE_INVALID'):
            generate_drafts(self.case,self.output)
        self.assertFalse(self.output.exists())

    def test_settings_edit_and_old_case_compatibility(self):
        session = ReviewSession(self.case)
        session.set_value('representative.email','corrected@example.test')
        session.apply()
        path = self.root/'test.canada-case.json'
        save_case(self.case,path)
        self.assertEqual(load_case(path).representative.email,'corrected@example.test')
        document = json.loads(path.read_text())
        del document['case']['representative']
        path.write_text(json.dumps(document))
        self.assertEqual(load_case(path).representative.family_name,'')

    def test_excess_parents_fail_transactionally(self):
        self.case.family.parents.append(FamilyMember(given_names='Extra'))
        with self.assertRaisesRegex(ValueError,'two parents'):
            generate_drafts(self.case,self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.iterdir()),[])

    def test_explicit_official_answers_are_distinct_from_broad_history(self):
        self.case.history.criminal_history_answer = 'No'
        self.case.official_review.tuberculosis_or_close_contact_last_two_years = 'No'
        self.case.official_review.disorder_requiring_social_or_health_services = 'Yes'
        self.case.official_review.medical_details = 'SYNTHETIC medical explanation'
        self.case.official_review.previously_applied_to_enter_or_remain_canada = 'Yes'
        generate_drafts(self.case,self.output)
        visa = data(self.output/'IMM5257-DRAFT.pdf')
        self.assertEqual(visa.find('.//BackgroundInfo/Choice[1]').text,'N')
        self.assertEqual(visa.find('.//BackgroundInfo/Choice[2]').text,'Y')
        self.assertEqual(visa.find('.//BackgroundInfo2/Details/VisaChoice3').text,'Y')
        self.assertIsNone(visa.find('.//PageWrapper/BackgroundInfo3/Choice').text)
        self.assertEqual(visa.find('.//MedicalDetails').text,'SYNTHETIC medical explanation')

    def test_representative_category_codes_and_membership_occurrences(self):
        self.case.representative.action = 'Appoint a representative'
        self.case.representative.membership_number = 'SYNTHETIC-ID'
        for i,(category,(group,code,membership)) in enumerate(REPRESENTATIVE_CATEGORIES.items()):
            with self.subTest(category=category):
                self.case.representative.category = category
                folder = self.root/f'category-{i}'
                generate_drafts(self.case,folder)
                rep = data(folder/'IMM5476-DRAFT.pdf')
                self.assertEqual(rep.find('.//RadioButtonList').text,'1')
                chosen = 'uncompensated' if group=='questionI' else 'compensated'
                other = 'compensated' if group=='questionI' else 'uncompensated'
                self.assertEqual(rep.find('.//'+chosen).text,code)
                self.assertIsNone(rep.find('.//'+other).text)
                if membership:
                    self.assertEqual(rep.find('.//question6/'+membership).text,'SYNTHETIC-ID')
                if category=='Unpaid - Quebec notary':
                    self.assertIsNone(rep.find('.//questionI/membership[1]').text)
                if category=='Unpaid - CICC member':
                    self.assertIsNone(rep.find('.//questionI/membership[2]').text)

    def test_cancellation_and_replacement_names_never_mix(self):
        self.case.representative.cancelled_family_name = 'OLDREP'
        self.case.representative.cancelled_given_names = 'Previous'
        self.case.representative.action = 'Cancel and appoint a new representative'
        generate_drafts(self.case,self.output)
        rep = data(self.output/'IMM5476-DRAFT.pdf')
        self.assertEqual(rep.find('.//RadioButtonList').text,'4')
        self.assertEqual(rep.find('.//sectionC/familyName').text,'OLDREP')
        self.assertEqual(rep.find('.//SectionB/familyName').text,'REPRESENTATIVE')
        self.assertIsNone(rep.find('.//sectionD/familyName').text)

    def test_cancellation_only_does_not_populate_new_representative(self):
        self.case.representative.action = 'Cancel a representative'
        self.case.representative.cancelled_family_name = 'OLDREP'
        generate_drafts(self.case,self.output)
        rep = data(self.output/'IMM5476-DRAFT.pdf')
        self.assertEqual(rep.find('.//RadioButtonList').text,'3')
        self.assertIsNone(rep.find('.//SectionB/familyName').text)
        self.assertEqual(rep.find('.//sectionC/familyName').text,'OLDREP')

    def test_withdrawal_does_not_populate_appointment(self):
        self.case.representative.action = 'Withdraw as representative'
        generate_drafts(self.case,self.output)
        rep = data(self.output/'IMM5476-DRAFT.pdf')
        self.assertEqual(rep.find('.//RadioButtonList').text,'5')
        self.assertEqual(rep.find('.//sectionD/familyName').text,'REPRESENTATIVE')
        self.assertIsNone(rep.find('.//SectionB/familyName').text)
        self.assertIsNone(rep.find('.//sectionD/signatrureApplicant').text)

    def test_official_choices_require_explicit_selection(self):
        session = ReviewSession(self.case)
        with self.assertRaises(ValueError):
            session.set_value('representative.category','probably paid')
        with self.assertRaises(ValueError):
            session.set_value('official_review.post_secondary_education','maybe')
        session.set_value('representative.action','Appoint a representative')
        session.set_value('representative.category','Unpaid - other')
        session.set_value('official_review.post_secondary_education','')
        session.apply()
        self.assertEqual(self.case.representative.action,'Appoint a representative')
        self.assertEqual(self.case.representative.category,'Unpaid - other')


if __name__ == '__main__':
    unittest.main()
