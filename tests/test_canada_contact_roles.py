"""Synthetic schema fixtures only; no real responses are required."""
import csv
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from canada.source_readers import CsvResponseRow, canada_case_from_csv_row, _norm

FIXTURES = Path(__file__).parent / 'fixtures'


class CanadaContactRoleTests(unittest.TestCase):
    def fixture(self, name='canada_csv_synthetic.csv'):
        with (FIXTURES / name).open(encoding='utf-8', newline='') as f:
            headers, values = list(csv.reader(f))
        return headers, values

    def indexes(self, headers, label):
        return [i for i,h in enumerate(headers) if _norm(h)==_norm(label)]

    def test_all_verified_layouts_keep_blanks_and_map_hosts(self):
        for name in ('canada_csv_synthetic.csv', 'canada_archive_csv_synthetic.csv',
                     'canada_schema_synthetic.csv'):
            with self.subTest(schema=name):
                headers, values = self.fixture(name)
                for label in ('Cidade', 'Telefone', 'E-mail'):
                    values[self.indexes(headers,label)[0]] = '  '
                case = canada_case_from_csv_row(CsvResponseRow(headers,values))
                self.assertEqual(case.contact.city,'')
                self.assertEqual(case.contact.email,'')
                self.assertEqual(case.contact.phone,'')
                self.assertEqual(case.source_email,'')
                self.assertEqual(case.trip.host_email,values[self.indexes(headers,'E-mail')[1]])
                self.assertEqual(case.trip.host_phone,values[self.indexes(headers,'Telefone')[1]])
                self.assertEqual(case.activities[0].city,values[self.indexes(headers,'Cidade')[1]])
                self.assertEqual(len(case.activities),4)

    def test_blank_host_contacts_never_use_applicant_values(self):
        for name in ('canada_csv_synthetic.csv', 'canada_archive_csv_synthetic.csv'):
            with self.subTest(schema=name):
                headers,values=self.fixture(name)
                for label in ('Telefone','E-mail'):
                    values[self.indexes(headers,label)[1]]=''
                case=canada_case_from_csv_row(CsvResponseRow(headers,values))
                self.assertEqual(case.trip.host_phone,'')
                self.assertEqual(case.trip.host_email,'')
                self.assertEqual(case.contact.phone,values[self.indexes(headers,'Telefone')[0]])
                self.assertEqual(case.contact.email,values[self.indexes(headers,'E-mail')[0]])

    def test_missing_applicant_contact_columns_do_not_relabel_host(self):
        headers,values=self.fixture()
        remove={self.indexes(headers,label)[0] for label in ('Telefone','E-mail')}
        host_phone=values[self.indexes(headers,'Telefone')[1]]
        host_email=values[self.indexes(headers,'E-mail')[1]]
        row=CsvResponseRow([h for i,h in enumerate(headers) if i not in remove],
                           [v for i,v in enumerate(values) if i not in remove])
        case=canada_case_from_csv_row(row)
        self.assertEqual(case.contact.phone,'')
        self.assertEqual(case.contact.email,'')
        self.assertEqual(case.source_email,'')
        self.assertEqual(case.trip.host_phone,host_phone)
        self.assertEqual(case.trip.host_email,host_email)

    def test_header_offsets_are_not_hardcoded(self):
        headers,values=self.fixture()
        # An extra metadata column shifts all contact positions without changing roles.
        headers.insert(0,'Audit metadata');values.insert(0,'SYNTHETIC_METADATA')
        case=canada_case_from_csv_row(CsvResponseRow(headers,values))
        self.assertEqual(case.trip.host_email,values[self.indexes(headers,'E-mail')[1]])
        self.assertEqual(case.contact.city,values[self.indexes(headers,'Cidade')[0]])

    def test_duplicate_without_role_evidence_is_rejected(self):
        for label in ('Telefone','E-mail','Cidade'):
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError,'Ambiguous Canada CSV layout'):
                    canada_case_from_csv_row(CsvResponseRow([label,label],['FIRST','SECOND']))

    def test_extra_contact_in_applicant_section_is_rejected(self):
        headers,values=self.fixture()
        index=self.indexes(headers,'Telefone')[0]
        headers.insert(index,'Telefone');values.insert(index,'UNASSIGNED_PHONE')
        with self.assertRaisesRegex(ValueError,'Ambiguous Canada CSV layout for Telefone'):
            canada_case_from_csv_row(CsvResponseRow(headers,values))

    def test_extra_city_in_activity_block_is_rejected(self):
        headers,values=self.fixture()
        index=self.indexes(headers,'Cidade')[1]
        headers.insert(index,'Cidade');values.insert(index,'UNASSIGNED_CITY')
        with self.assertRaisesRegex(ValueError,'Ambiguous Canada CSV layout for Cidade'):
            canada_case_from_csv_row(CsvResponseRow(headers,values))

    def test_old_and_new_aliases_map_without_changing_date_format(self):
        for residence,education in (
            ('Desde quando você reside nesse país?', 'Qual seu nível de formação educacional mais recente?'),
            ('Desde quando reside nesse país atual? ', 'Qual seu nível de formação educacional mais recente (completo ou incompleto)?'),
        ):
            with self.subTest(residence=residence):
                case=canada_case_from_csv_row(CsvResponseRow([residence,education],['1/2/2020','Ensino superior']))
                self.assertEqual(case.identity.residence_since,'01/02/2020')
                self.assertEqual(case.education.level,'Ensino superior')


if __name__ == '__main__':
    unittest.main()
