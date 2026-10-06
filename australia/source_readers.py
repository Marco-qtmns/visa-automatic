from __future__ import annotations
import csv
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import pymupdf as fitz

from .models import ApplicantData


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def normalize_date(value: str) -> str:
    value = str(value or "").strip()
    nums = re.findall(r"\d+", value)
    if len(nums) >= 3:
        d, m, y = nums[0], nums[1], nums[2]
        if len(y) == 4:
            return f"{int(d):02d}/{int(m):02d}/{y}"
    return value


def infer_title(sex: str, marital_status: str) -> str:
    """Business rule agreed for this workflow. Falls back to blank when uncertain."""
    s = _norm(sex)
    m = _norm(marital_status)
    if s in {"male", "masculino", "m", "homem"}:
        return "Mr"
    if s in {"female", "feminino", "f", "mulher"}:
        if any(x in m for x in ("casad", "married")):
            return "Mrs"
        if any(x in m for x in ("solteir", "single")):
            return "Miss"
        return "Ms"
    return ""


def _header_value(row: dict, needles: Iterable[str]) -> str:
    needles_n = [_norm(n) for n in needles]
    for key, value in row.items():
        nk = _norm(key)
        if any(n in nk for n in needles_n):
            return str(value or "").strip()
    return ""


def _exact_header_value(row: dict, names: Iterable[str]) -> str:
    names = {_norm(name) for name in names}
    for key, value in row.items():
        if _norm(key).rstrip(" *") in names:
            return str(value or "").strip()
    return ""



_BRAZIL_UF_CODES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
    "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

_CEP_RE = re.compile(
    r"(?<!\d)(\d{2})\.?(\d{3})-?(\d{3})(?!\d)"
)


def _apply_address_fallbacks(a: ApplicantData) -> ApplicantData:
    """Fill missing CEP/state only when they are explicit in the address text.

    Existing structured values always win. City is deliberately not inferred.
    """
    address = str(a.residential_address or "").strip()

    if not address:
        return a

    if not str(a.postcode or "").strip():
        match = _CEP_RE.search(address)
        if match:
            a.postcode = (
                f"{match.group(1)}{match.group(2)}-{match.group(3)}"
            )

    if not str(a.state or "").strip():
        uf_choices = "|".join(sorted(_BRAZIL_UF_CODES))
        tail = re.sub(r"\s+", " ", address.upper())[-100:]

        match = re.search(
            rf"(?:[-/,]\s*|\s)({uf_choices})"
            rf"(?=\s*(?:CEP\b|"
            rf"\d{{2}}\.?\d{{3}}-?\d{{3}}\b|"
            rf"[-–—,;]|$))",
            tail,
        )

        if match:
            a.state = match.group(1)

    return a


def applicant_from_csv_row(row: dict, default_country: str = "BRAZIL") -> ApplicantData:
    a = ApplicantData()
    a.family_name = _header_value(row, ["sobrenome completo", "surname", "family name"])
    a.given_names = _header_value(row, ["nome *", "given names", "first name"])
    if not a.given_names:
        # Exact header matching is preferable to grabbing "nome completo" questions.
        for k, v in row.items():
            if _norm(k) in {"nome", "given name", "given names"}:
                a.given_names = str(v or "").strip()
                break
    a.date_of_birth = normalize_date(_header_value(row, ["data de nascimento", "date of birth"]))
    a.residential_address = _header_value(row, ["endereco residencial completo", "residential address"])
    a.city = _exact_header_value(row, ["cidade", "city"])
    a.state = _exact_header_value(row, ["estado", "state"])
    a.postcode = _exact_header_value(row, ["cep", "postcode", "postal code"])
    a.mobile = _header_value(row, ["telefone celular", "mobile", "cell phone"])
    a.source_email = _header_value(row, ["e-mail", "email"])
    a.marital_status = _header_value(row, ["estado civil", "marital status"])
    a.sex = _header_value(row, ["sexo", "genero", "gender", "sex"])
    a.cid = _header_value(row, ["home affairs client id", "client id (cid)"])
    explicit_title = _header_value(row, ["title", "titulo"])
    a.title = explicit_title or infer_title(a.sex, a.marital_status)
    country = _header_value(row, ["pais onde se encontra atualmente", "country of residence"])
    country_n = _norm(country)
    if country_n in {"brasil", "brazil"}:
        a.country = "BRAZIL"
    else:
        a.country = country.upper() if country else default_country

    return _apply_address_fallbacks(a)


