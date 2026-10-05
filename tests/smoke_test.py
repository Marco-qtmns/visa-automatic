from pathlib import Path
import sys
import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import ApplicantData, RecipientData
from form956a import generate_956a


applicant = ApplicantData(
    family_name="EXAMPLE",
    given_names="SYNTHETIC",
    date_of_birth="01/01/2000",
    residential_address="Rua Exemplo, 1 - apt 101 - 00000-000",
    country="BRAZIL",
    mobile="00900000000",
    marital_status="Solteiro",
    title="Miss",
    date_lodged="24/08/2026",
)
recipient = RecipientData(
    title="Mrs", family_name="TEST RECIPIENT", given_names="EXAMPLE",
    date_of_birth="02/03/1990", address_line1="RUA FICTÍCIA 100",
    address_line2="EDIFÍCIO TESTE - SALA 2", address_line3="CIDADE TESTE - DF - BRAZIL", postcode="00000000",
    office_country_code="55", office_area_code="61", office_number="900000000",
    mobile="+5511900000000", email="recipient@example.invalid",
)
out = ROOT / "tests" / "_smoke_output.pdf"
generate_956a(applicant, recipient, out, ROOT / "templates" / "australia" / "FORM_956A.pdf")
assert out.exists() and out.stat().st_size > 10000
print(out)


# Regression checks for fields that previously caused problems.
doc = fitz.open(out)
fields = {}

try:
    for page in doc:
        for widget in page.widgets() or []:
            if widget.field_name and widget.field_name not in fields:
                fields[widget.field_name] = widget.field_value
finally:
    doc.close()

# Q7
assert fields["ap.resadd str"] == "RUA EXEMPLO, 1 - APT 101"
assert fields["ap.resadd cntry"] == "BRAZIL"
assert fields["ap.resadd pc"] == "00000-000"

# Q12
assert fields["ap.type"] == "VISITOR VISA - SUBCLASS 600"

# Q16
assert fields["ar.resadd str"] == "RUA FICTÍCIA 100"
assert fields["ar.resadd sub"] == "EDIFÍCIO TESTE - SALA 2"
assert fields["ar.resadd cntry"] == "CIDADE TESTE - DF - BRAZIL"
assert fields["ar.resadd pc"] == "00000000"

# Q28 / Q29
from datetime import date
from form956a import _format_pdf_date
assert fields["ar.dec date"] == _format_pdf_date(date.today().strftime("%d/%m/%Y"))
assert fields["ap.dec date"] == fields["ar.dec date"]

print("Field regression checks OK")
