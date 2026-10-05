from __future__ import annotations
import argparse
from datetime import date
from pathlib import Path

from models import RecipientData
from settings import load_settings
from workflows import get_workflow


def main():
    p = argparse.ArgumentParser(description="Generate Form 956A from a Google Forms response.")
    p.add_argument("source", help="Google Forms CSV or supported PDF export")
    p.add_argument("output", help="Output 956A PDF")
    p.add_argument("--row", type=int, default=1, help="1-based CSV row number (default 1)")
    p.add_argument("--title", choices=["Mr","Mrs","Miss","Ms","Other"], required=True)
    p.add_argument("--title-other", default="")
    p.add_argument("--cid", default="")
    p.add_argument("--rid", default="")
    p.add_argument("--trn", default="")
    p.add_argument("--date-lodged", default=date.today().strftime("%d/%m/%Y"))
    args = p.parse_args()

    settings = load_settings()
    country = settings.get("default_client_country", "BRAZIL")
    workflow = get_workflow("australia")
    src = Path(args.source)

    rows = workflow.read_source(src, country)

    if src.suffix.lower() == ".csv":
        if args.row < 1 or args.row > len(rows):
            raise SystemExit(f"CSV has {len(rows)} response rows; --row must be 1..{len(rows)}")
        applicant = rows[args.row - 1]
    else:
        applicant = rows[0]
    applicant.title = args.title
    applicant.title_other = args.title_other
    applicant.cid = args.cid
    applicant.rid = args.rid
    applicant.trn = args.trn
    applicant.date_lodged = args.date_lodged
    recipient = RecipientData(**settings.get("recipient", {}))
    out = workflow.generate(applicant, recipient, args.output)
    print(out)


if __name__ == "__main__":
    main()
