import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests
from modules.food_database_api import (
    ExternalFoodResult,
    OpenFoodFactsError,
    search_open_food_facts,
    fetch_product_by_barcode,
    check_sdk_compatibility,
    _off_product_to_result,
    _extract_serving_grams,
    _clean_category,
    _describe_request_failure,
)


@pytest.fixture(autouse=True)
def _no_real_sleep():
    """The retry-with-backoff logic calls time.sleep() between attempts
    on transient (429/503) errors -- mock it out so tests that exercise
    those retries run instantly instead of actually waiting several
    seconds per test."""
    with patch("modules.food_database_api.time.sleep"):
        yield


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
    "page": 1,
    "page_count": 1,
    "page_size": 10,
    "products": [SAMPLE_PRODUCT_WITH_SERVING_DATA, SAMPLE_PRODUCT_NO_SERVING_DATA],
}


def _mock_api_with_search_result(return_value):
    mock_api = MagicMock()
    mock_api.product.text_search.return_value = return_value
    return mock_api


def _mock_api_with_barcode_result(return_value):
    mock_api = MagicMock()
    mock_api.product.get.return_value = return_value
    return mock_api


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
# present_fields tracking (for UI highlighting of auto-filled values)
# --------------------------------------------------------------------------- #

def test_present_fields_includes_found_nutrients():
    result = _off_product_to_result(SAMPLE_PRODUCT_WITH_SERVING_DATA)
    assert "calories" in result.present_fields
    assert "protein_g" in result.present_fields
    assert "total_carbs_g" in result.present_fields
    assert "sodium_mg" in result.present_fields
    assert "cholesterol_mg" in result.present_fields
    assert "brand" in result.present_fields
    assert "category" in result.present_fields
    assert "serving_size_g" in result.present_fields


def test_present_fields_excludes_missing_nutrients():
    product = {"product_name": "Sparse Item", "nutriments": {"proteins_100g": 5}}
    result = _off_product_to_result(product)
    assert "protein_g" in result.present_fields
    assert "calories" not in result.present_fields
    assert "sodium_mg" not in result.present_fields
    assert "brand" not in result.present_fields
    assert "serving_size_g" not in result.present_fields


def test_present_fields_empty_for_fully_missing_data():
    product = {"product_name": "Blank Item"}
    result = _off_product_to_result(product)
    assert result.present_fields == set()


def test_present_fields_excludes_malformed_values():
    product = {
        "product_name": "Bad Data Item",
        "nutriments": {"proteins_100g": "garbage"},
    }
    result = _off_product_to_result(product)
    assert "protein_g" not in result.present_fields


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
# _describe_request_failure: error message specificity
# --------------------------------------------------------------------------- #