def read_google_forms_csv(path: str | Path, default_country: str = "BRAZIL") -> list[ApplicantData]:
    path = Path(path)
    # Google Sheets CSV exports are UTF-8; utf-8-sig also handles optional BOM.
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [applicant_from_csv_row(r, default_country) for r in rows]


def _page_blocks(page: fitz.Page):
    # Lines keep question numbers separate even when MuPDF groups them with labels.
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = re.sub(r"\s+", " ", "".join(span["text"] for span in line["spans"])).strip()
            if text:
                x0, y0, x1, y1 = line["bbox"]
                out.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, text=text))
    return out


def _answer_below(page: fitz.Page, label_fragment: str, max_gap: float = 180.0) -> str:
    """Read a text answer within its question, never options or example text."""
    blocks = _page_blocks(page)
    target = _norm(label_fragment).rstrip(" *")
    labels = [b for b in blocks
              if _norm(b["text"]).rstrip(" *") == target
              or _norm(b["text"]).startswith(target + " *")
              or (target == "endereco residencial completo" and
                  _norm(b["text"]).startswith(target + ","))
              or (target == "telefone celular" and
                  _norm(b["text"]).startswith(target + "."))]
    if not labels:
        return ""
    label = min(labels, key=lambda b: b["y0"])
    # Numbered questions and required-question labels delimit answer regions.
    boundaries = [b["y0"] for b in blocks if b["y0"] > label["y1"] + 1
                  and ((b["x0"] < label["x0"] - 10
                        and re.match(r"^\d+\.", b["text"]))
                       or b["text"].endswith("*"))]
    end = min(boundaries, default=page.rect.height)
    candidates = sorted((b for b in blocks
                         if label["y1"] - 1 < b["y0"] < min(end, label["y1"] + max_gap)
                         and label["x0"] - 3 <= b["x0"] < 480),
                        key=lambda b: (b["y0"], b["x0"]))
    # Printed choices do not reliably identify the selected answer.
    if any("marcar apenas uma oval" in _norm(b["text"])
           or "marque todas" in _norm(b["text"])
           or _norm(b["text"]) == "dropdown" for b in candidates):
        return ""
    answers = []
    for b in candidates:
        text = b["text"]
        normalized = _norm(text)
        if (normalized.startswith(("exemplo:", "https://", "http://"))
                or normalized in {"dd", "mm", "aaaa", "/", "outro:", "sim", "nao", "*"}
                or re.fullmatch(r"\d+\.", text)):
            continue
        answers.append(text)
    return " ".join(answers).strip()


def read_google_forms_pdf(path: str | Path, default_country: str = "BRAZIL") -> ApplicantData:
    """Find labelled answers across pages in old and revised Google Forms exports.

    Blank templates remain blank. Printed radio/dropdown options are not answers;
    use CSV or manual review for those fields. No OCR is performed.
    """
    with fitz.open(str(path)) as doc:
        def answer(label):
            return next((value for page in doc
                         if (value := _answer_below(page, label))), "")

        texts = [_norm(page.get_text()) for page in doc]
        if not any("sobrenome completo" in text for text in texts):
            raise ValueError("This does not look like a supported Google Forms export.")
        a = ApplicantData(country=default_country)
        for field, label in {
            "family_name": "Sobrenome completo", "given_names": "Nome",
            "date_of_birth": "Data de nascimento",
            "residential_address": "Endereço residencial completo",
            "city": "Cidade", "state": "Estado", "postcode": "CEP",
            "mobile": "Telefone celular", "source_email": "E-mail",
            "marital_status": "Estado civil",
        }.items():
            setattr(a, field, answer(label))
        a.date_of_birth = normalize_date(a.date_of_birth)
        country = answer("País onde se encontra atualmente")
        if country:
            a.country = "BRAZIL" if _norm(country) in {"brasil", "brazil"} else country.upper()

        return _apply_address_fallbacks(a)
