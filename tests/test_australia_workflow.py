from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from australia.models import ApplicantData
from australia.workflow import AustraliaWorkflow


class AustraliaWorkflowValidationTests(unittest.TestCase):

    def setUp(self):
        self.workflow = AustraliaWorkflow()

    def test_complete_address_has_no_address_issues(self):
        applicant = ApplicantData(
            residential_address="Rua Teste 10",
            city="Brasilia",
            state="DF",
            postcode="71930-000",
        )

        self.assertEqual(
            self.workflow.validation_issues(applicant),
            [],
        )

    def test_missing_structured_address_fields_are_reported(self):
        applicant = ApplicantData(
            residential_address="SQNW 303 Bloco A apto 503",
        )

        issues = self.workflow.validation_issues(applicant)

        self.assertIn("City is missing", issues)
        self.assertIn("State is missing", issues)
        self.assertIn("Postcode / CEP is missing", issues)

    def test_postcode_only_is_not_accepted_as_full_address(self):
        applicant = ApplicantData(
            residential_address="71930000",
            postcode="71930-000",
        )

        issues = self.workflow.validation_issues(applicant)

        self.assertIn(
            "Residential address contains only a postcode / CEP",
            issues,
        )

    def test_formatted_postcodes_are_not_full_addresses(self):
        for address in ("71930-000", "71.930-000", "CEP 71930-000", "cep: 71930000"):
            with self.subTest(address=address):
                applicant = ApplicantData(residential_address=address)
                self.assertIn(
                    "Residential address contains only a postcode / CEP",
                    self.workflow.validation_issues(applicant),
                )

    def test_street_with_postcode_is_not_postcode_only(self):
        applicant = ApplicantData(residential_address="Rua Teste, CEP 71930-000")
        self.assertNotIn(
            "Residential address contains only a postcode / CEP",
            self.workflow.validation_issues(applicant),
        )


if __name__ == "__main__":
    unittest.main()