def _http_error_with_status(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    return requests.exceptions.HTTPError(response=resp)


def test_describe_failure_rate_limit():
    msg = _describe_request_failure(_http_error_with_status(429))
    assert "rate limit" in msg.lower()


def test_describe_failure_service_unavailable():
    msg = _describe_request_failure(_http_error_with_status(503))
    assert "503" in msg


def test_describe_failure_other_http_status():
    msg = _describe_request_failure(_http_error_with_status(500))
    assert "500" in msg


def test_describe_failure_timeout():
    msg = _describe_request_failure(requests.exceptions.Timeout("timed out"))
    assert "timed out" in msg.lower()


def test_describe_failure_connection_error():
    msg = _describe_request_failure(requests.exceptions.ConnectionError("no internet"))
    assert "internet" in msg.lower() or "reach" in msg.lower()


def test_describe_failure_generic_exception():
    msg = _describe_request_failure(ValueError("something else"))
    assert "something else" in msg


# --------------------------------------------------------------------------- #
# search_open_food_facts (mocked SDK)
# --------------------------------------------------------------------------- #

def test_search_returns_parsed_results():
    mock_api = _mock_api_with_search_result(SAMPLE_SEARCH_RESPONSE)
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        results = search_open_food_facts("yogurt")
    assert len(results) == 2
    assert all(isinstance(r, ExternalFoodResult) for r in results)
    assert results[0].name == "Greek Yogurt"
    assert results[1].name == "Rolled Oats"


def test_search_empty_query_returns_empty_without_calling_api():
    mock_api = _mock_api_with_search_result(SAMPLE_SEARCH_RESPONSE)
    with patch("modules.food_database_api._get_api", return_value=mock_api):
        results = search_open_food_facts("")
    assert results == []
    mock_api.product.text_search.assert_not_called()


def test_search_whitespace_query_returns_empty():
    results = search_open_food_facts("   ")
    assert results == []


def test_search_genuinely_no_matches_returns_empty_list_not_error():
    mock_api = _mock_api_with_search_result({"count": 0, "products": []})
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        results = search_open_food_facts("nonexistent_food_xyz")
    assert results == []


def test_search_missing_sdk_raises_clear_error():
    with patch("modules.food_database_api._HAS_SDK", False):
        try:
            search_open_food_facts("yogurt")
            assert False, "should have raised"
        except OpenFoodFactsError as e:
            assert "openfoodfacts" in str(e).lower()


def test_search_network_failure_raises_open_food_facts_error_not_swallowed():
    """This is the core bug fix: network/API failures must be
    distinguishable from a genuine 'no results' response, rather than
    both silently collapsing into an empty list."""
    mock_api = MagicMock()
    mock_api.product.text_search.side_effect = requests.exceptions.ConnectionError("no internet")
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        try:
            search_open_food_facts("yogurt")
            assert False, "should have raised OpenFoodFactsError"
        except OpenFoodFactsError:
            pass


def test_search_rate_limit_raises_specific_error():
    mock_api = MagicMock()
    mock_api.product.text_search.side_effect = _http_error_with_status(429)
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        try:
            search_open_food_facts("yogurt")
            assert False, "should have raised"
        except OpenFoodFactsError as e:
            assert "rate limit" in str(e).lower()


def test_search_service_unavailable_raises_specific_error():
    mock_api = MagicMock()
    mock_api.product.text_search.side_effect = _http_error_with_status(503)
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        try:
            search_open_food_facts("yogurt")
            assert False, "should have raised"
        except OpenFoodFactsError as e:
            assert "503" in str(e)


def test_search_filters_out_unparseable_products():
    response = {"products": [{"brands": "NoName"}, SAMPLE_PRODUCT_NO_SERVING_DATA]}
    mock_api = _mock_api_with_search_result(response)
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        results = search_open_food_facts("oats")
    assert len(results) == 1
    assert results[0].name == "Rolled Oats"


def test_search_page_size_clamped():
    mock_api = _mock_api_with_search_result(SAMPLE_SEARCH_RESPONSE)
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        search_open_food_facts("yogurt", page_size=999)
    _, kwargs = mock_api.product.text_search.call_args
    assert kwargs["page_size"] <= 50


# --------------------------------------------------------------------------- #
# fetch_product_by_barcode (mocked SDK)
# --------------------------------------------------------------------------- #

def test_fetch_by_barcode_found():
    mock_api = _mock_api_with_barcode_result(SAMPLE_PRODUCT_WITH_SERVING_DATA)
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        result = fetch_product_by_barcode("0000000000001")
    assert result is not None
    assert result.name == "Greek Yogurt"


def test_fetch_by_barcode_not_found_returns_none_not_error():
    mock_api = _mock_api_with_barcode_result(None)
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        result = fetch_product_by_barcode("9999999999999")
    assert result is None


def test_fetch_by_barcode_empty_input_returns_none_without_calling_api():
    mock_api = _mock_api_with_barcode_result(SAMPLE_PRODUCT_WITH_SERVING_DATA)
    with patch("modules.food_database_api._get_api", return_value=mock_api):
        result = fetch_product_by_barcode("")
    assert result is None
    mock_api.product.get.assert_not_called()


def test_fetch_by_barcode_network_failure_raises_error():
    mock_api = MagicMock()
    mock_api.product.get.side_effect = requests.exceptions.ConnectionError("no internet")
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        try:
            fetch_product_by_barcode("0000000000001")
            assert False, "should have raised"
        except OpenFoodFactsError:
            pass


def test_fetch_by_barcode_missing_sdk_raises_clear_error():
    with patch("modules.food_database_api._HAS_SDK", False):
        try:
            fetch_product_by_barcode("0000000000001")
            assert False, "should have raised"
        except OpenFoodFactsError as e:
            assert "openfoodfacts" in str(e).lower()


# --------------------------------------------------------------------------- #
# Future-proofing: defensive response-shape parsing
# --------------------------------------------------------------------------- #

def test_extract_products_list_documented_key():
    from modules.food_database_api import _extract_products_list
    assert _extract_products_list({"products": [{"a": 1}]}) == [{"a": 1}]


def test_extract_products_list_alternate_keys():
    from modules.food_database_api import _extract_products_list
    # Simulates the backend migration mentioned in the module's
    # TRANSPORT NOTE changing the response shape
    assert _extract_products_list({"hits": [{"a": 1}]}) == [{"a": 1}]
    assert _extract_products_list({"results": [{"a": 1}]}) == [{"a": 1}]


def test_extract_products_list_missing_key_returns_empty():
    from modules.food_database_api import _extract_products_list
    assert _extract_products_list({"count": 0}) == []


def test_extract_products_list_non_dict_input_returns_empty():
    from modules.food_database_api import _extract_products_list
    assert _extract_products_list(None) == []
    assert _extract_products_list("not a dict") == []
    assert _extract_products_list([1, 2, 3]) == []


def test_search_uses_alternate_response_key_transparently():
    """End-to-end: if the SDK ever returns 'hits' instead of 'products',
    search results should still come through correctly."""
    mock_api = _mock_api_with_search_result({"hits": [SAMPLE_PRODUCT_NO_SERVING_DATA]})
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        results = search_open_food_facts("oats")
    assert len(results) == 1
    assert results[0].name == "Rolled Oats"


# --------------------------------------------------------------------------- #
# Future-proofing: nutrient key aliasing
# --------------------------------------------------------------------------- #

def test_nutriment_alias_fallback_when_primary_key_renamed():
    """Simulates Open Food Facts renaming a nutrient key -- as long as an
    alias is registered, extraction should still work."""
    from modules.food_database_api import _nutriment
    # "energy-kcal_100g" missing, but the alias "energy_kcal_100g" present
    nutriments = {"energy_kcal_100g": 200}
    assert _nutriment(nutriments, "energy-kcal", use_serving=False) == 200


def test_nutriment_prefers_first_alias_when_multiple_present():
    from modules.food_database_api import _nutriment
    nutriments = {"energy-kcal_100g": 100, "energy_kcal_100g": 999}
    assert _nutriment(nutriments, "energy-kcal", use_serving=False) == 100


def test_nutriment_unknown_base_key_falls_back_to_itself():
    from modules.food_database_api import _nutriment
    nutriments = {"made_up_nutrient_100g": 42}
    assert _nutriment(nutriments, "made_up_nutrient", use_serving=False) == 42


def test_off_product_to_result_survives_renamed_nutrient_key():
    """Full pipeline test: a product using an aliased (non-primary)
    nutrient key spelling should still parse correctly."""
    product = {
        "product_name": "Renamed Key Item",
        "nutriments": {"energy_kcal_100g": 150, "protein_100g": 5},
    }
    result = _off_product_to_result(product)
    assert result.calories == 150
    assert result.protein_g == 5


# --------------------------------------------------------------------------- #
# Future-proofing: SDK method missing -> raw REST fallback
# --------------------------------------------------------------------------- #

def test_search_falls_back_to_raw_rest_when_sdk_method_missing():
    """Core future-proofing test: if a future SDK version removes/renames
    `api.product.text_search`, search should still work via the raw REST
    fallback rather than failing outright."""
    mock_api = MagicMock(spec=[])  # no attributes at all, including .product
    mock_api.product = MagicMock(spec=[])  # .product exists but has no text_search

    raw_response = MagicMock()
    raw_response.status_code = 200
    raw_response.raise_for_status.return_value = None
    raw_response.json.return_value = {"products": [SAMPLE_PRODUCT_NO_SERVING_DATA]}

    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True), \
         patch("modules.food_database_api.requests.get", return_value=raw_response) as mock_get:
        results = search_open_food_facts("oats")

    assert len(results) == 1
    assert results[0].name == "Rolled Oats"
    mock_get.assert_called_once()


