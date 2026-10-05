from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .models import (
    Activity,
    CanadaCase,
    ContactData,
    EducationData,
    EmploymentData,
    IdentityData,
    PassportData,
    TripData,
)


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value.rstrip(" *")


def header_fingerprint(headers: list[str]) -> str:
    return hashlib.sha256(json.dumps(headers, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def normalize_date(value: str) -> str:
    value = str(value or "").strip()
    nums = re.findall(r"\d+", value)

    if len(nums) >= 3:
        d, m, y = nums[0], nums[1], nums[2]
        if len(y) == 4:
            return f"{int(d):02d}/{int(m):02d}/{y}"

    return value


@dataclass
class CsvResponseRow:
    headers: list[str]
    values: list[str]

    def values_for(self, label: str) -> list[str]:
        target = _norm(label)

        return [
            str(value or "").strip()
            for header, value in zip(self.headers, self.values)
            if _norm(header) == target
        ]

    def first(self, *labels: str) -> str:
        for label in labels:
            values = self.values_for(label)
            for value in values:
                if value:
                    return value
        return ""

    def first_containing(self, *fragments: str) -> str:
        targets = [_norm(fragment) for fragment in fragments]

        for header, value in zip(self.headers, self.values):
            normalized = _norm(header)

            if any(target in normalized for target in targets):
                value = str(value or "").strip()
                if value:
                    return value

        return ""

    def raw_dict(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}

        for header, value in zip(self.headers, self.values):
            header = str(header or "")
            result.setdefault(header, []).append(str(value or ""))

        return result


_EDUCATION_LABELS = (
    "Qual seu nível de formação educacional mais recente?",
    "Qual seu nível de formação educacional mais recente (completo ou incompleto)?",
)


def _column_indexes(row: CsvResponseRow, *labels: str) -> list[int]:
    targets = {_norm(label) for label in labels}
    return [i for i, header in enumerate(row.headers) if _norm(header) in targets]


def _column_value(row: CsvResponseRow, index: int) -> str:
    # A blank belongs to this column; never substitute another person's value.
    return str(row.values[index] or "").strip() if index < len(row.values) else ""


def _contact_values(row: CsvResponseRow, label: str) -> tuple[str, str]:
    """Resolve applicant/host contacts within the verified intake sections.

    Absolute offsets differ between export versions. Section anchors and a
    single occurrence per role are required when host data is present.
    """
    indexes = _column_indexes(row, label)
    if not indexes:
        return "", ""
    host_markers = _column_indexes(
        row, "Nome completo da pessoa/instituição", "Endereço completo no Canadá"
    )
    if len(indexes) == 1 and not host_markers:
        return _column_value(row, indexes[0]), ""

    boundaries = [
        _column_indexes(row, "Endereço completo"),
        _column_indexes(row, "Qual é o principal objetivo da sua viagem ao Canadá?"),
        _column_indexes(row, "Endereço completo no Canadá"),
        _column_indexes(row, *_EDUCATION_LABELS),
    ]
    error = (
        f"Ambiguous Canada CSV layout for {label}: review the applicant and "
        "host contact sections; no contact values have been assigned."
    )
    if any(len(matches) != 1 for matches in boundaries):
        raise ValueError(error)
    applicant_start, applicant_end, host_start, host_end = [b[0] for b in boundaries]
    if not applicant_start < applicant_end < host_start < host_end:
        raise ValueError(error)
    assigned: dict[str, int] = {}
    for index in indexes:
        if applicant_start < index < applicant_end:
            role = "applicant"
        elif host_start < index < host_end:
            role = "host"
        else:
            raise ValueError(error)
        if role in assigned:
            raise ValueError(error)
        assigned[role] = index
    return tuple(
        _column_value(row, assigned[role]) if role in assigned else ""
        for role in ("applicant", "host")
    )


def _applicant_city(row: CsvResponseRow) -> str:
    """Keep the contact city distinct from positionally grouped activity cities."""
    cities = _column_indexes(row, "Cidade")
    if not cities:
        return ""
    activities = _column_indexes(row, "Tipo de atividade")
    if not activities:
        if len(cities) == 1:
            return _column_value(row, cities[0])
    else:
        before = [i for i in cities if i < activities[0]]
        ends = activities[1:] + [len(row.headers)]
        counts = [sum(start < i < end for i in cities)
                  for start, end in zip(activities, ends)]
        if len(before) == 1 and all(count == 1 for count in counts):
            return _column_value(row, before[0])
    raise ValueError(
        "Ambiguous Canada CSV layout for Cidade: review the applicant city "
        "and activity blocks; no city values have been assigned."
    )


def _activities(row: CsvResponseRow) -> list[Activity]:
    activity_types = row.values_for("Tipo de atividade")
    starts = row.values_for("Data de início")
    ends = row.values_for("Data de término")
    positions = row.values_for("Cargo")
    organizations = row.values_for(
        "Nome da empresa, empregador ou instituição"
    )

    # "Cidade" is also used for the residential address.
    # The first occurrence belongs to ContactData; later occurrences belong
    # to the repeated activity-history blocks.
    cities = row.values_for("Cidade")
    activity_cities = cities[1:] if cities else []

    count = max(
        len(activity_types),
        len(starts),
        len(ends),
        len(positions),
        len(organizations),
        len(activity_cities),
        0,
    )

    activities: list[Activity] = []

    def get(values: list[str], index: int) -> str:
        return values[index] if index < len(values) else ""

    for i in range(count):
        activity = Activity(
            activity_type=get(activity_types, i),
            start_date=normalize_date(get(starts, i)),
            end_date=normalize_date(get(ends, i)),
            position=get(positions, i),
            organization=get(organizations, i),
            city=get(activity_cities, i),
        )
        # A state belongs to its activity section, not to the residential address.
        anchors = _column_indexes(row, "Tipo de atividade")
        if i < len(anchors):
            start = anchors[i]
            end = anchors[i + 1] if i + 1 < len(anchors) else len(row.headers)
            states = [j for j in _column_indexes(row, "Estado", "Estado/província") if start < j < end]
            if len(states) > 1:
                raise ValueError("Ambiguous state in Canada activity block")
            if states:
                activity.state = _column_value(row, states[0])

        if any(vars(activity).values()):
            activity.source_block_index = i + 1
            activity.source_role = "csv"
            activities.append(activity)

    return activities


def _applicant_state(row: CsvResponseRow) -> str:
    starts = _column_indexes(row, "Tipo de atividade")
    boundary = starts[0] if starts else len(row.headers)
    indexes = [i for i in _column_indexes(row, "Estado") if i < boundary]
    if len(indexes) > 1:
        raise ValueError("Ambiguous applicant state in Canada CSV")
    return _column_value(row, indexes[0]) if indexes else ""


def canada_case_from_csv_row(row: CsvResponseRow) -> CanadaCase:
    from .verified_intake import HEADER_SHA256, read_verified
    fingerprint = header_fingerprint(row.headers)
    if fingerprint == HEADER_SHA256:
        return read_verified(row, fingerprint)
    applicant_email, host_email = _contact_values(row, "E-mail")
    applicant_phone, host_phone = _contact_values(row, "Telefone")
    applicant_city = _applicant_city(row)
    identity = IdentityData(
        full_name=row.first("Nome completo, conforme o passaporte"),
        other_names=row.first_containing("Já usou outro nome"),
        date_of_birth=normalize_date(row.first("Data de nascimento")),
        city_of_birth=row.first("Cidade de nascimento"),
        state_of_birth=row.first("Estado de nascimento"),
        nationality=row.first("Qual é sua nacionalidade?"),
        other_citizenship=row.first_containing("Possui outra cidadania"),
        residence_country=row.first("Em qual país reside atualmente?"),
        residence_status=row.first("Qual é seu status no país de residência?"),
        residence_since=normalize_date(
            row.first(
                "Desde quando você reside nesse país?",
                "Desde quando reside nesse país atual?",
            )
        ),
        previous_residence_5y=row.first_containing(
            "Nos últimos 5 anos, você morou em algum outro país"
        ),
        marital_status=row.first("Estado civil atual", "Estado civil"),
        languages=row.first_containing(
            "Você consegue se comunicar em inglês, francês ou ambos"
        ),
    )

    passport = PassportData(
        number=row.first("Número do passaporte"),
        issuing_country=row.first("País que emitiu o passaporte"),
        issue_date=normalize_date(row.first("Data de emissão do passaporte")),
        expiry_date=normalize_date(row.first("Data de validade do passaporte")),
        has_other_valid_passport=row.first(
            "Você possui outro passaporte válido?"
        ),
        other_passport_details=row.first_containing(
            "Se sim, informe país e número do outro passaporte"
        ),
        identity_number=row.first("Número da identidade"),
        identity_issue_date=normalize_date(
            row.first("Data de emissão da identidade")
        ),
        identity_expiry_date=normalize_date(
            row.first("Data de validade da identidade")
        ),
        green_card_details=row.first_containing(
            "residente permanente legal dos Estados Unidos"
        ),
    )

    contact = ContactData(
        address=next((str(v or "") for h,v in zip(row.headers,row.values) if _norm(h) == _norm("Endereço completo")), ""),
        city=applicant_city,
        state=_applicant_state(row),
        postcode=row.first("CEP"),
        email=applicant_email,
        phone=applicant_phone,
    )

    trip = TripData(
        purpose=row.first("Qual é o principal objetivo da sua viagem ao Canadá?"),
        arrival_date=normalize_date(
            row.first("Data prevista de chegada no Canadá")
        ),
        departure_date=normalize_date(
            row.first("Data prevista de saída do Canadá")
        ),
        duration_days=row.first(
            "Quantos dias pretende permanecer no Canadá?"
        ),
        estimated_spend=row.first_containing(
            "Valor aproximado que pretende gastar"
        ),
        payer=row.first("Quem pagará pelos custos da viagem?"),
        payer_details=row.first_containing(
            "Caso outra pessoa ou empresa pague pela viagem"
        ),
        visiting_person_or_institution=row.first(
            "Você pretende visitar alguma pessoa ou instituição no Canadá?"
        ),
        host_name=row.first("Nome completo da pessoa/instituição"),
        relationship=row.first("Relação com você"),
        family_relationship=row.first_containing(
            "Se for familiar, qual é o grau de parentesco"
        ),
        host_status=row.first("Status dessa pessoa no Canadá"),
        host_address=row.first("Endereço completo no Canadá"),
        host_postcode=row.first("Código postal (postal code)"),
        host_phone=host_phone,
        host_email=host_email,
    )

    education = EducationData(
        level=row.first(*_EDUCATION_LABELS),
        institution=row.first(
            "Nome da instituição de ensino mais recente"
        ),
        course=row.first("Curso"),
        start_date=normalize_date(row.first("Data de início do curso")),
        end_date=normalize_date(row.first("Data de conclusão do curso")),
        country=row.first("País onde estudou"),
    )

    employment = EmploymentData(
        start_date=normalize_date(
            row.first("Data de início do emprego atual")
        ),
        profession=row.first("Qual é sua profissão atual?"),
        duties=row.first("Descreva brevemente sua função atual"),
        organization=row.first("Nome da empresa/instituição"),
        city=row.first("Cidade da empresa/instituição"),
        state=row.first("Estado da empresa/instituição"),
    )

    from .family_reader import read_family
    relationships, family = read_family(row)

    case = CanadaCase(
        relationships=relationships,
        family=family,
        identity=identity,
        passport=passport,
        contact=contact,
        trip=trip,
        education=education,
        employment=employment,
        activities=_activities(row),
        raw_response=row.raw_dict(),
        source_email=contact.email,
        source_headers=list(row.headers),
        source_header_sha256=fingerprint,
    )
    if case.source_header_sha256 not in {
        "858532075b08d4f9a2c0867e2981bbc78750be87fe5bd26517170ad296c870e2",
        "7136b956dfb5de8bad7231207fd665f1d982751d7d23a5a0aae14241b1883dfc",
    }:
        case.import_profile = "schema_unverified"
    from .updated_intake import apply_updated_intake
    return apply_updated_intake(case, row)


def read_google_forms_csv(path: str | Path) -> list[CanadaCase]:
    path = Path(path)

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return []

    headers = rows[0]
    versions = {
        "81820c7095e89bb2809f1c674838a95a088524b15efa4e70827a7b535ac0117b": "canada_trv_google_form_v1",
        "858532075b08d4f9a2c0867e2981bbc78750be87fe5bd26517170ad296c870e2": "canada_trv_legacy_v1",
        "7136b956dfb5de8bad7231207fd665f1d982751d7d23a5a0aae14241b1883dfc": "canada_trv_archive_v1",
    }
    version = versions.get(header_fingerprint(headers))
    if version is None:
        raise ValueError("CSV_SCHEMA_MISMATCH: unknown, missing or reordered Canada headers")
    cases: list[CanadaCase] = []

    for values in rows[1:]:
        if not any(values):
            continue
        if len(values) != len(headers):
            raise ValueError("CSV_SCHEMA_MISMATCH: response width differs from headers")
        # Preserve column positions even if Google exported duplicate headers.
        padded = values + [""] * max(0, len(headers) - len(values))
        response = CsvResponseRow(headers, padded[:len(headers)])

        if not any(str(value or "").strip() for value in response.values):
            continue

        case = canada_case_from_csv_row(response)
        case.schema_version = version
        from .provenance import seed_source
        seed_source(case)
        cases.append(case)

    return cases
