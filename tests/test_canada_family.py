import csv
import unittest
from pathlib import Path

from canada.source_readers import CsvResponseRow, canada_case_from_csv_row
from canada.family_reader import family_review_sections

FIXTURES = Path(__file__).parent / 'fixtures'


class FamilyImportTests(unittest.TestCase):
    def row(self, archive=False):
        name = 'canada_archive_csv_synthetic.csv' if archive else 'canada_csv_synthetic.csv'
        with (FIXTURES / name).open(newline='', encoding='utf-8-sig') as f:
            headers, values = list(csv.reader(f))
        return CsvResponseRow(headers, values)

    def test_both_versions_and_mixed_child_headers(self):
        for archive in (False, True):
            row = self.row(archive)
            case = canada_case_from_csv_row(row)
            self.assertEqual(case.relationships.spouse_family_name, row.values[15 if archive else 16])
            self.assertEqual(case.relationships.spouse_residence_answer, row.values[19 if archive else 8])
            self.assertEqual(case.relationships.former_spouse_full_name, row.values[21])
            self.assertEqual(len(case.family.parents), 2)
            for i, parent in enumerate(case.family.parents):
                self.assertEqual(parent.full_name, row.values[105 + 8*i])
                self.assertEqual(parent.death_details, row.values[111 + 8*i])
                self.assertEqual(parent.source_role, 'parent_or_guardian' if archive else 'parent')
            self.assertEqual(len(case.family.children), 5)
            for i, child in enumerate(case.family.children):
                self.assertEqual(child.full_name, row.values[123 + 9*i])
                self.assertEqual(child.accompanying_answer, row.values[129 + 9*i])
                self.assertEqual(child.source_block_index, i + 1)
                self.assertEqual(child.family_name, '')

    def test_blank_middle_block_and_unknown_answers_are_preserved(self):
        row = self.row()
        row.values[131:139] = [''] * 8
        row.values[121] = ''
        case = canada_case_from_csv_row(row)
        self.assertEqual(case.family.children[1].full_name, '')
        self.assertEqual(case.family.children[2].full_name, row.values[141])
        self.assertEqual(case.family.children[1].has_more_children_answer, row.values[139])
        self.assertEqual(case.family.has_children_answer, '')

    def test_shifted_columns_do_not_change_roles(self):
        row = self.row()
        row.headers.insert(110, 'Unrelated added question')
        row.values.insert(110, 'Synthetic value')
        case = canada_case_from_csv_row(row)
        self.assertEqual(case.family.parents[0].death_details, 'SYNTHETIC_C111')
        self.assertEqual(case.family.parents[1].death_details, 'SYNTHETIC_C119')

    def test_duplicate_within_block_is_rejected(self):
        row = self.row()
        row.headers.insert(125, row.headers[123])
        row.values.insert(125, '')
        with self.assertRaisesRegex(ValueError, 'Ambiguous Canada family'):
            canada_case_from_csv_row(row)

    def test_family_sections_visible_for_review(self):
        case = canada_case_from_csv_row(self.row())
        sections = list(family_review_sections(case))
        self.assertEqual(len(sections), 9)
        self.assertIs(sections[0][1], case.relationships)
        self.assertIn('source block 5', sections[-1][0])
        self.assertIs(sections[-1][1], case.family.children[4])

    def test_missing_child_anchor_is_rejected(self):
        row = self.row()
        row.headers[122] = 'Unrecognized child anchor'
        with self.assertRaisesRegex(ValueError, 'Ambiguous Canada family'):
            canada_case_from_csv_row(row)

    def test_no_answer_is_not_replaced_by_member_data(self):
        row = self.row()
        row.values[121] = 'Não'
        case = canada_case_from_csv_row(row)
        self.assertEqual(case.family.has_children_answer, 'Não')
        self.assertTrue(any('Children declared No' in issue for issue in case.validation_issues()))
        self.assertEqual(case.family.children[0].full_name, row.values[123])