def test_barcode_falls_back_to_raw_rest_when_sdk_method_missing():
    mock_api = MagicMock(spec=[])
    mock_api.product = MagicMock(spec=[])  # no .get method

    raw_response = MagicMock()
    raw_response.status_code = 200
    raw_response.raise_for_status.return_value = None
    raw_response.json.return_value = {"status": 1, "product": SAMPLE_PRODUCT_WITH_SERVING_DATA}

    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True), \
         patch("modules.food_database_api.requests.get", return_value=raw_response) as mock_get:
        result = fetch_product_by_barcode("0000000000001")

    assert result is not None
    assert result.name == "Greek Yogurt"
    mock_get.assert_called_once()


def test_search_raw_rest_fallback_failure_raises_clear_error():
    mock_api = MagicMock(spec=[])
    mock_api.product = MagicMock(spec=[])

    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True), \
         patch("modules.food_database_api.requests.get", side_effect=ConnectionError("no internet")):
        try:
            search_open_food_facts("oats")
            assert False, "should have raised"
        except OpenFoodFactsError:
            pass


def test_barcode_raw_rest_fallback_not_found_returns_none():
    mock_api = MagicMock(spec=[])
    mock_api.product = MagicMock(spec=[])

    raw_response = MagicMock()
    raw_response.status_code = 200
    raw_response.raise_for_status.return_value = None
    raw_response.json.return_value = {"status": 0}

    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True), \
         patch("modules.food_database_api.requests.get", return_value=raw_response):
        result = fetch_product_by_barcode("9999999999999")
    assert result is None


