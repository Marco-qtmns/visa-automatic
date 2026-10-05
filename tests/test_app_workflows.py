"""Exercise country routing without opening Tk windows or storing client data."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
from australia.models import ApplicantData
from canada.models import CanadaCase, IdentityData
from workflows import get_workflow


class AppWorkflowTests(unittest.TestCase):
    def test_country_switch_hides_australia_controls_and_preserves_applicant(self):
        applicant = ApplicantData(family_name="EXAMPLE")
        ui = SimpleNamespace(
            destination=Mock(), australia_panel=Mock(), canada_panel=Mock(),
            source_hint=Mock(), status=Mock(), status_label=Mock(), applicant=applicant,
        )
        ui.destination.get.return_value = "Canada"
        App.on_destination_changed(ui)
        self.assertEqual(ui.workflow.key, "canada")
        ui.australia_panel.pack_forget.assert_called_once()
        ui.canada_panel.pack.assert_called_once()
        ui.destination.get.return_value = "Australia"
        App.on_destination_changed(ui)
        self.assertEqual(ui.workflow.key, "australia")
        ui.canada_panel.pack_forget.assert_called_once()
        ui.australia_panel.pack.assert_called_once()
        self.assertIs(ui.applicant, applicant)

    def test_multiple_canada_rows_route_selected_case_to_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "canada.csv"
            source.write_text('Nome completo,Data de nascimento\n', encoding='utf-8')
            first = CanadaCase(identity=IdentityData(full_name="FIRST"))
            selected = CanadaCase(identity=IdentityData(full_name="SECOND"))
            applicant = ApplicantData(family_name="AUSTRALIA")
            ui = SimpleNamespace(
                source_path=Mock(), settings_data={}, workflow=Mock(key="canada"),
                select_csv_row=Mock(return_value=selected), show_canada_review=Mock(),
                status=Mock(), applicant=applicant, _load_applicant_to_ui=Mock(),
            )
            ui.source_path.get.return_value = str(source)
            ui.workflow.read_source.return_value = [first, selected]
            with patch('app.messagebox.showerror') as error:
                App.read_source(ui)
            error.assert_not_called()
            self.assertIs(ui.canada_case, selected)
            self.assertIs(ui.applicant, applicant)
            ui._load_applicant_to_ui.assert_not_called()
            ui.select_csv_row.assert_called_once_with([first, selected])
            ui.show_canada_review.assert_called_once_with(selected)
            self.assertIn('validation issue', ui.status.set.call_args.args[0])

    def test_canada_generation_routes_to_drafts_without_australia_conversion(self):
        ui = SimpleNamespace(workflow=Mock(key='canada'), canada_case=CanadaCase(),
                             _ui_to_applicant=Mock(), status=Mock())
        ui.workflow.generate.return_value = {'populated_fields_not_exported':['history.travel_details']}
        with tempfile.TemporaryDirectory() as folder, patch('app.filedialog.askdirectory', return_value=folder), patch('app.messagebox.showinfo') as info:
            App.generate(ui)
        ui.workflow.generate.assert_called_once()
        self.assertIs(ui.workflow.generate.call_args.args[0],ui.canada_case)
        self.assertIn('not ready for submission', info.call_args.args[1])
        ui._ui_to_applicant.assert_not_called()

    def test_canada_generation_cancel_does_not_export(self):
        ui = SimpleNamespace(workflow=Mock(key='canada'), canada_case=CanadaCase())
        with patch('app.filedialog.askdirectory',return_value=''):
            App.generate(ui)
        ui.workflow.generate.assert_not_called()

    def test_review_can_be_reopened(self):
        case = CanadaCase()
        ui = SimpleNamespace(canada_case=case, show_canada_review=Mock())
        App.review_canada(ui)
        ui.show_canada_review.assert_called_once_with(case)


if __name__ == '__main__':
    unittest.main()
