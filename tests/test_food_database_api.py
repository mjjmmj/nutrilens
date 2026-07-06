import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.food_database_api import (
    ExternalFoodResult,
    search_open_food_facts,
    fetch_product_by_barcode,
    _off_product_to_result,
    _extract_serving_grams,
    _clean_category,
)


# --------------------------------------------------------------------------- #
# Sample fixtures, shaped like real Open Food Facts API responses
# --------------------------------------------------------------------------- #

SAMPLE_PRODUCT_WITH_SERVING_DATA = {
    "product_name": "Greek Yogurt",
    "brands": "Chobani",
    "categories": "Dairies, Fermented foods, Yogurts",
    "categories_tags": ["en:dairies", "en:fermented-foods", "en:yogurts"],
    "serving_size": "150 g",
    "code": "0000000000001",
    "nutriments": {
        "energy-kcal_100g": 97,
        "energy-kcal_serving": 146,
        "proteins_100g": 9,
        "proteins_serving": 13.5,
        "carbohydrates_100g": 3.6,
        "carbohydrates_serving": 5.4,
        "fiber_100g": 0,
        "fiber_serving": 0,
        "sugars_100g": 3.6,
        "sugars_serving": 5.4,
        "fat_100g": 5,
        "fat_serving": 7.5,
        "saturated-fat_100g": 3.3,
        "saturated-fat_serving": 5.0,
        "trans-fat_100g": 0,
        "trans-fat_serving": 0,
        "sodium_100g": 0.036,
        "sodium_serving": 0.054,
        "cholesterol_100g": 0.017,
        "cholesterol_serving": 0.0255,
    },
}

SAMPLE_PRODUCT_NO_SERVING_DATA = {
    "product_name": "Rolled Oats",
    "brands": "Quaker",
    "categories_tags": ["en:cereals", "en:breakfast-cereals"],
    "code": "0000000000002",
    "nutriments": {
        "energy-kcal_100g": 379,
        "proteins_100g": 13.5,
        "carbohydrates_100g": 67.7,
        "fiber_100g": 10.1,
        "sugars_100g": 0.99,
        "fat_100g": 6.9,
        "saturated-fat_100g": 1.2,
        "sodium_100g": 0.002,
    },
}

SAMPLE_SEARCH_RESPONSE = {
    "count": 2,
    "products": [SAMPLE_PRODUCT_WITH_SERVING_DATA, SAMPLE_PRODUCT_NO_SERVING_DATA],
}

SAMPLE_BARCODE_FOUND_RESPONSE = {
    "status": 1,
    "code": "0000000000001",
    "product": SAMPLE_PRODUCT_WITH_SERVING_DATA,
}

SAMPLE_BARCODE_NOT_FOUND_RESPONSE = {
    "status": 0,
    "status_verbose": "product not found",
}


