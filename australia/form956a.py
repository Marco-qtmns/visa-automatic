from __future__ import annotations
from datetime import date
import re
import sys
from pathlib import Path

import pymupdf as fitz

from .models import ApplicantData, RecipientData


TITLE_STATE = {"Mr": "mr", "Mrs": "mrs", "Miss": "miss", "Ms": "ms"}


def _format_pdf_date(value: str) -> str:
    """Convert common numeric dates to the 956A field format dd-mmm-yyyy in English."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw)
    if not m:
        return raw
    day, month, year = map(int, m.groups())
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return raw
    return f"{day:02d}-{months[month-1]}-{year:04d}"


def resource_path(relative: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    return base / relative


def template_path() -> Path:
    return resource_path("templates/australia/FORM_956A.pdf")


def _postcode_from_address(address: str) -> tuple[str, str]:
    # Brazil CEP: 12345-678 or 12345678. Keep other postal formats untouched/unknown.
    m = re.search(r"(?<!\d)(\d{5})-?(\d{3})(?!\d)", address or "")
    if not m:
        return (address.strip(), "")
    pc = f"{m.group(1)}-{m.group(2)}"
    clean = (address[:m.start()] + address[m.end():]).strip(" ,;-\n")
    clean = re.sub(r"\s{2,}", " ", clean)
    return clean, pc


def _split_address(address: str, country: str) -> tuple[str, str, str, str]:
    """Prepare Q7 applicant address: two address lines, country line, postcode."""
    clean, pc = _postcode_from_address(address)
    clean = re.sub(r"\s+", " ", clean).strip(" ,;-\n")

    country_key = re.sub(r"\s+", " ", str(country or "")).strip().upper()
    country_line = "BRAZIL" if country_key in {"BRAZIL", "BRASIL"} else country_key

    if not clean:
        return "", "", country_line, pc

    max_len = 45

    if len(clean) <= max_len:
        return clean.upper(), "", country_line, pc

    # Prefer a natural split before the PDF field becomes too long.
    candidates = [
        clean.rfind(", ", 0, max_len + 1),
        clean.rfind(" - ", 0, max_len + 1),
        clean.rfind("; ", 0, max_len + 1),
    ]

    split_at = max(candidates)

    if split_at < 15:
        split_at = clean.rfind(" ", 0, max_len + 1)

    if split_at < 15:
        split_at = max_len

    line1 = clean[:split_at].strip(" ,;-")
    line2 = clean[split_at:].strip(" ,;-")

    return line1.upper(), line2.upper(), country_line, pc


def _split_brazil_phone(phone: str) -> tuple[str, str, str]:
    """Split a Brazilian phone into 956A Q9 parts.

    Examples:
      00900000000       -> ("55", "00", "900000000")
      +55 11 900000000  -> ("55", "11", "900000000")
    """
    digits = re.sub(r"\D", "", str(phone or ""))

    if not digits:
        return "", "", ""

    # Remove Brazilian country code if the input already contains +55 / 55.
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]

    # Brazil: 2-digit area code + 8 or 9-digit local number.
    if len(digits) not in (10, 11):
        raise ValueError(
            f"Invalid Brazilian phone number: {phone!r}. "
            "Expected 10 or 11 national digits "
            "(2-digit area code + phone number), optionally prefixed by +55."
        )

    return "55", digits[:2], digits[2:]


def _set_fields(doc: fitz.Document, values: dict[str, str]) -> None:
    for page in doc:
        for widget in page.widgets() or []:
            name = widget.field_name
            if name not in values:
                continue
            value = values[name]
            if widget.field_type_string == "CheckBox":
                on = widget.on_state()
                widget.field_value = on if str(on) == str(value) else "Off"
            else:
                widget.field_value = str(value or "")
            widget.update()


def validate(applicant: ApplicantData, recipient: RecipientData) -> list[str]:
    missing = []
    for label, value in [
        ("Applicant family name", applicant.family_name),
        ("Applicant given names", applicant.given_names),
        ("Applicant date of birth", applicant.date_of_birth),
        ("Applicant residential address", applicant.residential_address),
        ("Applicant title", applicant.title or applicant.title_other),
        ("Date lodged", applicant.date_lodged),
        ("Recipient family name", recipient.family_name),
        ("Recipient given names", recipient.given_names),
        ("Recipient date of birth", recipient.date_of_birth),
        ("Recipient address", recipient.address_line1),
        ("Recipient email", recipient.email),
        ("Recipient title", recipient.title or recipient.title_other),
    ]:
        if not str(value or "").strip():
            missing.append(label)
    return missing


def build_field_values(applicant: ApplicantData, recipient: RecipientData) -> dict[str, str]:
    address_parts = [applicant.residential_address.strip()]

    address_norm = applicant.residential_address.upper()

    if (
        applicant.city.strip()
        and applicant.city.strip().upper() not in address_norm
    ):
        address_parts.append(applicant.city.strip())

    if applicant.state.strip():
        state = applicant.state.strip()
        state_code_match = re.match(r"([A-Za-z]{2})\b", state)
        state_code = (
            state_code_match.group(1).upper()
            if state_code_match
            else ""
        )

        state_already_present = (
            bool(state_code)
            and re.search(
                rf"(?<![A-Z]){re.escape(state_code)}(?![A-Z])",
                address_norm,
            )
        )

        if not state_already_present:
            address_parts.append(state)

    address = ", ".join(
        part for part in address_parts if part
    )
    addr1, addr2, country, postcode = _split_address(address, applicant.country)
    if applicant.postcode.strip():
        postcode = applicant.postcode.strip()
        if re.fullmatch(r"\d{8}", postcode):
            postcode = postcode[:5] + "-" + postcode[5:]
    app_phone_cc, app_phone_ac, app_phone_number = _split_brazil_phone(applicant.mobile)
    title_state = TITLE_STATE.get(applicant.title, "")
    r_title_state = TITLE_STATE.get(recipient.title, "")
    today = _format_pdf_date(date.today().strftime("%d/%m/%Y"))

    values = {
        # Part A - new appointment
        "ap.app": "appoint",
        "ap.person rec": "visa",
        "ap.IDNum": "Yes" if applicant.cid.strip() else "No",
        "ap.diac id": applicant.cid.strip(),
        "ap.name fam": applicant.family_name.strip().upper(),
        "ap.name giv": applicant.given_names.strip().upper(),
        "ap.dob": _format_pdf_date(applicant.date_of_birth),
        "ap.org name": "",
        "ap.resadd str": addr1,
        "ap.resadd sub": addr2,
        "ap.resadd cntry": country,
        "ap.resadd pc": postcode,
        "ap.corradd str": "AS ABOVE",
        "ap.corradd sub": "",
        "ap.corradd cntry": "",
        "ap.corradd pc": "",

        # Q9 Telephone numbers
        # Brazilian customer phone is split as:
        # (+55) (AREA CODE) NUMBER
        "ap.off ph cc": app_phone_cc,
        "ap.off ph ac": app_phone_ac,
        "ap.off ph": app_phone_number,

        # We intentionally leave Mobile/cell blank because the customer's
        # telephone number is entered in the structured Office hours fields.
        "ap.mob": "",

        # Q10 intentionally blank: company creates a separate 956A per person.
        # Q11 fixed by business rule.
        "ap.migr": "No",
        # Q12/Q13
        "ap.appoint": "Application",
        # Application-process side has a single Type of application field. Put subclass into that text.
        "ap.type": "VISITOR VISA - SUBCLASS 600",
        "ap.lodged": _format_pdf_date(applicant.date_lodged),
        "ap.diac request id": applicant.rid.strip(),
        "ap.diac trans id": applicant.trn.strip(),
        # Recipient Q14-Q19
        "ar.name fam": recipient.family_name.strip().upper(),
        "ar.name giv": recipient.given_names.strip().upper(),
        # This official PDF's internal field name for Q15 DOB is unexpectedly 'ar.lodged'.
        "ar.lodged": _format_pdf_date(recipient.date_of_birth),
        "ar.resadd str": recipient.address_line1.strip().upper(),
        "ar.resadd sub": recipient.address_line2.strip().upper(),
        "ar.resadd cntry": (recipient.address_line3 or recipient.country).strip().upper(),
        "ar.resadd pc": recipient.postcode.strip(),
        "ar.corradd str": "AS ABOVE",
        "ar.corradd sub": "",
        "ar.corradd cntry": "",
        "ar.corradd pc": "",
        "ar.off ph cc": recipient.office_country_code.strip(),
        "ar.off ph ac": recipient.office_area_code.strip(),
        "ar.off ph": recipient.office_number.strip(),
        "ar.mob": recipient.mobile.strip(),
        "ar.agree": "Yes",
        # Q19 email has the misleading internal field name ar.mob1 in this PDF.
        "ar.mob1": recipient.email.strip(),
        # Part C - choose Appointment; signatures remain blank; declaration dates use today.
        # In this official PDF the Appointment checkbox's export state is unexpectedly 'No'.
        "ar.dec appoint": "No",
        "ar.dec date": today,
        "ap.dec appoint": "No",
        "ap.dec date": today,
    }
    if title_state:
        values["ap.title"] = title_state
        values["ap.title other"] = ""
    else:
        values["ap.title other"] = applicant.title_other.strip()
    if r_title_state:
        values["ar.title"] = r_title_state
        values["ar.title other"] = ""
    else:
        values["ar.title other"] = recipient.title_other.strip()
    return values


def generate_956a(applicant: ApplicantData, recipient: RecipientData, output_path: str | Path,
                   template: str | Path | None = None) -> Path:
    missing = validate(applicant, recipient)
    if missing:
        raise ValueError("Missing required data: " + ", ".join(missing))
    src = Path(template) if template else template_path()
    if not src.exists():
        raise FileNotFoundError(f"956A template not found: {src}")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    values = build_field_values(applicant, recipient)
    doc = fitz.open(str(src))
    try:
        _set_fields(doc, values)
        doc.save(str(out), garbage=4, deflate=True)
    finally:
        doc.close()
    return out
