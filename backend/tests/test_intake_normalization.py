from backend.app.services.address_normalization import normalize_address
from backend.app.services.country_normalization import normalize_country, split_country_values


def test_portuguese_nationality_and_alpha2_normalize_to_alpha3():
    assert normalize_country("Brasileira").code == "BRA"
    assert normalize_country("brasileiro").code == "BRA"
    assert normalize_country("BR").code == "BRA"
    assert normalize_country("Canadense").code == "CAN"
    assert normalize_country("Alemanha").code == "DEU"


def test_multiple_citizenships_remain_separate_source_values():
    assert split_country_values("Brasileira; Canadense / Alemã") == [
        "Brasileira", "Canadense", "Alemã"
    ]


def test_unknown_country_is_explicitly_unresolved():
    result = normalize_country("Unknownland")
    assert result.code is None
    assert result.issue == "unknown_or_ambiguous_country"


def test_brazilian_address_preserves_raw_and_parses_only_certain_components():
    result = normalize_address("Rua das Flores, 123, Apto 4, Centro, 01310-100")
    assert result.raw == "Rua das Flores, 123, Apto 4, Centro, 01310-100"
    assert result.postal_code == "01310-100"
    assert result.street_name == "Rua das Flores"
    assert result.street_number == "123"
    assert result.unit == "4"
    assert result.unresolved_text == "Centro"
    assert result.review_status == "needs_review"
