"""Canonical country normalization for Canada application imports.

The importer is the only caller allowed to turn human country/nationality text
into canonical ISO-3166 alpha-3 values.  Raw source text remains on the import
candidate for provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

try:  # Optional at source-checkout time; pinned in production requirements.
    import pycountry
except ImportError:  # pragma: no cover - the explicit aliases remain deterministic.
    pycountry = None


ISO_ALPHA3_CODES = frozenset("""
ABW AFG AGO AIA ALA ALB AND ARE ARG ARM ASM ATA ATF ATG AUS AUT AZE BDI BEL BEN BES BFA BGD BGR BHR BHS BIH BLM BLR BLZ BMU BOL BRA BRB BRN BTN BVT BWA CAF CAN CCK CHE CHL CHN CIV CMR COD COG COK COL COM CPV CRI CUB CUW CXR CYM CYP CZE DEU DJI DMA DNK DOM DZA ECU EGY ERI ESH ESP EST ETH FIN FJI FLK FRA FRO FSM GAB GBR GEO GGY GHA GIB GIN GLP GMB GNB GNQ GRC GRD GRL GTM GUF GUM GUY HKG HMD HND HRV HTI HUN IDN IMN IOT IRL IRN IRQ ISL ISR ITA JAM JEY JOR JPN KAZ KEN KGZ KHM KIR KNA KOR KWT LAO LBN LBR LBY LCA LIE LKA LSO LTU LUX LVA MAC MAF MAR MCO MDA MDG MDV MEX MHL MKD MLI MLT MMR MNE MNG MNP MOZ MRT MSR MTQ MUS MWI MYS MYT NAM NCL NER NFK NGA NIC NIU NLD NOR NPL NRU NZL OMN PAK PAN PCN PER PHL PLW PNG POL PRI PRK PRT PRY PSE PYF QAT REU ROU RUS RWA SAU SDN SEN SGP SGS SHN SJM SLB SLE SLV SMR SOM SPM SRB SSD STP SUR SVK SVN SWE SWZ SXM SYC SYR TCA TCD TGO THA TJK TKL TKM TLS TON TTO TUN TUR TUV TWN TZA UGA UKR UMI URY USA UZB VAT VCT VEN VGB VIR VNM VUT WLF WSM YEM ZAF ZMB ZWE
""".split())

# Includes every alpha-2 form commonly present in the supported Portuguese
# intake, plus the complete set of countries represented by its aliases.
ALPHA2_TO_ALPHA3 = {
    "AR": "ARG", "AT": "AUT", "AU": "AUS", "BE": "BEL", "BR": "BRA",
    "CA": "CAN", "CH": "CHE", "CL": "CHL", "CN": "CHN", "CO": "COL",
    "CZ": "CZE", "DE": "DEU", "DK": "DNK", "EC": "ECU", "ES": "ESP",
    "FI": "FIN", "FR": "FRA", "GB": "GBR", "GR": "GRC", "IE": "IRL",
    "IN": "IND", "IT": "ITA", "JP": "JPN", "KR": "KOR", "LU": "LUX",
    "MX": "MEX", "NL": "NLD", "NO": "NOR", "NZ": "NZL", "PE": "PER",
    "PL": "POL", "PT": "PRT", "PY": "PRY", "RU": "RUS", "SE": "SWE",
    "TR": "TUR", "UA": "UKR", "US": "USA", "UY": "URY", "VE": "VEN",
    "ZA": "ZAF",
}


def _key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


ALIASES = {
    # Portuguese and English country names, nationality adjectives, and common variants.
    "brasil": "BRA", "brazil": "BRA", "bresil": "BRA", "brasilien": "BRA", "brasileira": "BRA", "brasileiro": "BRA",
    "brasileiras": "BRA", "brasileiros": "BRA", "brazilian": "BRA",
    "canada": "CAN", "canadense": "CAN", "canadian": "CAN",
    "alemanha": "DEU", "alema": "DEU", "alemao": "DEU", "germany": "DEU", "german": "DEU",
    "suica": "CHE", "suico": "CHE", "suisse": "CHE", "schweiz": "CHE", "suica nacionalidade": "CHE", "switzerland": "CHE", "swiss": "CHE",
    "estados unidos": "USA", "estados unidos da america": "USA", "americano": "USA", "americana": "USA", "united states": "USA", "united states of america": "USA", "usa": "USA",
    "portugal": "PRT", "portugues": "PRT", "portuguesa": "PRT", "portuguese": "PRT",
    "franca": "FRA", "frances": "FRA", "francesa": "FRA", "france": "FRA", "french": "FRA",
    "italia": "ITA", "italiano": "ITA", "italiana": "ITA", "italy": "ITA", "italian": "ITA",
    "espanha": "ESP", "espanhol": "ESP", "espanhola": "ESP", "spain": "ESP", "spanish": "ESP",
    "reino unido": "GBR", "gra bretanha": "GBR", "britanico": "GBR", "britanica": "GBR", "united kingdom": "GBR", "great britain": "GBR", "british": "GBR",
    "argentina": "ARG", "argentino": "ARG", "argentina nacionalidade": "ARG",
    "chile": "CHL", "chileno": "CHL", "chilena": "CHL",
    "colombia": "COL", "colombiano": "COL", "colombiana": "COL",
    "mexico": "MEX", "mexicano": "MEX", "mexicana": "MEX",
    "peru": "PER", "peruano": "PER", "peruana": "PER",
    "uruguai": "URY", "uruguaio": "URY", "uruguaia": "URY", "uruguay": "URY",
    "paraguai": "PRY", "paraguaio": "PRY", "paraguaia": "PRY", "paraguay": "PRY",
    "venezuela": "VEN", "venezuelano": "VEN", "venezuelana": "VEN",
    "australia": "AUS", "australiano": "AUS", "australiana": "AUS", "australian": "AUS",
    "nova zelandia": "NZL", "neozelandes": "NZL", "neozelandesa": "NZL", "new zealand": "NZL",
    "japao": "JPN", "japones": "JPN", "japonesa": "JPN", "japan": "JPN", "japanese": "JPN",
    "china": "CHN", "chines": "CHN", "chinesa": "CHN", "chinese": "CHN",
    "india": "IND", "indiano": "IND", "indiana": "IND", "indian": "IND",
    "coreia do sul": "KOR", "sul coreano": "KOR", "sul coreana": "KOR", "south korea": "KOR",
    "paises baixos": "NLD", "holanda": "NLD", "holandes": "NLD", "holandesa": "NLD", "netherlands": "NLD", "dutch": "NLD",
    "belgica": "BEL", "belga": "BEL", "belgium": "BEL",
    "austria": "AUT", "austriaco": "AUT", "austriaca": "AUT",
    "suecia": "SWE", "sueco": "SWE", "sueca": "SWE", "sweden": "SWE",
    "noruega": "NOR", "noruegues": "NOR", "norueguesa": "NOR", "norway": "NOR",
    "dinamarca": "DNK", "dinamarques": "DNK", "dinamarquesa": "DNK", "denmark": "DNK",
    "finlandia": "FIN", "finlandes": "FIN", "finlandesa": "FIN", "finland": "FIN",
    "irlanda": "IRL", "irlandes": "IRL", "irlandesa": "IRL", "ireland": "IRL",
    "polonia": "POL", "polones": "POL", "polonesa": "POL", "poland": "POL",
    "grecia": "GRC", "grego": "GRC", "grega": "GRC", "greece": "GRC",
    "turquia": "TUR", "turco": "TUR", "turca": "TUR", "turkey": "TUR",
    "russia": "RUS", "russo": "RUS", "russa": "RUS", "russian federation": "RUS",
    "ucrania": "UKR", "ucraniano": "UKR", "ucraniana": "UKR", "ukraine": "UKR",
    "africa do sul": "ZAF", "sul africano": "ZAF", "sul africana": "ZAF", "south africa": "ZAF",
}


@dataclass(frozen=True)
class CountryNormalization:
    raw: str
    code: str | None
    issue: str | None = None


def normalize_country(value: object) -> CountryNormalization:
    raw = str(value or "").strip()
    if not raw:
        return CountryNormalization(raw=raw, code=None, issue="missing_country")
    upper = raw.upper()
    if upper in ISO_ALPHA3_CODES:
        return CountryNormalization(raw=raw, code=upper)
    if upper in ALPHA2_TO_ALPHA3:
        return CountryNormalization(raw=raw, code=ALPHA2_TO_ALPHA3[upper])
    code = ALIASES.get(_key(raw))
    if code is None and pycountry is not None:
        try:
            code = pycountry.countries.lookup(raw).alpha_3
        except LookupError:
            code = None
    return CountryNormalization(
        raw=raw,
        code=code,
        issue=None if code else "unknown_or_ambiguous_country",
    )


def split_country_values(value: object) -> list[str]:
    """Split explicit multi-citizenship answers without guessing comma semantics."""
    raw = str(value or "").strip()
    if not raw:
        return []
    values = re.split(r"\s*(?:;|\n|\||/|\be\b|\band\b)\s*", raw, flags=re.IGNORECASE)
    return [item.strip() for item in values if item.strip()]
