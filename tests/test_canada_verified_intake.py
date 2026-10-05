"""Actual September header schema with exclusively synthetic answers."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from canada.case_store import load_case, save_case
from canada.source_readers import CsvResponseRow, canada_case_from_csv_row, header_fingerprint, read_google_forms_csv
from canada.verified_intake import HEADER_SHA256, COLUMN_TARGETS, read_verified

ROOT = Path(__file__).resolve().parents[1]


def target_value(case, path):
    value = case
    for part in path.split('.'):
        if '[' in part:
            name, index = part.rstrip(']').split('[')
            value = getattr(value, name)[int(index)]
        else:
            value = getattr(value, part)
    return value


class VerifiedIntakeTests(unittest.TestCase):
    def row(self, replacements=None):
        with (ROOT / 'tests/fixtures/canada_20260929_synthetic.csv').open(encoding='utf-8', newline='') as f:
            headers, values = list(csv.reader(f))
        for index, value in (replacements or {}).items():
            values[index] = value
        return CsvResponseRow(headers, values)

    def test_every_nonmetadata_source_cell_has_one_exact_target(self):
        row = self.row()
        self.assertEqual(header_fingerprint(row.headers), HEADER_SHA256)
        self.assertEqual(set(COLUMN_TARGETS), set(range(1,234)))
        self.assertEqual(len(set(COLUMN_TARGETS.values())), 233)
        case = canada_case_from_csv_row(row)
        for index, path in COLUMN_TARGETS.items():
            self.assertEqual(target_value(case, path), row.values[index], path)
        self.assertEqual(case.import_profile, 'verified_20260929')
        self.assertEqual(sum(map(len, case.raw_response.values())), 234)

    def test_parent_country_typo_resolves_within_exact_verified_blocks(self):
        row = self.row({117:'', 127:'Synthetic country 2'})
        self.assertEqual(row.headers[117], row.headers[127])
        case = canada_case_from_csv_row(row)
        self.assertEqual(case.family.parents[0].birth_country, '')
        self.assertEqual(case.family.parents[1].birth_country, 'Synthetic country 2')
        self.assertEqual(case.family.parents[0].confirmed_role, '')
        self.assertEqual(case.family.parents[1].confirmed_role, '')

    def test_no_name_splitting_or_missing_identity_facts_inferred(self):
        case = canada_case_from_csv_row(self.row({1:'Example', 2:'Synthetic', 114:'Complete Synthetic Name'}))
        self.assertEqual(case.identity.family_name, 'Example')
        self.assertEqual(case.identity.given_names, 'Synthetic')
        self.assertEqual(case.identity.full_name, '')
        self.assertEqual(case.display_name(), 'Example, Synthetic')
        self.assertNotIn('Missing full name', case.validation_issues())
        self.assertEqual(case.identity.sex, '')
        self.assertEqual(case.identity.birth_country, '')
        self.assertEqual(case.family.parents[0].given_names, 'Complete Synthetic Name')
        self.assertEqual(case.family.parents[0].full_name, '')
        self.assertEqual(case.family.children[0].given_names, 'SYNTHETIC_R136')

    def test_blank_applicant_contacts_and_states_do_not_use_other_people(self):
        case = canada_case_from_csv_row(self.row({48:'',49:'',51:'',52:'',67:'Synthetic host phone',68:'host@example.test'}))
        self.assertEqual(case.contact.city, '')
        self.assertEqual(case.contact.state, '')
        self.assertEqual(case.contact.email, '')
        self.assertEqual(case.contact.phone, '')
        self.assertEqual(case.trip.host_email, 'host@example.test')
        self.assertEqual(case.trip.host_phone, 'Synthetic host phone')
        self.assertEqual(case.activities[0].state, 'SYNTHETIC_R088')

    def test_all_child_blocks_and_postcodes_keep_positions_including_blank_middle(self):
        row = self.row({i:'' for i in range(146,157)})
        case = canada_case_from_csv_row(row)
        self.assertEqual(len(case.family.children), 5)
        self.assertEqual(case.family.children[1].postcode, '')
        for block, index in ((0,143),(2,167),(3,179),(4,191)):
            self.assertEqual(case.family.children[block].postcode, row.values[index])
        self.assertEqual(case.family.children[4].date_of_birth, row.values[185])
        self.assertEqual(case.family.children[1].has_more_children_answer, row.values[157])

    def test_current_employment_plus_four_history_slots_and_end_date_uncertainty(self):
        row = self.row({0:'29/09/2026 10:00:00',83:'2020-01-01',84:'29/09/2026'})
        case = canada_case_from_csv_row(row)
        self.assertEqual(case.employment.state, row.values[80])
        self.assertEqual(len(case.activities),4)
        self.assertEqual(case.activities[0].end_date,'29/09/2026')
        self.assertEqual(case.activities[0].ongoing_answer,'')
        self.assertEqual(case.activities[0].country,'')
        self.assertTrue(any('end-date placeholder' in i for i in case.validation_issues()))

    def test_spouse_co_residence_and_spending_do_not_imply_other_answers(self):
        case = canada_case_from_csv_row(self.row({21:'Synthetic separate address',57:'4500'}))
        self.assertEqual(case.relationships.spouse_residence_answer, 'Synthetic separate address')
        self.assertEqual(case.relationships.spouse_address, '')
        self.assertEqual(case.relationships.spouse_accompanying_answer, 'SYNTHETIC_R022')
        self.assertEqual(case.trip.estimated_spend, '4500')
        self.assertEqual(case.trip.available_funds_cad, '')
        self.assertEqual(case.relationships.former_spouse_accompanying_answer, '')

    def test_document_roles_and_consent_are_preserved_not_executed(self):
        case = canada_case_from_csv_row(self.row())
        self.assertEqual(case.documents[4].references,'SYNTHETIC_R216')
        self.assertEqual(case.documents[4].source_role,'applicant')
        self.assertEqual(case.documents[15].references,'SYNTHETIC_R227')
        self.assertEqual(case.documents[15].source_role,'sponsor')
        self.assertEqual(case.declaration_acceptance,'SYNTHETIC_R233')

    def test_changed_headers_cannot_reuse_verified_column_offsets(self):
        for operation in ('reorder','insert','delete','rename'):
            row=self.row()
            if operation=='reorder': row.headers[117],row.headers[118]=row.headers[118],row.headers[117]
            elif operation=='insert': row.headers.insert(1,'New question')
            elif operation=='delete': row.headers.pop(1)
            else: row.headers[127]='País de nascimento do genitor 2'
            with self.assertRaises(ValueError):
                read_verified(row, HEADER_SHA256)

    def test_round_trip_and_extra_csv_cells_are_not_lost(self):
        case=canada_case_from_csv_row(self.row())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.canada-case.json'
            save_case(case,path)
            self.assertEqual(load_case(path),case)
            csv_path=Path(tmp)/'synthetic.csv'
            row=self.row()
            with csv_path.open('w',newline='') as f:
                csv.writer(f).writerows([row.headers,row.values+['unexpected cell']])
            with self.assertRaisesRegex(ValueError,'CSV_SCHEMA_MISMATCH'):
                read_google_forms_csv(csv_path)

    def test_matrix_matches_verified_schema_and_actual_mappings(self):
        matrix=json.loads((ROOT/'canada/coverage_matrix.yaml').read_text())
        self.assertEqual(matrix['source']['header_sha256'],HEADER_SHA256)
        self.assertEqual(len(matrix['source_fields']),234)
        case=canada_case_from_csv_row(self.row())
        for row in matrix['source_fields']:
            for path in row['reader_observation']['actual_targets']:
                self.assertEqual(target_value(case,path),f"SYNTHETIC_R{row['csv_index']:03}")
        self.assertEqual(matrix['reader_audit']['all_populated_mapped_column_count'],233)