# --------------------------------------------------------------------------- #
# Future-proofing: SDK constructor signature drift
# --------------------------------------------------------------------------- #

def test_get_api_retries_without_timeout_if_constructor_signature_changed():
    """Simulates a future SDK version removing/renaming the 'timeout'
    constructor kwarg -- _get_api should retry with just user_agent."""
    import modules.food_database_api as fda_module
    fda_module._api_instance = None  # reset the module-level cache

    call_log = []

    def fake_api_constructor(*args, **kwargs):
        call_log.append(kwargs)
        if "timeout" in kwargs:
            raise TypeError("unexpected keyword argument 'timeout'")
        return MagicMock()

    with patch("modules.food_database_api.openfoodfacts.API", side_effect=fake_api_constructor):
        api = fda_module._get_api()

    assert api is not None
    assert len(call_log) == 2
    assert "timeout" in call_log[0]
    assert "timeout" not in call_log[1]
    fda_module._api_instance = None  # clean up for other tests


# --------------------------------------------------------------------------- #
# Future-proofing: SDK version compatibility check
# --------------------------------------------------------------------------- #

def test_check_sdk_compatibility_no_sdk_returns_none():
    with patch("modules.food_database_api._HAS_SDK", False):
        assert check_sdk_compatibility() is None


def test_check_sdk_compatibility_version_in_range_returns_none():
    mock_module = MagicMock()
    mock_module.__version__ = "5.2.0"
    with patch("modules.food_database_api.openfoodfacts", mock_module), \
         patch("modules.food_database_api._HAS_SDK", True):
        assert check_sdk_compatibility() is None


