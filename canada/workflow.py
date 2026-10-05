from __future__ import annotations

from pathlib import Path

from .models import CanadaCase
from .source_readers import read_google_forms_csv


class CanadaWorkflow:
    key = "canada"
    display_name = "Canada"

    def read_source(
        self,
        path: str | Path,
        default_country: str = "BRAZIL",
    ) -> list[CanadaCase]:
        path = Path(path)

        if path.suffix.lower() == ".csv":
            from .preparation import prepare_case
            return [prepare_case(case) for case in read_google_forms_csv(path)]
        if path.name.endswith(".canada-case.json"):
            from .case_store import load_case
            from .preparation import prepare_case
            return [prepare_case(load_case(path))]

        raise ValueError(
            "Canada supports Google Forms CSV or .canada-case.json files."
        )

    def generate(self, case, output_dir):
        from .pdf_drafts import generate_drafts
        return generate_drafts(case, output_dir)
