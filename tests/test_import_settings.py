"""Regression tests use synthetic client/recipient data only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
import settings
from models import RecipientData
from source_readers import applicant_from_csv_row, read_google_forms_pdf
from form956a import build_field_values


class SettingsTests(unittest.TestCase):
    def test_fresh_install_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(settings, 'settings_path', return_value=Path(tmp)/'settings.json'):
                self.assertFalse(any(settings.load_settings()['recipient'].values()))
                self.assertFalse(any(settings.load_settings()['recipient'].values()))

    def test_all_old_versions_preserve_values_and_blanks(self):
        for version in (None, 0, 1, 2, 3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'settings.json'
                original = {'address_line1': 'EMPLOYEE ADDRESS', 'address_line2': '',
                            'country': 'COUNTRY', 'office_number': '', 'given_names': 'TEST'}
                data = {'recipient': original}
                if version is not None:
                    data['settings_version'] = version
                path.write_text(json.dumps(data))
                with patch.object(settings, 'settings_path', return_value=path):
                    for _ in range(2):
                        result = settings.load_settings()['recipient']
                        for key, value in result.items():
                            self.assertEqual(value, original.get(key, ''))


class ImportTests(unittest.TestCase):
    def test_new_csv_address_fields(self):
        a = applicant_from_csv_row({'Nome': 'TEST', 'Sobrenome completo': 'CLIENT',
            'Cidade de nascimento': 'WRONG CITY', 'Estado civil': 'Solteiro',
            'Endereço residencial completo': 'Rua Teste 10', 'Cidade': 'Test City',
            'Estado': 'DF – Distrito Federal', 'CEP': '12345678'})
        self.assertEqual(a.city, 'Test City')
        self.assertEqual(a.state, 'DF – Distrito Federal')
        values = build_field_values(a, RecipientData())
        self.assertEqual(values['ap.resadd pc'], '12345-678')
        self.assertIn('TEST CITY', values['ap.resadd str'] + values['ap.resadd sub'])
        self.assertIn('DISTRITO FEDERAL', values['ap.resadd str'] + values['ap.resadd sub'])

    def test_csv_address_fallback_extracts_cep_and_state(self):
        a = applicant_from_csv_row({
            "Endereço residencial completo":
                "AVENIDA TESTE 100 BRASÍLIA-DF CEP 71930-000",
            "Cidade": "",
            "Estado": "",
            "CEP": "",
        })

        self.assertEqual(a.city, "")
        self.assertEqual(a.state, "DF")
        self.assertEqual(a.postcode, "71930-000")

        values = build_field_values(a, RecipientData())

        self.assertEqual(values["ap.resadd pc"], "71930-000")

        rendered_address = (
            values["ap.resadd str"] + " " +
            values["ap.resadd sub"]
        )

        # The fallback state must not be appended a second time.
        self.assertNotIn("DF, DF", rendered_address)


    def test_csv_address_fallback_extracts_plain_8_digit_cep(self):
        a = applicant_from_csv_row({
            "Endereço residencial completo": "71930000",
            "CEP": "",
        })

        self.assertEqual(a.postcode, "71930-000")


    def test_explicit_address_fields_override_fallback(self):
        a = applicant_from_csv_row({
            "Endereço residencial completo":
                "Rua Teste 10, São Paulo-SP CEP 01000-000",
            "Cidade": "Brasília",
            "Estado": "DF – Distrito Federal",
            "CEP": "71930000",
        })

        self.assertEqual(a.city, "Brasília")
        self.assertEqual(a.state, "DF – Distrito Federal")
        self.assertEqual(a.postcode, "71930000")


    def test_old_csv_address_still_works(self):
        a = applicant_from_csv_row({'Endereço residencial completo, com CEP':
                                   'Rua Teste 10 - 12345-678'})
        values = build_field_values(a, RecipientData())
        self.assertEqual(values['ap.resadd str'], 'RUA TESTE 10')
        self.assertEqual(values['ap.resadd pc'], '12345-678')

    def test_pdf_answers_on_shifted_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'synthetic.pdf'
            with fitz.open() as doc:
                doc.new_page()  # No fixed page assumptions.
                page = doc.new_page()
                for y, label, answer in [(60,'Sobrenome completo *','CLIENT'),
                        (160,'Nome *','TEST'), (260,'Data de nascimento *','01/02/2000'),
                        (360,'Endereço residencial completo *','Rua Teste 10'),
                        (460,'Cidade *','Test City'), (560,'CEP *','12345678')]:
                    page.insert_text((40,y), str(y//100+1)+'.')
                    page.insert_text((72,y), label)
                    page.insert_text((72,y+35), answer)
                page = doc.new_page()
                page.insert_text((72,60),'Telefone celular. Informe somente números, sem espaços *')
                page.insert_text((72,80),'Exemplo: 5511999999999')
                page.insert_text((72,110),'11900000000')
                page.insert_text((40,160),'8.')
                page.insert_text((72,160),'E-mail *')
                page.insert_text((72,195),'client@example.invalid')
                page.insert_text((40,240),'9.')
                page.insert_text((72,240),'Estado civil *')
                page.insert_text((72,265),'Marcar apenas uma oval.')
                page.insert_text((72,285),'Solteiro')
                page.insert_text((72,305),'Casado')
                doc.save(path)
            a = read_google_forms_pdf(path)
            self.assertEqual(a.family_name, 'CLIENT')
            self.assertEqual(a.given_names, 'TEST')
            self.assertEqual(a.date_of_birth, '01/02/2000')
            self.assertEqual(a.city, 'Test City')
            self.assertEqual(a.postcode, '12345678')
            self.assertEqual(a.mobile, '11900000000')
            self.assertEqual(a.source_email, 'client@example.invalid')
            self.assertEqual(a.marital_status, '')


if __name__ == '__main__':
    unittest.main()
