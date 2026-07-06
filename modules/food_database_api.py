"""
food_database_api.py
=====================
Integration with Open Food Facts (https://world.openfoodfacts.org), a
free, open, community-maintained food product database covering millions
of products worldwide. No API key is required.

Design goals:
- Never crash the app: every network call is wrapped and returns an empty
  result ([] or None) on any failure (no internet, timeout, malformed
  response, product not found), so the UI can fall back to manual entry
  or OCR.
- UI-independent: plain `requests` calls + parsing, fully unit-testable
  by mocking `requests.get` with realistic sample JSON (see
  tests/test_food_database_api.py) -- no live network needed to test the
  parsing logic, and no flakiness from a third-party service's uptime.
- Data quality caveat: Open Food Facts is crowd-sourced. Values are
  generally reliable for well-known branded products but can be missing,
  inconsistent, or occasionally wrong for less common items -- exactly
  like OCR, the app treats this as a starting point for the user to
  review, not an authoritative source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests

SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
BARCODE_URL_TEMPLATE = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
REQUEST_TIMEOUT_SECONDS = 8
USER_AGENT = "NutriLens/1.0 (Streamlit nutrition-label app)"

SOURCE_NAME = "Open Food Facts"


@dataclass
class ExternalFoodResult:
    """A food record fetched from an external public database, shaped to
    map directly onto the app's NutritionFacts / FoodEntry fields."""

    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    barcode: Optional[str] = None
    serving_size_g: float = 100.0
    calories: float = 0.0
    total_carbs_g: float = 0.0
    fiber_g: float = 0.0
    sugars_g: float = 0.0
    protein_g: float = 0.0
    total_fat_g: float = 0.0
    saturated_fat_g: float = 0.0
    trans_fat_g: float = 0.0
    cholesterol_mg: float = 0.0
    sodium_mg: float = 0.0
    source: str = SOURCE_NAME


def _extract_serving_grams(serving_size_str: Optional[str]) -> Optional[float]:
    """Parse Open Food Facts' free-text `serving_size` field (e.g.
    "30 g", "1 cup (240ml)", "250ml") into a gram value. Milliliters are
    treated as grams (density ~1), a reasonable approximation for most
    foods/beverages and consistent with how this app treats serving sizes
    elsewhere; it will be somewhat off for very dense or airy items."""
    if not serving_size_str:
        return None
    match = re.search(r"([\d]+(?:\.\d+)?)\s*(?:g|ml)\b", serving_size_str.lower())
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _nutriment(nutriments: dict, base_key: str, use_serving: bool) -> Optional[float]:
    """Read a nutrient value from OFF's `nutriments` dict, preferring the
    already-per-serving value when available and requested, falling back
    to the per-100g value otherwise."""
    if use_serving:
        val = nutriments.get(f"{base_key}_serving")
        if val is not None:
            return val
    return nutriments.get(f"{base_key}_100g")


def _clean_category(product: dict) -> Optional[str]:
    """Open Food Facts categories are noisy free-text/tag lists (e.g.
    'en:yogurts, en:fermented-foods'); take the first one and clean it up
    into something reasonable for our category field."""
    tags = product.get("categories_tags")
    if isinstance(tags, list) and tags:
        first = tags[0]
        first = re.sub(r"^[a-z]{2}:", "", first)  # strip locale prefix, e.g. "en:"
        return first.replace("-", " ").strip().title() or None

    raw = product.get("categories")
    if isinstance(raw, str) and raw.strip():
        return raw.split(",")[0].strip().title()

    return None


def _off_product_to_result(product: dict) -> Optional[ExternalFoodResult]:
    """Convert one Open Food Facts product JSON object into an
    ExternalFoodResult. Returns None if the product has no usable name
    (a handful of low-quality community entries are missing even that)."""
    name = (
        product.get("product_name")
        or product.get("product_name_en")
        or product.get("generic_name")
    )
    if not name or not str(name).strip():
        return None

    nutriments = product.get("nutriments") or {}
    serving_g = _extract_serving_grams(product.get("serving_size"))
    has_serving_values = any(k.endswith("_serving") for k in nutriments)
    use_serving = bool(has_serving_values and serving_g)

    def get(base_key: str) -> float:
        val = _nutriment(nutriments, base_key, use_serving)
        try:
            return float(val) if val is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    brand = None
    brands_field = product.get("brands")
    if isinstance(brands_field, str) and brands_field.strip():
        brand = brands_field.split(",")[0].strip()

    # OFF reports sodium and cholesterol per-100g/serving in grams, like
    # every other nutrient; our schema stores them in mg for readability
    # and consistency with US label conventions, so convert here. Kept
    # unrounded until after the x1000 conversion -- these are often very
    # small gram values (e.g. 0.054g), and rounding to 2dp beforehand
    # would silently zero out real precision (0.054 -> 0.05 -> 50mg
    # instead of the correct 54mg).
    sodium_g = get("sodium")
    cholesterol_g = get("cholesterol")

    return ExternalFoodResult(
        name=str(name).strip(),
        brand=brand,
        category=_clean_category(product),
        barcode=product.get("code") or None,
        serving_size_g=serving_g if use_serving and serving_g else 100.0,
        calories=round(get("energy-kcal"), 1),
        total_carbs_g=round(get("carbohydrates"), 2),
        fiber_g=round(get("fiber"), 2),
        sugars_g=round(get("sugars"), 2),
        protein_g=round(get("proteins"), 2),
        total_fat_g=round(get("fat"), 2),
        saturated_fat_g=round(get("saturated-fat"), 2),
        trans_fat_g=round(get("trans-fat"), 2),
        cholesterol_mg=round(cholesterol_g * 1000, 1),
        sodium_mg=round(sodium_g * 1000, 1),
    )


def search_open_food_facts(query: str, page_size: int = 10) -> list:
    """Search Open Food Facts by free-text product name. Returns a list
    of ExternalFoodResult, or an empty list on no matches, network
    failure, or an unparseable response -- never raises."""
    if not query or not query.strip():
        return []

    params = {
        "search_terms": query.strip(),
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": max(1, min(page_size, 50)),
    }
    try:
        response = requests.get(
            SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    products = data.get("products") or []
    results = []
    for product in products:
        result = _off_product_to_result(product)
        if result:
            results.append(result)
    return results


def fetch_product_by_barcode(barcode: str) -> Optional[ExternalFoodResult]:
    """Look up a single product by exact barcode (UPC/EAN). Returns None
    if not found, on network failure, or on an unparseable response --
    never raises."""
    if not barcode or not barcode.strip():
        return None

    url = BARCODE_URL_TEMPLATE.format(barcode=barcode.strip())
    try:
        response = requests.get(
            url, timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    if data.get("status") != 1:
        return None

    return _off_product_to_result(data.get("product") or {})
