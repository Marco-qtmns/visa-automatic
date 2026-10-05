from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class ApplicantData:
    family_name: str = ""
    given_names: str = ""
    date_of_birth: str = ""
    residential_address: str = ""
    country: str = "BRAZIL"
    mobile: str = ""
    marital_status: str = ""
    sex: str = ""
    title: str = ""
    title_other: str = ""
    cid: str = ""
    rid: str = ""
    trn: str = ""
    date_lodged: str = ""
    source_email: str = ""
    city: str = ""
    state: str = ""
    postcode: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class RecipientData:
    title: str = ""
    title_other: str = ""
    family_name: str = ""
    given_names: str = ""
    date_of_birth: str = ""
    address_line1: str = ""
    address_line2: str = ""
    address_line3: str = ""
    country: str = ""  # legacy fallback for settings created by v0.1/v0.1.1
    postcode: str = ""
    office_country_code: str = ""
    office_area_code: str = ""
    office_number: str = ""
    mobile: str = ""
    email: str = ""

    def to_dict(self):
        return asdict(self)
