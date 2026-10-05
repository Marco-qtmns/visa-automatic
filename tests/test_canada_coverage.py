"""Schema-derived regression tests. No client PDF or client answers required.

Historical audit snapshots remain separate from current reader expectations.
The six previously expected failures are regular regression tests now.
"""
import csv
from dataclasses import fields, is_dataclass
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from canada.source_readers import read_google_forms_csv, canada_case_from_csv_row, CsvResponseRow
from tools.inventory_canada_fields import inventory
import fitz

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'


class CanadaSchemaCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.current_matrix = json.loads((ROOT / 'canada/coverage_matrix.yaml').read_text(encoding='utf-8'))
        # Continue verifying the two historical schemas against their preserved audit.
        if 'pre_20260929_baseline' in cls.current_matrix:
            cls.current_matrix.update(cls.current_matrix['pre_20260929_baseline'])
        cls.matrix = dict(cls.current_matrix)
        cls.matrix.update(cls.current_matrix['pdf_schema_baseline'])
        cls.current_schema = json.loads((FIXTURES / 'canada_csv_schema.json').read_text(encoding='utf-8'))
        with (FIXTURES / 'canada_csv_synthetic.csv').open(encoding='utf-8', newline='') as f:
            cls.current_headers, cls.current_values = list(csv.reader(f))
        cls.schema = json.loads((FIXTURES / 'canada_pdf_schema.json').read_text(encoding='utf-8'))
        with (FIXTURES / 'canada_schema_synthetic.csv').open(encoding='utf-8', newline='') as f:
            cls.headers, cls.values = list(csv.reader(f))

    def read_case(self, overrides=None):
        values = self.values.copy()
        for question, value in (overrides or {}).items():
            values[question-1] = value
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic.csv'
            with path.open('w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)
                writer.writerow(values)
            return canada_case_from_csv_row(CsvResponseRow(self.headers, values))

    def read_current_case(self, overrides=None):
        values = self.current_values.copy()
        for index, value in (overrides or {}).items():
            values[index] = value
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic.csv'
            with path.open('w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.current_headers)
                writer.writerow(values)
            return read_google_forms_csv(path)[0]

    def test_all_printed_questions_have_unique_matrix_rows(self):
        questions = self.schema['questions']
        rows = self.matrix['source_fields']
        self.assertEqual([q['question_number'] for q in questions], list(range(1,155)))
        self.assertEqual([r['question_number'] for r in rows], list(range(1,155)))
        self.assertEqual(self.headers, [q['source_header'] for q in questions])
        self.assertEqual(self.headers, [r['source_header'] for r in rows])
        self.assertEqual(len({r['id'] for r in rows}), 154)
        self.assertFalse(self.matrix['source']['submitted_values_observed'])
        self.assertFalse(self.matrix['source']['csv_headers_verified'])

    def test_repeated_labels_and_activity_order(self):
        for label, numbers in {
            'Cidade': [38,77,84,91,98],
            'Telefone': [42,57], 'E-mail': [41,58],
            'Tipo de atividade': [72,79,86,93],
            'Extratos bancários dos últimos 3 meses': [137,148],
            'Imposto de Renda': [138,149],
            'Contracheques dos últimos 3 meses': [140,150],
            'Contrato Social (se for empresário)': [142,151],
            'Cartão CNPJ (se for empresário)': [143,152],
            '3 últimos pró-labores (se for empresário)': [144,153],
            'Data de início': [73,80,87,94],
            'Data de término': [74,81,88,95],
            'Cargo': [75,82,89,96],
            'Nome da empresa, empregador ou instituição': [76,83,90,97],
            'Você possui outra atividade para informar nos últimos 10 anos?': [78,85,92,99],
        }.items():
            with self.subTest(label=label):
                matches = [r for r in self.matrix['source_fields'] if r['source_header']==label]
                self.assertEqual([r['question_number'] for r in matches], numbers)
                self.assertEqual([r['occurrence'] for r in matches], list(range(1,len(numbers)+1)))

    def test_synthetic_fixture_contains_only_generated_markers(self):
        self.assertEqual(self.values, [f'SYNTHETIC_Q{i:03}' for i in range(1,155)])

    def test_all_answers_survive_in_raw_response_including_unmapped_sections(self):
        case = self.read_case()
        self.assertEqual(sum(map(len,case.raw_response.values())),154)
        self.assertEqual(case.raw_response['Cidade'], [self.values[i-1] for i in (38,77,84,91,98)])
        for n in (14,100,113,117,122,128,132,154):
            self.assertIn(self.values[n-1],case.raw_response[self.headers[n-1]])

    def test_observed_model_assignments_match_matrix(self):
        case = self.read_case()
        assigned = 0
        for row in self.matrix['source_fields']:
            paths = row['reader_observation']['actual_targets']
            if paths: assigned += 1
            for path in paths:
                obj = case
                for part in path.split('.'):
                    if '[' in part:
                        name,index = part.rstrip(']').split('[')
                        obj = getattr(obj,name)[int(index)]
                    else: obj = getattr(obj,part)
                self.assertEqual(obj,self.values[row['question_number']-1],path)
        self.assertEqual(assigned,self.matrix['reader_audit']['all_populated_mapped_question_count'])
        self.assertEqual(assigned,79)

    def test_four_activity_blocks_keep_their_own_cities_and_organizations(self):
        case = self.read_case()
        self.assertEqual(len(case.activities),4)
        for index,start in enumerate((72,79,86,93)):
            activity = case.activities[index]
            self.assertEqual(activity.city,self.values[start+4])
            self.assertEqual(activity.organization,self.values[start+3])
        self.assertEqual(case.contact.city,self.values[37])

    def test_empty_middle_activity_does_not_shift_later_values(self):
        case = self.read_case({n:'' for n in range(79,85)})
        self.assertEqual(len(case.activities),3)
        self.assertEqual(case.activities[1].activity_type,self.values[85])
        self.assertEqual(case.activities[1].city,self.values[90])
        self.assertEqual(case.activities[1].organization,self.values[89])

    def test_names_sex_and_birth_country_are_never_inferred(self):
        case = self.read_case({1:'EXAMPLE COMBINED NAME',3:'01/02/2000'})
        self.assertEqual(case.identity.family_name,'')
        self.assertEqual(case.identity.given_names,'')
        self.assertEqual(case.identity.sex,'')
        self.assertEqual(case.identity.date_of_birth,'01/02/2000')
        self.assertEqual(case.identity.birth_country,'')
        self.assertTrue(case.validation_issues())

    def test_blank_applicant_city_must_not_use_activity_city(self):
        self.assertEqual(self.read_current_case({43:''}).contact.city,'')

    def test_blank_applicant_email_must_not_use_host_email(self):
        case = self.read_current_case({46:'',63:'host@example.invalid'})
        self.assertEqual(case.contact.email,'')
        self.assertEqual(case.source_email,'')

    def test_blank_applicant_phone_must_not_use_host_phone(self):
        self.assertEqual(self.read_current_case({47:'',62:'+1 202 555 0100'}).contact.phone,'')

    def test_host_contacts_must_have_their_own_assignments(self):
        case = self.read_current_case({62:'+1 202 555 0100',63:'host@example.invalid'})
        self.assertEqual(case.trip.host_phone,'+1 202 555 0100')
        self.assertEqual(case.trip.host_email,'host@example.invalid')

    def test_every_target_resolves_to_exact_hashed_template_node(self):
        for form, template in self.matrix['templates'].items():
            path = ROOT / template['file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),template['sha256'])
            current = inventory(path)
            self.assertEqual(len(current['widgets']),template['widget_count'])
            self.assertEqual(current['packets'],template['packets'])
            with fitz.open(path) as doc:
                for key,target in self.matrix['target_catalog'].items():
                    if target['template']!=form: continue
                    packet = current['packets'][target['packet_index']]
                    self.assertEqual(packet['name'],target['packet'])
                    self.assertEqual(packet['sha256'],target['packet_sha256'])
                    self.assertEqual(target['template_sha256'],template['sha256'])
                    node = ET.fromstring(doc.xref_stream(packet['xref']))
                    route = target['xml_path']
                    self.assertEqual(node.tag,route[0]['tag'])
                    self.assertEqual(route[0]['index'],1)
                    for step in route[1:]:
                        node = [child for child in node if child.tag==step['tag']][step['index']-1]
                    self.assertEqual(node.get('name'),target['node_name'],key)
                    self.assertEqual(node.tag.rsplit('}',1)[-1],target['kind'])
                    matches = [f for f in current['fields'] if f['packet_index']==target['packet_index'] and f['xml_path']==route]
                    self.assertEqual(len(matches),1)
                    self.assertEqual(matches[0]['named_path'],target['hierarchical_path'])

    def test_references_and_statuses_are_valid(self):
        allowed = {'covered','missing_from_model','missing_from_intake','ambiguous',
                   'conditional','manual','static_setting','derived_safely','not_required'}
        for row in self.matrix['source_fields']+self.matrix['intake_gaps']:
            self.assertIn(row['status'],allowed)
            for form in self.matrix['templates']:
                for key in row[form+'_target']:
                    self.assertIn(key,self.matrix['target_catalog'])
                    self.assertEqual(self.matrix['target_catalog'][key]['template'],form)

    def test_duplicate_office_fields_are_not_conflated(self):
        catalog = self.matrix['target_catalog']
        email = catalog[self.matrix['source_fields'][40]['IMM5476_target'][0]]
        fallback = catalog[self.matrix['source_fields'][41]['IMM5476_target'][0]]
        application = next(r for r in self.matrix['intake_gaps'] if r['id']=='application_type')
        application = catalog[application['IMM5476_target'][0]]
        self.assertTrue(email['hierarchical_path'].endswith('/office[0]'))
        self.assertTrue(fallback['hierarchical_path'].endswith('/office[1]'))
        self.assertTrue(application['hierarchical_path'].endswith('/office[2]'))
        self.assertEqual(len({json.dumps(t['xml_path']) for t in (email,fallback,application)}),3)

    def test_non_equivalent_questions_have_no_direct_mapping(self):
        # Estimated spending is not funds available; birth city is not country.
        for n in (47,102,108,118,121):
            row = self.matrix['source_fields'][n-1]
            self.assertFalse(row['IMM5257_target'])
            self.assertFalse(row['IMM5707_target'])
        signature = next(g for g in self.matrix['intake_gaps'] if g['id']=='signatures')
        self.assertEqual(signature['status'],'manual')
        self.assertFalse(self.matrix['source_fields'][153]['IMM5476_target'])

    def test_current_csv_header_fingerprint_and_synthetic_values(self):
        self.assertEqual(len(self.current_headers),207)
        self.assertEqual(self.current_headers,[c['header'] for c in self.current_schema['columns']])
        self.assertEqual(self.current_values,[f'SYNTHETIC_C{i:03}' for i in range(207)])
        digest = hashlib.sha256(json.dumps(self.current_headers,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(digest,self.current_schema['header_sha256'])
        self.assertEqual(digest,self.current_matrix['source']['header_sha256'])
        self.assertTrue(self.current_matrix['source']['csv_headers_verified'])
        self.assertEqual(self.current_headers[0],'Carimbo de data/hora')
        self.assertTrue(self.current_headers[46].endswith(' '))
        self.assertNotEqual(self.current_headers[46],self.current_headers[63])
        self.assertIn('\n',self.current_headers[2])

    def test_current_csv_repeated_roles_have_verified_occurrences(self):
        from canada.source_readers import _norm
        for label,indexes in {
            'Cidade':[43,82,89,96,103], 'Telefone':[47,62], 'E-mail':[46,63],
            'Tipo de Filiação':[122,131,140,149,158],
            'Nome completo do filho':[123,132,141,150],
            'Nome completo do filho(a).':[159],
            'Você possui outros filhos?':[130,139,148,157],
            'Se seu genitor 1 for falecido, informar a data e a cidade do óbito':[111],
            'Se seu genitor for falecido, informar a data e a cidade do óbito':[119],
        }.items():
            found=[r for r in self.current_matrix['source_fields'] if _norm(r['source_header'])==_norm(label)]
            self.assertEqual([r['csv_index'] for r in found],indexes)
            self.assertEqual([r['occurrence'] for r in found],list(range(1,len(indexes)+1)))
        self.assertEqual(self.current_matrix['source_fields'][63]['exact_header_occurrence'],1)
        self.assertEqual(self.current_matrix['source_fields'][63]['occurrence'],2)

    def test_current_matrix_assignments_match_reader(self):
        case=self.read_current_case()
        mapped=0
        for row in self.current_matrix['source_fields']:
            paths=row['reader_observation']['actual_targets']
            if paths:mapped+=1
            for path in paths:
                obj=case
                for part in path.split('.'):
                    if '[' in part:
                        name,index=part.rstrip(']').split('[')
                        obj=getattr(obj,name)[int(index)]
                    else:obj=getattr(obj,part)
                self.assertEqual(obj,self.current_values[row['csv_index']],path)
        self.assertEqual(mapped,173)
        self.assertEqual(mapped,self.current_matrix['reader_audit']['all_populated_mapped_column_count'])
        self.assertEqual(self.current_matrix['reader_audit']['all_populated_unmapped_column_count'],34)
        self.assertEqual(len(case.activities),4)
        for activity,city_index in zip(case.activities,(82,89,96,103)):
            self.assertEqual(activity.city,self.current_values[city_index])

    def test_current_matrix_does_not_omit_newly_mapped_source_columns(self):
        observed = set()
        def walk(value):
            if is_dataclass(value):
                for field in fields(value):
                    if field.name not in {'raw_response', 'source_headers', 'review_changes'}:
                        walk(getattr(value, field.name))
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, str) and value.startswith('SYNTHETIC_C'):
                observed.add(int(value[-3:]))
        walk(self.read_current_case())
        expected = {r['csv_index'] for r in self.current_matrix['source_fields']
                    if r['reader_observation']['actual_targets']}
        self.assertEqual(observed, expected)

    def test_new_family_fields_remain_raw_without_guessed_roles(self):
        case=self.read_current_case()
        self.assertEqual(sum(map(len,case.raw_response.values())),207)
        self.assertEqual(case.raw_response['Nome completo do filho'],[self.current_values[i] for i in (123,132,141,150)])
        self.assertEqual(case.raw_response['Nome completo do filho(a).'],[self.current_values[159]])
        self.assertEqual(case.raw_response[self.current_headers[111]],[self.current_values[111]])
        self.assertEqual(case.raw_response[self.current_headers[119]],[self.current_values[119]])
        self.assertEqual(case.family.parents[0].source_role, 'parent')
        self.assertEqual(case.family.children[0].full_name, self.current_values[123])
        self.assertEqual(case.identity.family_name,'')
        self.assertEqual(case.identity.given_names,'')
        self.assertEqual(case.identity.sex,'')

    def test_current_residence_start_header_must_be_recognized(self):
        self.assertEqual(self.read_current_case({11:'01/01/2020'}).identity.residence_since,'01/01/2020')

    def test_current_education_level_header_must_be_recognized(self):
        self.assertEqual(self.read_current_case({64:'Ensino superior'}).education.level,'Ensino superior')

    def test_current_source_rows_do_not_claim_pdf_question_indexes(self):
        rows=self.current_matrix['source_fields']
        self.assertEqual([r['csv_index'] for r in rows],list(range(207)))
        for row in rows:
            self.assertNotIn('question_number',row)
            self.assertEqual(row['source_header'],self.current_headers[row['csv_index']])
            for form in self.current_matrix['templates']:
                for key in row[form+'_target']:
                    self.assertIn(key,self.current_matrix['target_catalog'])
        self.assertEqual(rows[30]['proposed_CanadaCase_target'],'identity.language_test')
        self.assertEqual(rows[38]['proposed_CanadaCase_target'],'passport.identity_country')
        self.assertEqual(rows[11]['reader_observation']['classification'],'mapped')
        self.assertEqual(rows[64]['reader_observation']['classification'],'mapped')

    def test_newly_collected_intake_gaps_are_not_reported_as_absent(self):
        gaps={g['id']:g for g in self.current_matrix['intake_gaps']}
        self.assertEqual(gaps['identity_country']['status'],'missing_from_model')
        self.assertEqual(gaps['identity_country']['verified_csv_indices'],[38])
        self.assertEqual(gaps['language_test']['status'],'conditional')
        self.assertEqual(gaps['language_test']['verified_csv_indices'],[30])
        self.assertEqual(gaps['current_spouse_details']['verified_csv_indices'],[18,19,8])

    def test_archive_and_latest_layouts_are_distinct_and_kept_separate(self):
        archived_schema=json.loads((FIXTURES/'canada_archive_csv_schema.json').read_text(encoding='utf-8'))
        archived_headers=[c['header'] for c in archived_schema['columns']]
        self.assertEqual(sum(a!=b for a,b in zip(archived_headers,self.current_headers)),63)
        self.assertNotEqual(archived_schema['header_sha256'],self.current_schema['header_sha256'])
        self.assertEqual(archived_headers[19],self.current_headers[8])
        self.assertEqual(archived_headers[10],self.current_headers[11])
        self.assertEqual(self.current_matrix['source_fields'][8]['archive_csv_index'],19)
        self.assertEqual(self.current_matrix['source_fields'][11]['archive_csv_index'],10)
        archived=read_google_forms_csv(FIXTURES/'canada_archive_csv_synthetic.csv')[0]
        self.assertEqual(sum(map(len,archived.raw_response.values())),207)
        self.assertEqual(len(archived.activities),4)
        self.assertEqual(len(archived.raw_response['Nome completo do filho(a).']),5)
        self.assertEqual(len(archived.raw_response[archived_headers[111]]),2)
        self.assertEqual(archived.identity.residence_since,'SYNTHETIC_C010')
        self.assertEqual(archived.education.level,'SYNTHETIC_C064')
        with (FIXTURES/'canada_archive_csv_synthetic.csv').open(encoding='utf-8',newline='') as f:
            headers,values=list(csv.reader(f))
        self.assertEqual(headers,archived_headers)
        self.assertEqual(values,[f'SYNTHETIC_C{i:03}' for i in range(207)])


if __name__ == '__main__':
    unittest.main()