def _mock_response(json_data, status_code=200, raise_for_status_error=None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    if raise_for_status_error:
        mock_resp.raise_for_status.side_effect = raise_for_status_error
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


# --------------------------------------------------------------------------- #
# _off_product_to_result: core parsing logic
# --------------------------------------------------------------------------- #

def test_parse_product_prefers_serving_values_when_available():
    result = _off_product_to_result(SAMPLE_PRODUCT_WITH_SERVING_DATA)
    assert result.name == "Greek Yogurt"
    assert result.brand == "Chobani"
    assert result.serving_size_g == 150.0
    assert result.calories == 146
    assert result.protein_g == 13.5
    assert result.total_carbs_g == 5.4
    assert result.fiber_g == 0
    assert result.sugars_g == 5.4
    assert result.total_fat_g == 7.5
    assert result.saturated_fat_g == 5.0
    assert result.trans_fat_g == 0


def test_parse_product_converts_sodium_and_cholesterol_grams_to_mg():
    result = _off_product_to_result(SAMPLE_PRODUCT_WITH_SERVING_DATA)
    # 0.054g sodium (serving) -> 54mg
    assert result.sodium_mg == 54.0
    # 0.0255g cholesterol (serving) -> 25.5mg
    assert result.cholesterol_mg == 25.5


def test_parse_product_falls_back_to_100g_when_no_serving_data():
    result = _off_product_to_result(SAMPLE_PRODUCT_NO_SERVING_DATA)
    assert result.name == "Rolled Oats"
    assert result.serving_size_g == 100.0  # defaulted, no serving_size field
    assert result.calories == 379
    assert result.protein_g == 13.5
    assert result.fiber_g == 10.1


def test_parse_product_barcode_captured():
    result = _off_product_to_result(SAMPLE_PRODUCT_WITH_SERVING_DATA)
    assert result.barcode == "0000000000001"


def test_parse_product_source_is_open_food_facts():
    result = _off_product_to_result(SAMPLE_PRODUCT_WITH_SERVING_DATA)
    assert result.source == "Open Food Facts"


def test_parse_product_category_cleaned_from_tags():
    result = _off_product_to_result(SAMPLE_PRODUCT_WITH_SERVING_DATA)
    assert result.category == "Dairies"


def test_parse_product_missing_name_returns_none():
    product = {"brands": "SomeBrand", "nutriments": {}}
    result = _off_product_to_result(product)
    assert result is None


def test_parse_product_blank_name_returns_none():
    product = {"product_name": "   ", "nutriments": {}}
    result = _off_product_to_result(product)
    assert result is None


def test_parse_product_missing_nutriments_no_crash():
    product = {"product_name": "Mystery Item"}
    result = _off_product_to_result(product)
    assert result is not None
    assert result.calories == 0.0
    assert result.protein_g == 0.0


def test_parse_product_malformed_nutriment_values_no_crash():
    product = {
        "product_name": "Weird Data Item",
        "nutriments": {"energy-kcal_100g": "not_a_number", "proteins_100g": None},
    }
    result = _off_product_to_result(product)
    assert result.calories == 0.0
    assert result.protein_g == 0.0


def test_parse_product_no_brand():
    product = {"product_name": "Generic Item", "nutriments": {}}
    result = _off_product_to_result(product)
    assert result.brand is None


def test_parse_product_brand_takes_first_of_comma_separated_list():
    # OFF's `brands` field is a genuinely comma-separated list when a
    # product has multiple brand names (e.g. "Danone, Danone SA"), so
    # taking the first entry is correct there. Documented limitation:
    # this also splits on a comma that's part of a single legal name
    # (e.g. "Acme, Inc." -> "Acme"), which OFF's own field format doesn't
    # distinguish from the multi-brand case.
    product = {"product_name": "Widget Snack", "brands": "Acme, Inc.", "nutriments": {}}
    result = _off_product_to_result(product)
    assert result.brand == "Acme"


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #

def test_extract_serving_grams_simple():
    assert _extract_serving_grams("30 g") == 30.0
    assert _extract_serving_grams("150g") == 150.0


def test_extract_serving_grams_with_ml():
    assert _extract_serving_grams("250 ml") == 250.0


def test_extract_serving_grams_with_extra_text():
    assert _extract_serving_grams("1 cup (240ml)") == 240.0


def test_extract_serving_grams_none_input():
    assert _extract_serving_grams(None) is None
    assert _extract_serving_grams("") is None


def test_extract_serving_grams_unparseable():
    assert _extract_serving_grams("one serving") is None


def test_clean_category_from_tags():
    product = {"categories_tags": ["en:breakfast-cereals"]}
    assert _clean_category(product) == "Breakfast Cereals"


def test_clean_category_from_raw_string_fallback():
    product = {"categories": "Snacks, Cookies"}
    assert _clean_category(product) == "Snacks"


def test_clean_category_missing_returns_none():
    assert _clean_category({}) is None


# --------------------------------------------------------------------------- #
# search_open_food_facts (mocked HTTP)
# --------------------------------------------------------------------------- #

def test_search_returns_parsed_results():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.return_value = _mock_response(SAMPLE_SEARCH_RESPONSE)
        results = search_open_food_facts("yogurt")
    assert len(results) == 2
    assert all(isinstance(r, ExternalFoodResult) for r in results)
    assert results[0].name == "Greek Yogurt"
    assert results[1].name == "Rolled Oats"


def test_search_empty_query_returns_empty_without_network_call():
    with patch("modules.food_database_api.requests.get") as mock_get:
        results = search_open_food_facts("")
    assert results == []
    mock_get.assert_not_called()


def test_search_whitespace_query_returns_empty():
    results = search_open_food_facts("   ")
    assert results == []


def test_search_network_failure_returns_empty_list():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.side_effect = ConnectionError("no internet")
        results = search_open_food_facts("yogurt")
    assert results == []


def test_search_timeout_returns_empty_list():
    import requests as requests_module
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.side_effect = requests_module.exceptions.Timeout("timed out")
        results = search_open_food_facts("yogurt")
    assert results == []


def test_search_http_error_returns_empty_list():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.return_value = _mock_response(
            {}, status_code=500, raise_for_status_error=Exception("server error")
        )
        results = search_open_food_facts("yogurt")
    assert results == []


def test_search_malformed_json_returns_empty_list():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("invalid json")
        mock_get.return_value = mock_resp
        results = search_open_food_facts("yogurt")
    assert results == []


def test_search_no_products_key_returns_empty_list():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.return_value = _mock_response({"count": 0})
        results = search_open_food_facts("nonexistent_food_xyz")
    assert results == []


def test_search_filters_out_unparseable_products():
    response = {"products": [{"brands": "NoName"}, SAMPLE_PRODUCT_NO_SERVING_DATA]}
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.return_value = _mock_response(response)
        results = search_open_food_facts("oats")
    assert len(results) == 1
    assert results[0].name == "Rolled Oats"


def test_search_page_size_clamped():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.return_value = _mock_response(SAMPLE_SEARCH_RESPONSE)
        search_open_food_facts("yogurt", page_size=999)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["page_size"] <= 50


# --------------------------------------------------------------------------- #
# fetch_product_by_barcode (mocked HTTP)
# --------------------------------------------------------------------------- #

def test_fetch_by_barcode_found():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.return_value = _mock_response(SAMPLE_BARCODE_FOUND_RESPONSE)
        result = fetch_product_by_barcode("0000000000001")
    assert result is not None
    assert result.name == "Greek Yogurt"


def test_fetch_by_barcode_not_found():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.return_value = _mock_response(SAMPLE_BARCODE_NOT_FOUND_RESPONSE)
        result = fetch_product_by_barcode("9999999999999")
    assert result is None


def test_fetch_by_barcode_empty_input_returns_none_without_network_call():
    with patch("modules.food_database_api.requests.get") as mock_get:
        result = fetch_product_by_barcode("")
    assert result is None
    mock_get.assert_not_called()


def test_fetch_by_barcode_network_failure_returns_none():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_get.side_effect = ConnectionError("no internet")
        result = fetch_product_by_barcode("0000000000001")
    assert result is None


def test_fetch_by_barcode_malformed_json_returns_none():
    with patch("modules.food_database_api.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("invalid json")
        mock_get.return_value = mock_resp
        result = fetch_product_by_barcode("0000000000001")
    assert result is None
