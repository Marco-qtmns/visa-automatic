"""Exact schema, manually constructed fictional responses; no client CSV copied."""
import csv
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from canada.source_readers import CsvResponseRow, canada_case_from_csv_row
from canada.preparation import prepare_case
from canada.review import ReviewSession
from canada.validation import validate_case
from canada.case_store import save_case, load_case
from canada.pdf_drafts import generate_drafts
from tests.test_canada_pdf_drafts import data

ADDRESS='Rua das Acácias, 123, Apto 41, Jardim Modelo, Campinas, SP, Brasil (endereço fictício)'


def source_case(address=ADDRESS):
    with (Path(__file__).parent/'fixtures/canada_20260929_synthetic.csv').open(encoding='utf-8',newline='') as f:
        headers=next(csv.reader(f))
    row=['']*234
    for i,value in {0:'2026/09/29 6:42:55 AM GMT-3',1:'Costa Almeida',2:'Mariana',
        4:'1990-01-01',9:'Brasil',36:'SYNTHETIC000',47:address,48:'Campinas',
        49:'SP – São Paulo',50:'13080-000',16:'Ferreira Santos',17:'Rafael Henrique',
        24:'Moura Pereira',25:'Carlos Eduardo',113:'Almeida',114:'João Roberto',
        123:'Costa',124:'Lúcia Helena',201:'A contradictory narrative name must never replace passport names'}.items():
        row[i]=value
    for start in (135,147,159,171,183):
        row[start]='Costa';row[start+1]='Costa'  # Shared token is still explicit given name.
    return canada_case_from_csv_row(CsvResponseRow(headers,row))


def values(c):
    return (c.identity.family_name,c.identity.given_names,c.contact.address,
            c.contact.city,c.contact.state,c.contact.postcode,c.identity.residence_country)


class NameAddressTests(unittest.TestCase):
    def test_current_234_csv_maps_applicant_name_and_address(self):
        c=source_case()
        self.assertEqual(values(c),('Costa Almeida','Mariana',ADDRESS,'Campinas','SP – São Paulo','13080-000','Brasil'))
        self.assertEqual(c.provenance['contact.address'].source_type,'csv_explicit')

    def test_preparation_preserves_explicit_name_and_address(self):
        c=source_case('  '+ADDRESS+'\n  '); before=values(c)
        prepare_case(c); prepare_case(c)
        self.assertEqual(values(c),before)

    def test_address_country_review_does_not_clear_address(self):
        c=prepare_case(source_case()); before=values(c)
        s=ReviewSession(c)
        self.assertEqual(values(s.preview()),before)
        s.set_value('identity.sex','Female'); s.apply()
        s=ReviewSession(c)
        s.resolve_issue(next(i for i in s.issues() if i.code=='ADDRESS_COUNTRY_CONFIRMATION'),confirm=True)
        s.apply()
        self.assertEqual(values(c),before)

    def test_explicit_applicant_name_components_do_not_require_review(self):
        issues=validate_case(source_case()).issues
        self.assertFalse(any(i.code=='REQUIRED_FIELD_MISSING' and i.field in ('identity.family_name','identity.given_names') for i in issues))
        self.assertTrue(any(i.code=='ADDRESS_COUNTRY_CONFIRMATION' for i in issues))

    def test_name_and_address_survive_case_save_reload(self):
        c=prepare_case(source_case('  '+ADDRESS+'\n  '))
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.canada-case.json';save_case(c,p)
            self.assertEqual(values(prepare_case(load_case(p))),values(c))

    def test_draft_receives_applicant_name_and_address_from_canada_case(self):
        c=prepare_case(source_case()); before=deepcopy(c)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'draft';report=generate_drafts(c,out)
            visa=data(out/'IMM5257-DRAFT.pdf')
            self.assertEqual(visa.find('.//Name/FamilyName').text,'Costa Almeida')
            self.assertEqual(visa.find('.//Name/GivenName').text,'Mariana')
            self.assertEqual(visa.find('.//ResidentialAddressRow1/StreetName/Streetname').text,ADDRESS.replace('á','a').replace('í','i'))
            self.assertEqual(visa.find('.//ResidentialAddressRow1/CityTown/CityTown').text,'Campinas')
            self.assertEqual(visa.find('.//ResidentialAddressRow2/PostalCode/PostalCode').text,'13080-000')
            self.assertIsNone(visa.find('.//ResidentialAddressRow2/Country/Country').text)
            family=data(out/'IMM5707-DRAFT.pdf')
            self.assertEqual(family.find('.//Applicant/PaddedEntry/PersonalData/FamilyName').text,'Costa Almeida')
            rep=data(out/'IMM5476-DRAFT.pdf')
            self.assertEqual(rep.find('.//SectionA/familyName').text,'Costa Almeida')
            self.assertIn('contact.address', [w['source'] for w in report['forms']['IMM5257']['writes']])
        self.assertEqual(c,before)

    def test_later_cidade_estado_headers_do_not_overwrite_contact_address(self):
        c=source_case();c.employment.city='Different city';c.employment.state='Different state'
        prepare_case(c)
        self.assertEqual(c.contact.city,'Campinas');self.assertEqual(c.contact.state,'SP – São Paulo')

    def test_direct_family_component_contract_including_shared_tokens(self):
        c=prepare_case(source_case())
        self.assertEqual(c.relationships.spouse_given_names,'Rafael Henrique')
        self.assertEqual(c.relationships.former_spouse_given_names,'Carlos Eduardo')
        self.assertEqual([p.given_names for p in c.family.parents],['João Roberto','Lúcia Helena'])
        self.assertEqual([p.given_names for p in c.family.children],['Costa']*5)

    def test_valid_override_wins_stale_override_does_not(self):
        c=source_case();s=ReviewSession(c);s.set_value('identity.family_name','Confirmed correction');s.apply()
        self.assertEqual(prepare_case(c).identity.family_name,'Confirmed correction')
        c.raw_response['Carimbo de data/hora']=['2026/09/30 10:00:00']
        self.assertEqual(prepare_case(c).identity.family_name,'Costa Almeida')
        c.identity.given_names='Wrong derived name';c.contact.address=''
        prepare_case(c)
        self.assertEqual(c.identity.given_names,'Mariana');self.assertEqual(c.contact.address,ADDRESS)

    def test_structured_street_override_and_long_address_fallback(self):
        c=source_case(ADDRESS+' additional fictional address details'*5)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'long'; report=generate_drafts(c,out)
            self.assertEqual(data(out/'IMM5257-DRAFT.pdf').find('.//ResidentialAddressRow1/StreetName/Streetname').text,
                             'See residential address in continuation sheet')
            self.assertIsNotNone(report['continuation'])
            c.official_review.residential_street_name='Confirmed street'
            out=Path(folder)/'override';generate_drafts(c,out)
            self.assertEqual(data(out/'IMM5257-DRAFT.pdf').find('.//ResidentialAddressRow1/StreetName/Streetname').text,'Confirmed street')


if __name__=='__main__': unittest.main()