def test_check_sdk_compatibility_version_too_old_returns_warning():
    mock_module = MagicMock()
    mock_module.__version__ = "1.0.0"
    with patch("modules.food_database_api.openfoodfacts", mock_module), \
         patch("modules.food_database_api._HAS_SDK", True):
        warning = check_sdk_compatibility()
    assert warning is not None
    assert "1.0.0" in warning


def test_check_sdk_compatibility_missing_version_attr_returns_none():
    mock_module = MagicMock(spec=[])  # no __version__ attribute
    with patch("modules.food_database_api.openfoodfacts", mock_module), \
         patch("modules.food_database_api._HAS_SDK", True):
        assert check_sdk_compatibility() is None


def test_check_sdk_compatibility_unparseable_version_returns_none():
    mock_module = MagicMock()
    mock_module.__version__ = "not-a-version"
    with patch("modules.food_database_api.openfoodfacts", mock_module), \
         patch("modules.food_database_api._HAS_SDK", True):
        assert check_sdk_compatibility() is None


# --------------------------------------------------------------------------- #
# Retry-with-backoff for transient (429/503) errors
# --------------------------------------------------------------------------- #

def test_call_with_retry_succeeds_after_transient_failures():
    from modules.food_database_api import _call_with_retry

    call_count = {"n": 0}

    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise _http_error_with_status(503)
        return "success"

    with patch("modules.food_database_api.time.sleep") as mock_sleep:
        result = _call_with_retry(flaky)

    assert result == "success"
    assert call_count["n"] == 3
    assert mock_sleep.call_count == 2  # slept before each of the 2 retries


def test_call_with_retry_gives_up_after_max_retries():
    from modules.food_database_api import _call_with_retry, _MAX_TRANSIENT_RETRIES

    call_count = {"n": 0}

    def always_fails():
        call_count["n"] += 1
        raise _http_error_with_status(503)

    with patch("modules.food_database_api.time.sleep"):
        try:
            _call_with_retry(always_fails)
            assert False, "should have raised"
        except requests.exceptions.HTTPError:
            pass

    assert call_count["n"] == _MAX_TRANSIENT_RETRIES + 1


def test_call_with_retry_does_not_retry_non_transient_errors():
    from modules.food_database_api import _call_with_retry

    call_count = {"n": 0}

    def bad_request():
        call_count["n"] += 1
        raise _http_error_with_status(400)

    with patch("modules.food_database_api.time.sleep") as mock_sleep:
        try:
            _call_with_retry(bad_request)
            assert False, "should have raised"
        except requests.exceptions.HTTPError:
            pass

    assert call_count["n"] == 1  # no retries attempted
    mock_sleep.assert_not_called()


def test_call_with_retry_retries_on_429_too():
    from modules.food_database_api import _call_with_retry

    call_count = {"n": 0}

    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise _http_error_with_status(429)
        return "recovered"

    with patch("modules.food_database_api.time.sleep"):
        result = _call_with_retry(flaky)
    assert result == "recovered"


def test_search_retries_transparently_on_transient_error():
    """End-to-end: a search that fails once with 503 then succeeds
    should return results normally, without the caller seeing an error."""
    mock_api = MagicMock()
    call_count = {"n": 0}

    def flaky_search(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise _http_error_with_status(503)
        return SAMPLE_SEARCH_RESPONSE

    mock_api.product.text_search.side_effect = flaky_search
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        results = search_open_food_facts("yogurt")

    assert len(results) == 2
    assert call_count["n"] == 2


def test_search_exhausts_retries_then_raises_clear_error():
    mock_api = MagicMock()
    mock_api.product.text_search.side_effect = _http_error_with_status(503)
    with patch("modules.food_database_api._get_api", return_value=mock_api), \
         patch("modules.food_database_api._HAS_SDK", True):
        try:
            search_open_food_facts("yogurt")
            assert False, "should have raised"
        except OpenFoodFactsError as e:
            assert "503" in str(e)
    # Confirms retries were actually attempted (not an immediate failure)
    assert mock_api.product.text_search.call_count == 3
