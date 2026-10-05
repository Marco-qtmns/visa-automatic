"""All answers below are synthetic; draft headers are not a real export."""
import csv
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import App
from canada.case_store import load_case, save_case
from canada.models import CanadaCase
from canada.review import ReviewSession
from canada.source_readers import CsvResponseRow, canada_case_from_csv_row, read_google_forms_csv
from canada.workflow import CanadaWorkflow

FIXTURES = Path(__file__).parent / 'fixtures'


def draft_case(extra=None):
    values = {
        'Nome completo conforme passaporte': 'Example Synthetic',
        'Sobrenome conforme passaporte': 'Example',
        'Todos os nomes conforme passaporte': 'Synthetic',
        'Sexo': 'X', 'País de nascimento': 'Brazil',
        'Endereço residencial completo': 'SQN 000, Bloco X, apto 00, Brasília — DF',
        'CEP residencial': '00000-000',
        'E-mail do requerente': '', 'E-mail do anfitrião no Canadá': 'host@example.test',
        'Telefone do requerente': '', 'Telefone do anfitrião no Canadá': '+1 000 000 0000',
        'Fundos disponíveis para a viagem em CAD': '4500',
        'Quem pagará a viagem?': 'Eu',
        'Sobrenome da mãe': 'Example', 'Nomes da mãe': 'Mother',
        'País de nascimento da mãe': 'Brazil',
        'Sobrenome do pai': 'Example', 'Nomes do pai': 'Father',
        'País de nascimento do pai': 'Brazil',
        'Histórico de viagens — países, datas e motivo': 'Portugal — 2020, dates to confirm',
    }
    for i in range(1, 6):
        values.update({f'Sobrenome do filho {i:02}': f'Child{i}', f'Nomes do filho {i:02}': 'Synthetic',
                       f'Atividade {i:02} — tipo': 'Estudo', f'Atividade {i:02} — cidade': 'Brasília',
                       f'Atividade {i:02} — estado/província': 'DF',
                       f'Atividade {i:02} — em andamento?': 'Sim' if i == 1 else 'Não',
                       f'Atividade {i:02} — término': '' if i == 1 else '01/01/2020'})
    values.update(extra or {})
    return canada_case_from_csv_row(CsvResponseRow(list(values), list(values.values())))


