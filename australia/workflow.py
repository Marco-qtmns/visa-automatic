from __future__ import annotations

from pathlib import Path
import re

from .models import ApplicantData, RecipientData
from .source_readers import read_google_forms_csv, read_google_forms_pdf
from .form956a import generate_956a


class AustraliaWorkflow:
    key = "australia"
    display_name = "Australia"

    def read_source(
        self,
        path: str | Path,
        default_country: str = "BRAZIL",
    ) -> list[ApplicantData]:
        path = Path(path)

        if path.suffix.lower() == ".csv":
            return read_google_forms_csv(path, default_country)

        if path.suffix.lower() == ".pdf":
            return [read_google_forms_pdf(path, default_country)]

        raise ValueError("Unsupported file type.")

    def validation_issues(
        self,
        applicant: ApplicantData,
    ) -> list[str]:
        issues: list[str] = []

        address = str(applicant.residential_address or "").strip()
        city = str(applicant.city or "").strip()
        state = str(applicant.state or "").strip()
        postcode = str(applicant.postcode or "").strip()

        if not address:
            issues.append("Residential address is missing")

        if not city:
            issues.append("City is missing")

        if not state:
            issues.append("State is missing")

        if not postcode:
            issues.append("Postcode / CEP is missing")

        # A CEP alone is not a usable residential address.
        if re.fullmatch(r"(?:CEP\s*:?\s*)?\d{2}\.?\d{3}\s*-?\s*\d{3}", address, re.IGNORECASE):
            issues.append(
                "Residential address contains only a postcode / CEP"
            )

        return issues

    def generate(
        self,
        applicant: ApplicantData,
        recipient: RecipientData,
        output_path: str | Path,
    ) -> Path:
        return generate_956a(applicant, recipient, output_path)
