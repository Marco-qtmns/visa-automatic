from pathlib import Path
import csv
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canada.source_readers import read_google_forms_csv, canada_case_from_csv_row, CsvResponseRow


class CanadaImportTests(unittest.TestCase):

    def test_canada_csv_preserves_duplicate_activity_columns(self):
        headers = [
            "Nome completo, conforme o passaporte",
            "Data de nascimento",
            "Número do passaporte",
            "Cidade",
            "Tipo de atividade",
            "Data de início",
            "Data de término",
            "Cargo",
            "Nome da empresa, empregador ou instituição",
            "Cidade",
            "Tipo de atividade",
            "Data de início",
            "Data de término",
            "Cargo",
            "Nome da empresa, empregador ou instituição",
            "Cidade",
        ]

        values = [
            "TEST CLIENT",
            "01/02/2000",
            "AA123456",
            "Brasilia",
            "Emprego",
            "01/01/2024",
            "24/09/2026",
            "Analista",
            "Empresa A",
            "Brasilia",
            "Estudante",
            "01/01/2022",
            "31/12/2023",
            "Estudante",
            "Universidade B",
            "Sao Paulo",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "canada.csv"

            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerow(values)

            cases = [canada_case_from_csv_row(CsvResponseRow(headers, values))]

        self.assertEqual(len(cases), 1)

        case = cases[0]

        self.assertEqual(case.identity.full_name, "TEST CLIENT")
        self.assertEqual(case.identity.date_of_birth, "01/02/2000")
        self.assertEqual(case.passport.number, "AA123456")
        self.assertEqual(case.contact.city, "Brasilia")

        self.assertEqual(len(case.activities), 2)

        self.assertEqual(case.activities[0].activity_type, "Emprego")
        self.assertEqual(case.activities[0].organization, "Empresa A")
        self.assertEqual(case.activities[0].city, "Brasilia")

        self.assertEqual(case.activities[1].activity_type, "Estudante")
        self.assertEqual(case.activities[1].organization, "Universidade B")
        self.assertEqual(case.activities[1].city, "Sao Paulo")

    def test_full_name_is_not_guessed_into_surname_and_given_names(self):
        headers = [
            "Nome completo, conforme o passaporte",
            "Número do passaporte",
        ]

        values = [
            "MARIA DE SOUZA SILVA",
            "AA123456",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "canada.csv"

            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerow(values)

            case = canada_case_from_csv_row(CsvResponseRow(headers, values))

        self.assertEqual(case.identity.full_name, "MARIA DE SOUZA SILVA")
        self.assertEqual(case.identity.family_name, "")
        self.assertEqual(case.identity.given_names, "")

        issues = case.validation_issues()

        self.assertTrue(any("identity.family_name" in issue for issue in issues))
        self.assertTrue(any("identity.given_names" in issue for issue in issues))


class CanadaWorkflowTests(unittest.TestCase):

    def test_canada_workflow_reads_csv(self):
        from canada.workflow import CanadaWorkflow

        headers = [
            "Nome completo, conforme o passaporte",
            "Data de nascimento",
            "Número do passaporte",
        ]

        values = [
            "TEST CLIENT",
            "01/02/2000",
            "AA123456",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "canada.csv"

            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerow(values)

            with self.assertRaisesRegex(ValueError, 'CSV_SCHEMA_MISMATCH'):
                CanadaWorkflow().read_source(path)
            cases = CanadaWorkflow().read_source(Path(__file__).parent / 'fixtures/canada_20260929_synthetic.csv')

        self.assertEqual(len(cases), 1)
        self.assertTrue(cases[0].identity.family_name)
        self.assertTrue(cases[0].passport.number)

    def test_canada_workflow_rejects_pdf_for_now(self):
        from canada.workflow import CanadaWorkflow

        with self.assertRaises(ValueError):
            CanadaWorkflow().read_source("example.pdf")


if __name__ == "__main__":
    unittest.main()