class AdaptationTests(unittest.TestCase):
    def test_draft_names_address_funds_contacts_and_parent_roles(self):
        case = draft_case()
        self.assertEqual(case.identity.family_name, 'Example')
        self.assertEqual(case.identity.given_names, 'Synthetic')
        self.assertEqual(case.contact.address, 'SQN 000, Bloco X, apto 00, Brasília — DF')
        self.assertEqual(case.contact.country, '')
        self.assertEqual(case.contact.city, '')
        self.assertEqual(case.contact.email, '')
        self.assertEqual(case.contact.phone, '')
        self.assertEqual(case.trip.host_email, 'host@example.test')
        self.assertEqual(case.trip.available_funds_cad, '4500')
        self.assertEqual(case.trip.estimated_spend, '')
        self.assertEqual([p.confirmed_role for p in case.family.parents], ['mother', 'father'])
        self.assertEqual(case.import_profile, 'updated_unverified')

    def test_five_blocks_and_no_country_or_present_end_date_inference(self):
        case = draft_case({'Sobrenome do filho 02': '', 'Nomes do filho 02': ''})
        self.assertEqual(len(case.family.children), 5)
        self.assertEqual(case.family.children[2].family_name, 'Child3')
        self.assertEqual(case.family.children[1].source_block_index, 2)
        self.assertEqual(len(case.activities), 5)
        self.assertEqual(case.activities[0].ongoing_answer, 'Sim')
        self.assertEqual(case.activities[0].end_date, '')
        self.assertEqual(case.activities[0].country, '')
        self.assertEqual(case.activities[0].state, 'DF')

    def test_combined_history_preserved_and_reviewed_explicitly(self):
        case = draft_case()
        narrative = case.history.travel_details
        self.assertTrue(any('narrative' in i for i in case.validation_issues()))
        session = ReviewSession(case)
        session.set_value('staff_review.history_reviewed', 'Sim')
        session.apply()
        self.assertEqual(case.history.travel_details, narrative)
        # A blanket legacy flag no longer clears incomplete structured records.
        self.assertTrue(any('TRAVEL_RECORD_INCOMPLETE' in i for i in case.validation_issues()))

    def test_partner_details_do_not_copy_applicant_address(self):
        case = draft_case({'O cônjuge mora com você?': 'Sim',
                           'Endereço do cônjuge, se diferente': '',
                           'O cônjuge viajará com você ao Canadá?': 'Não',
                           'O ex-cônjuge mora com você?': 'Não',
                           'Endereço do ex-cônjuge, se diferente': 'Synthetic address',
                           'O ex-cônjuge viajará com você ao Canadá?': 'Não'})
        self.assertEqual(case.relationships.spouse_residence_answer, 'Sim')
        self.assertEqual(case.relationships.spouse_address, '')
        self.assertEqual(case.relationships.former_spouse_address, 'Synthetic address')

    def test_duplicate_explicit_field_is_rejected_even_when_blank(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            canada_case_from_csv_row(CsvResponseRow(['Sexo', 'Sexo'], ['X', '']))

    def test_legacy_imports_still_work_and_do_not_relabel_spending(self):
        for name in ('canada_csv_synthetic.csv', 'canada_archive_csv_synthetic.csv'):
            case = read_google_forms_csv(FIXTURES / name)[0]
            self.assertEqual(case.import_profile, 'legacy')
            self.assertEqual(sum(map(len, case.raw_response.values())), 207)
            self.assertEqual(case.trip.available_funds_cad, '')
            self.assertTrue(case.trip.estimated_spend)
            self.assertEqual(case.family.parents[0].confirmed_role, '')
            self.assertTrue(case.history.travel_details)

    def test_repeated_activity_states_do_not_fill_blank_applicant_state(self):
        with (FIXTURES / 'canada_csv_synthetic.csv').open(newline='') as f:
            headers, values = list(csv.reader(f))
        values[headers.index('Estado')] = ''
        i = headers.index('Tipo de atividade') + 1
        headers.insert(i, 'Estado')
        values.insert(i, 'Synthetic activity state')
        case = canada_case_from_csv_row(CsvResponseRow(headers, values))
        self.assertEqual(case.contact.state, '')
        self.assertEqual(case.activities[0].state, 'Synthetic activity state')

    def test_guardian_is_not_a_parent_assignment(self):
        case = draft_case()
        session = ReviewSession(case)
        with self.assertRaises(ValueError):
            session.set_value('family.parents[0].confirmed_role', 'legal_guardian')
        session.set_value('staff_review.guardianship_notes', 'Separate court decision')
        session.set_value('staff_review.guardianship_document_reference', 'local reference only')
        session.apply()
        self.assertEqual(case.family.parents[0].confirmed_role, 'mother')

    def test_no_children_answer_conflicts_with_separate_names(self):
        case = draft_case({'Possui filhos?': 'Não'})
        self.assertTrue(any('Children declared No' in i for i in case.validation_issues()))

    def test_unknown_schema_is_flagged_even_without_draft_aliases(self):
        case = canada_case_from_csv_row(CsvResponseRow(['Unrecognized revised name field'], ['Synthetic']))
        self.assertEqual(case.import_profile, 'schema_unverified')
        self.assertTrue(any('provisional' in i for i in case.validation_issues()))
        self.assertEqual(case.raw_response['Unrecognized revised name field'], ['Synthetic'])

    def test_added_names_in_legacy_parent_block_do_not_infer_mother(self):
        with (FIXTURES / 'canada_csv_synthetic.csv').open(newline='') as f:
            headers, values = list(csv.reader(f))
        headers += ['Sobrenome do genitor 1', 'Nomes do genitor 1', 'País de nascimento do genitor 1']
        values += ['Example', 'Synthetic', 'Brazil']
        case = canada_case_from_csv_row(CsvResponseRow(headers, values))
        self.assertEqual(case.family.parents[0].family_name, 'Example')
        self.assertEqual(case.family.parents[0].confirmed_role, '')

    def test_duplicate_parent_addition_rejected_without_losing_edits(self):
        case = draft_case()
        session = ReviewSession(case)
        session.set_value('staff_review.follow_up_notes', 'Synthetic note')
        with self.assertRaises(ValueError):
            session.add_record('mother')
        self.assertEqual(session.preview().staff_review.follow_up_notes, 'Synthetic note')
        self.assertEqual(case.staff_review.follow_up_notes, '')

    def test_whatsapp_additions_are_transactional_unlimited_and_audited(self):
        case = draft_case()
        original = deepcopy(case)
        session = ReviewSession(case)
        session.add_record('child')
        session.set_value('family.children[5].family_name', 'Additional')
        session.add_record('activity')
        session.set_value('activities[5].organization', 'Synthetic follow-up')
        session.add_record('activity')
        self.assertEqual(case, original)
        session.apply()
        self.assertEqual(len(case.family.children), 6)
        self.assertEqual(len(case.activities), 7)
        self.assertEqual(case.family.children[5].source_role, 'staff_child')
        self.assertEqual(case.raw_response, original.raw_response)
        self.assertTrue(any(c.path == 'family.children[5]' for c in case.review_changes))
        self.assertEqual(session.apply(), [])


class CaseStorageTests(unittest.TestCase):
    def test_round_trip_including_extra_records_raw_answers_and_audit(self):
        case = draft_case()
        session = ReviewSession(case)
        session.add_record('child')
        session.set_value('family.children[5].given_names', 'Follow-up synthetic')
        session.set_value('staff_review.uci', 'synthetic-uci')
        session.apply()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'client.canada-case.json'
            save_case(case, path)
            self.assertEqual(load_case(path), case)
            self.assertEqual(CanadaWorkflow().read_source(path), [case])
            self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_source_overwrite_and_invalid_formats_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.csv'
            source.write_text('unchanged')
            with self.assertRaises(ValueError):
                save_case(CanadaCase(), source)
            self.assertEqual(source.read_text(), 'unchanged')
            path = Path(tmp) / 'bad.canada-case.json'
            for data in ({'format': 'other', 'version': 1, 'case': {}},
                         {'format': 'visa-automatic-canada-case', 'version': 2, 'case': {}},
                         {'format': 'visa-automatic-canada-case', 'version': 1, 'case': {'identity': {'full_name': 42}}},
                         {'format': 'visa-automatic-canada-case', 'version': 1, 'case': {'unexpected': ''}}):
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_case(path)

    def test_read_only_import_metadata_cannot_be_edited(self):
        session = ReviewSession(draft_case())
        for path in ('import_profile', 'source_headers', 'source_header_sha256'):
            with self.assertRaises(ValueError):
                session.set_value(path, 'changed')

    def test_failed_replace_preserves_previous_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'case.canada-case.json'
            save_case(CanadaCase(), path)
            before = path.read_bytes()
            with patch('canada.case_store.os.replace', side_effect=OSError('synthetic failure')):
                with self.assertRaises(OSError):
                    save_case(draft_case(), path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_app_save_and_cancel(self):
        case = draft_case()
        ui = SimpleNamespace(canada_case=case, status=Mock())
        with patch('app.filedialog.asksaveasfilename', return_value='') as chooser, patch('canada.case_store.save_case') as save:
            App.save_canada_case(ui)
            save.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'case.canada-case.json'
            with patch('app.filedialog.asksaveasfilename', return_value=str(path)):
                App.save_canada_case(ui)
            self.assertEqual(load_case(path), case)
