from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from canada.models import CanadaCase
from canada.representative_store import save_profile, load_profile_into_case


class RepresentativeProfileTests(unittest.TestCase):
    def test_reusable_details_exclude_case_action_and_old_representative(self):
        source = CanadaCase()
        source.representative.family_name = 'EXAMPLE'
        source.representative.email = 'representative@example.test'
        source.representative.category = 'Unpaid - other'
        source.representative.other_category_details = 'SYNTHETIC'
        source.representative.action = 'Cancel and appoint a new representative'
        source.representative.cancelled_family_name = 'PRIVATE OLD REP'
        target = CanadaCase()
        target.identity.family_name = 'CLIENT'
        target.raw_response = {'E-mail':['client@example.test']}
        target.representative.action = 'Update representative contact information'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'example.canada-representative.json'
            save_profile(source.representative,path)
            text = path.read_text()
            self.assertNotIn('PRIVATE OLD REP',text)
            self.assertNotIn('Cancel and appoint',text)
            self.assertNotIn('action',json.loads(text)['representative'])
            changes = load_profile_into_case(target,path)
        self.assertEqual(target.representative.family_name,'EXAMPLE')
        self.assertEqual(target.representative.category,'Unpaid - other')
        self.assertEqual(target.representative.action,'Update representative contact information')
        self.assertEqual(target.representative.cancelled_family_name,'')
        self.assertEqual(target.identity.family_name,'CLIENT')
        self.assertEqual(target.raw_response,{'E-mail':['client@example.test']})
        self.assertTrue(changes)
        self.assertTrue(all(c.path.startswith('representative.') for c in changes))

    def test_malformed_profile_does_not_partially_update_case(self):
        case = CanadaCase()
        before = deepcopy(case)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'example.canada-representative.json'
            save_profile(case.representative,path)
            document = json.loads(path.read_text())
            document['representative']['family_name']='MUST NOT APPLY'
            document['representative']['category']='guessed category'
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                load_profile_into_case(case,path)
        self.assertEqual(case,before)

    def test_profile_cannot_overwrite_csv_or_case(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('source.csv','source.canada-case.json'):
                path=Path(folder)/name
                path.write_text('original')
                with self.assertRaises(ValueError):
                    save_profile(CanadaCase().representative,path)
                self.assertEqual(path.read_text(),'original')


if __name__ == '__main__':
    unittest.main()
