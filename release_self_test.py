"""Diagnostics run inside the packaged application, using temporary data only."""
from datetime import date
import json
from pathlib import Path
import tempfile
import traceback


def run(report_path: str, app_class) -> int:
    report = {"ok": False, "checks": []}
    try:
        import fitz
        import settings
        from form956a import generate_956a, resource_path, _format_pdf_date
        from models import ApplicantData, RecipientData

        report["version"] = resource_path("VERSION.txt").read_text().strip()
        with tempfile.TemporaryDirectory(prefix="956a-self-test-") as tmp:
            original = settings.settings_path
            settings.settings_path = lambda: Path(tmp) / "settings.json"
            try:
                assert not any(settings.load_settings()["recipient"].values())
                report["checks"].append("empty_recipient_defaults")
                for version in (0, 1, 2, 3, 4, 5):
                    settings.settings_path().write_text(json.dumps({
                        "settings_version": version,
                        "recipient": {"address_line1": "TEST ADDRESS", "office_number": ""},
                    }))
                    recipient = settings.load_settings()["recipient"]
                    assert recipient["address_line1"] == "TEST ADDRESS"
                    assert recipient["office_number"] == ""
                    assert not any(value for key, value in recipient.items()
                                   if key != "address_line1")
                report["checks"].append("legacy_settings_preserved")
                settings.save_settings(settings.default_settings())
                app = app_class()
                app.withdraw()
                try:
                    app.update_idletasks()
                    assert {"city", "state", "postcode"} <= app.vars.keys()
                    assert not any(app.settings_data["recipient"].values())
                finally:
                    app.destroy()
                report["checks"].append("tkinter_startup")

                applicant = ApplicantData(family_name="TEST", given_names="CLIENT",
                    date_of_birth="01/01/2000", title="Ms", date_lodged="01/01/2026",
                    residential_address="RUA TESTE 10", city="TEST CITY", state="DF",
                    postcode="12345678", mobile="11900000000")
                recipient = RecipientData(title="Ms", family_name="TEST", given_names="RECIPIENT",
                    date_of_birth="01/01/1990", address_line1="TEST ADDRESS",
                    email="recipient@example.invalid")
                output = generate_956a(applicant, recipient, Path(tmp) / "test.pdf")
                with fitz.open(output) as doc:
                    fields = {w.field_name: w.field_value for page in doc
                              for w in page.widgets() or [] if w.field_type_string == "Text"}
                assert fields["ap.resadd pc"] == "12345-678"
                assert "TEST CITY" in fields["ap.resadd str"] + fields["ap.resadd sub"]
                assert fields["ap.type"] == "VISITOR VISA - SUBCLASS 600"
                today = _format_pdf_date(date.today().strftime("%d/%m/%Y"))
                assert fields["ap.dec date"] == fields["ar.dec date"] == today
                report["checks"].append("bundled_template_pdf_generation")
                from canada.models import CanadaCase, Activity
                from canada.pdf_drafts import generate_drafts
                case = CanadaCase()
                case.identity.family_name = "EXAMPLE"
                case.identity.given_names = "Synthetic"
                case.activities = [Activity(position=f'Synthetic activity {i}',start_date='2020-01',
                    end_date='2021-01',ongoing_answer='No') for i in range(4)]
                drafts = generate_drafts(case, Path(tmp) / "canada-drafts")
                assert set(drafts['forms']) == {'IMM5257', 'IMM5707', 'IMM5476'}
                assert not drafts['submission_ready']
                assert drafts['continuation']['activity_count'] == 1
                with fitz.open(Path(tmp) / 'canada-drafts/IMM5257-CONTINUATION-DRAFT.pdf') as supplement:
                    assert 'Synthetic activity 3' in ''.join(page.get_text() for page in supplement)
                report['checks'].append('bundled_canada_xfa_drafts')
            finally:
                settings.settings_path = original
        report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
