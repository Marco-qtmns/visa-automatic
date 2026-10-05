from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from canada.models import CanadaCase, FamilyMember
from canada.review import ReviewSession, editable_fields
from canada.source_readers import read_google_forms_csv
from app import App


class ReviewTests(unittest.TestCase):
    def case(self):
        return read_google_forms_csv(Path(__file__).parent / 'fixtures/canada_csv_synthetic.csv')[0]

    def test_cancel_and_preview_do_not_mutate_case(self):
        case = self.case()
        original = deepcopy(case)
        session = ReviewSession(case)
        session.set_value('identity.family_name', 'EXAMPLE')
        self.assertEqual(session.preview().identity.family_name, 'EXAMPLE')
        self.assertEqual(case, original)

    def test_apply_logs_changes_and_preserves_all_raw_answers(self):
        case = self.case()
        raw = deepcopy(case.raw_response)
        session = ReviewSession(case)
        session.set_value('identity.family_name', 'EXAMPLE')
        session.set_value('family.parents[0].confirmed_role', 'mother')
        session.set_value('contact.address', 'Line one\nLine two')
        changes = session.apply()
        self.assertEqual(len(changes), 3)
        self.assertEqual(case.raw_response, raw)
        self.assertEqual(case.family.parents[0].source_role, 'parent')
        self.assertEqual(case.family.parents[0].confirmed_role, 'mother')
        self.assertEqual(case.contact.address, 'Line one\nLine two')
        self.assertEqual(changes[0].previous_value, '')
        self.assertEqual(changes[0].corrected_value, 'EXAMPLE')
        self.assertTrue(changes[0].reviewed_at)
        self.assertEqual(session.apply(), [])
        self.assertEqual(len(case.review_changes), 3)

    def test_reopen_keeps_corrections_and_records_later_clearing(self):
        case = self.case()
        first = ReviewSession(case)
        first.set_value('identity.family_name', 'EXAMPLE')
        first.apply()
        second = ReviewSession(case)
        self.assertEqual(second.values['identity.family_name'], 'EXAMPLE')
        second.set_value('identity.family_name', '')
        second.apply()
        self.assertEqual(case.review_changes[-1].previous_value, 'EXAMPLE')
        self.assertEqual(case.identity.family_name, '')

    def test_provenance_paths_and_invalid_roles_are_rejected(self):
        session = ReviewSession(self.case())
        for path in ('raw_response', 'source_email', 'family.parents[0].source_role',
                     'family.parents[0].source_block_index', 'review_changes', '__dict__'):
            with self.assertRaises(ValueError):
                session.set_value(path, 'changed')
        with self.assertRaises(ValueError):
            session.set_value('family.parents[0].confirmed_role', 'guessed mother')
        with self.assertRaises(ValueError):
            session.set_value('identity.family_name', None)

    def test_conflicting_review_cannot_overwrite_newer_changes(self):
        case = self.case()
        old = ReviewSession(case)
        newer = ReviewSession(case)
        newer.set_value('identity.family_name', 'NEWER')
        newer.apply()
        old.set_value('identity.family_name', 'OLDER')
        with self.assertRaisesRegex(ValueError, 'changed'):
            old.apply()
        self.assertEqual(case.identity.family_name, 'NEWER')

    def test_missing_manual_fields_are_not_inferred_and_issues_resolve(self):
        case = CanadaCase()
        case.family.parents = [FamilyMember(full_name='Synthetic Name', source_block_index=1)]
        session = ReviewSession(case)
        for path in ('identity.family_name', 'identity.given_names', 'identity.birth_country',
                     'family.parents[0].family_name', 'family.parents[0].given_names',
                     'family.parents[0].birth_country', 'family.parents[0].confirmed_role'):
            self.assertEqual(session.values[path], '')
        self.assertTrue(any('Parent block 1' in s for s in case.validation_issues()))
        for field, value in {'family_name':'Example', 'given_names':'Person',
                             'birth_country':'Brazil', 'confirmed_role':'mother'}.items():
            session.set_value('family.parents[0].' + field, value)
        self.assertFalse(any('Parent block 1' in s for s in session.preview().validation_issues()))
        self.assertTrue(any('Parent block 1' in s for s in case.validation_issues()))

    def test_empty_case_and_blank_family_slots_can_be_reviewed(self):
        case = self.case()
        case.family.children[1] = FamilyMember(source_block_index=2, source_role='child')
        fields = editable_fields(case)
        self.assertIn('family.children[1].family_name', fields)
        self.assertEqual(ReviewSession(CanadaCase()).apply(), [])

    def test_app_uses_editor_and_refreshes_status(self):
        ui = SimpleNamespace(status=Mock())
        case = self.case()
        with patch('canada.review_ui.show_review') as editor:
            App.show_canada_review(ui, case)
        editor.assert_called_once_with(ui, case)
        self.assertIn('validation issue', ui.status.set.call_args.args[0])

    def run_editor(self, accept, add_child=False, compact_answer=False, finance_task=False):
        from canada.review_ui import show_review
        case = self.case()
        from canada.preparation import prepare_case
        prepare_case(case)
        original = deepcopy(case)
        parent = Mock()
        tree = Mock()
        tree.get_children.return_value = ()
        history_tree = Mock()
        history_tree.get_children.return_value = ()
        history_tree.selection.return_value = ()
        issue_tree=Mock(get_children=Mock(return_value=[]))
        editor = Mock()
        editor.get.return_value = 'MANUALLY CONFIRMED'
        buttons = {}
        def button(*args, **kwargs):
            buttons[kwargs['text']] = kwargs['command']
            return Mock()
        def interact(win):
            tree.selection.return_value = ('identity.family_name',)
            tree.bind.call_args.args[1]()
            self.assertEqual(case, original)
            if compact_answer:
                from canada.compact_review import QUESTIONS
                variables[list(QUESTIONS).index('identity.sex')].set('Female')
            if add_child:
                tree.selection.return_value = ()
                buttons['Add child']()
            finish=buttons['Apply corrections (session)' if accept else 'Cancel']
            if finance_task:
                from canada.review_tasks import review_tasks
                index=next(i for i,t in enumerate(review_tasks(original)) if t.id=='finances')
                issue_tree.selection.return_value=('task:'+str(index),)
                buttons['Open review task']()
                buttons['Save to review draft']()
                self.assertEqual(case,original)
            finish()
        parent.wait_window.side_effect = interact
        variables=[]
        class FakeVar:
            def __init__(self, value='', **kwargs):
                self.value=value
                self.callbacks=[]
                variables.append(self)
            def get(self): return self.value
            def set(self,value):
                self.value=value
                for callback in self.callbacks: callback()
            def trace_add(self,mode,callback): self.callbacks.append(callback)
        with patch('canada.review_ui.tk.Toplevel'), \
             patch('canada.review_ui.tk.Canvas'), patch('canada.review_ui.tk.StringVar', FakeVar), \
             patch('canada.review_ui.ttk.Entry'), \
             patch('canada.review_ui.ttk.Frame'), patch('canada.review_ui.ttk.Label'), \
             patch('canada.review_ui.ttk.Notebook'), patch('canada.review_ui.ttk.Scrollbar'), \
             patch('canada.review_ui.ttk.Combobox'), \
             patch('canada.review_ui.ttk.Treeview', side_effect=[tree,history_tree,issue_tree]), \
             patch('canada.review_ui.tk.Text', side_effect=[editor, Mock(), Mock(), Mock(), Mock(), Mock(), Mock(get=Mock(return_value='5000')), Mock(get=Mock(return_value='Synthetic bank statement'))]), \
             patch('canada.review_ui.ttk.Button', side_effect=button):
            show_review(parent, case)
        return case, original

    def test_grouped_finance_dialog_apply_and_main_cancel(self):
        case,_=self.run_editor(True,finance_task=True)
        self.assertEqual(case.trip.available_funds_cad,'5000')
        self.assertEqual(case.trip.funds_source_reference,'Synthetic bank statement')
        case,original=self.run_editor(False,finance_task=True)
        self.assertEqual(case,original)

    def test_compact_official_answer_applies_and_cancel_discards(self):
        case,original=self.run_editor(True,compact_answer=True)
        self.assertEqual(case.identity.sex,'Female')
        case,original=self.run_editor(False,compact_answer=True)
        self.assertEqual(case,original)

    def test_editor_apply_flushes_active_field_without_selection_change(self):
        case, _ = self.run_editor(True)
        self.assertEqual(case.identity.family_name, 'MANUALLY CONFIRMED')
        self.assertEqual(len(case.review_changes), 1)

    def test_editor_cancel_does_not_apply_active_field(self):
        case, original = self.run_editor(False)
        self.assertEqual(case, original)

    def test_editor_can_add_whatsapp_child_and_apply_or_cancel(self):
        case, original = self.run_editor(True, add_child=True)
        self.assertEqual(len(case.family.children), len(original.family.children) + 1)
        self.assertEqual(case.identity.family_name, 'MANUALLY CONFIRMED')
        case, original = self.run_editor(False, add_child=True)
        self.assertEqual(case, original)

    def test_verified_case_documents_and_declaration_do_not_break_editor(self):
        case = read_google_forms_csv(Path(__file__).parent / 'fixtures/canada_20260929_synthetic.csv')[0]
        with patch.object(self, 'case', return_value=case):
            edited, original = self.run_editor(True)
        self.assertEqual(edited.declaration_acceptance, original.declaration_acceptance)
        self.assertEqual(edited.documents, original.documents)
        self.assertNotIn('declaration_acceptance', editable_fields(edited))
        self.assertNotIn('documents[0].category', editable_fields(edited))
