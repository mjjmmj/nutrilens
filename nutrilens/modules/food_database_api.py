"""
food_database_api.py
=====================
Integration with Open Food Facts (https://world.openfoodfacts.org), a
free, open, community-maintained food product database covering millions
of products worldwide. No API key is required.

TRANSPORT NOTE (important, corrected from an earlier version of this
file): this module uses Open Food Facts' own officially-maintained
Python SDK (`pip install openfoodfacts`) rather than hand-rolled HTTP
calls to a specific endpoint URL. An earlier version of this file
described `/cgi/search.pl` as "effectively deprecated" based on a
third-party bug report; reading Open Food Facts' own API documentation
directly (openfoodfacts.github.io/openfoodfacts-server/api/) tells a more
precise story worth recording accurately:

- **Full-text search by product name has no v2/v3 REST replacement yet.**
  Open Food Facts' documentation explicitly states full-text search is
  not available in the v2/v3 server-side API; `/cgi/search.pl` (what the
  SDK's `text_search()` calls) remains the documented, currently-intended
  way to do it. The long-term replacement is "Search-a-licious" at
  search.openfoodfacts.org, which is still being rolled out and doesn't
  yet have a stable, fully-public API contract to build against safely.
- **This endpoint is explicitly rate-limited**: 10 requests/minute/IP
  for search queries, with an explicit warning not to use it for
  search-as-you-type. There's also a global, shared capacity cap
  ("irrespective of the IP address") -- Open Food Facts' own docs state
  plainly: "A HTTP 503 response (Service Not Available) will be returned
  if these limits are exceeded." So a 503 here is often a *documented,
  expected* rate-limit/load response, not evidence the endpoint is dead.
- Given that, this module (a) retries automatically on 429/503 with a
  short backoff, since Open Food Facts' own docs frame these as
  transient, and (b) relies on the calling UI to avoid firing redundant
  searches in the first place (see the "only search on an explicit
  button click, not on every rerun" fix in app.py -- a repeated/
  accidental search-as-you-type pattern is exactly what trips this limit
  fastest, and was an actual bug in an earlier version of this app).
- The official SDK is still used as the primary transport (rather than
  hand-rolling calls to `/cgi/search.pl` directly) because it's
  maintained by the Open Food Facts team itself, so if/when
  Search-a-licious matures into the documented replacement, the SDK is
  where that migration will land -- this app benefits automatically
  without needing to track a raw endpoint URL by hand.

======================================================================
FUTURE-PROOFING / MAINTENANCE NOTES -- read this if Open Food Facts
integration stops working or starts returning incomplete data:
======================================================================

This module defends against several classes of upstream change, each
with a fallback so a change degrades gracefully instead of breaking:

1. **SDK method signature/removal.** If a future major version of the
   `openfoodfacts` package renames or removes `api.product.text_search`
   or `api.product.get`, this module catches that (`AttributeError`/
   `TypeError`) and falls back to a raw REST call against the same
   endpoints the SDK itself uses internally (`_raw_rest_search` /
   `_raw_rest_get_by_barcode`). This is a last-resort safety net, not
   the primary path -- prefer keeping the SDK dependency up to date.

2. **Response shape changes.** `_extract_products_list()` tries a few
   plausible top-level key names ("products", "hits", "results") rather
   than assuming "products" forever -- Open Food Facts' search backend
   migration (see TRANSPORT NOTE) could plausibly change this.

3. **Nutrient field renames.** `_NUTRIENT_KEY_ALIASES` maps each nutrient
   this app cares about to a list of plausible key spellings, tried in
   order. If Open Food Facts renames a nutrient key (e.g.
   "energy-kcal" -> "energy_kcal"), add the new spelling to the front of
   that nutrient's alias list rather than needing to change the
   extraction logic itself.

4. **SDK version drift.** `check_sdk_compatibility()` does a soft,
   non-blocking check of the installed SDK version against the range
   this module was built/tested against, returning a warning string the
   UI can optionally surface -- it never blocks functionality, since a
   newer SDK version is usually fine.

Design goals:
- Never crash the app: every call is wrapped, and failures are
  distinguished so the UI can show something actionable:
    - "genuinely no results" (a valid response, just nothing matched) is
      a normal return of an empty list / None.
    - anything that actually *failed* (network error, timeout, rate
      limit, server error) raises `OpenFoodFactsError` with a specific,
      user-facing message -- these used to be silently collapsed into
      the same generic "no matches" message, which made a rate-limit or
      outage indistinguishable from a real empty search.
- UI-independent: fully unit-testable by mocking the SDK's `API` object
  (see tests/test_food_database_api.py) -- no live network needed to
  test the parsing/error-handling/fallback logic, and no flakiness from
  a third-party service's uptime.
- Data quality caveat: Open Food Facts is crowd-sourced. Values are
  generally reliable for well-known branded products but can be missing,
  inconsistent, or occasionally wrong for less common items -- exactly
  like OCR, the app treats this as a starting point for the user to
  review, not an authoritative source.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

try:
    import openfoodfacts
    _HAS_SDK = True
except ImportError:
    _HAS_SDK = False

# Open Food Facts asks integrators to use a descriptive User-Agent in the
# form "AppName/Version (ContactEmail)" so they can identify traffic and
# get in touch if there's an issue -- see
# https://openfoodfacts.github.io/openfoodfacts-server/api/
# If you deploy this app yourself, consider replacing the contact email
# below with your own, per Open Food Facts' usage policy.
USER_AGENT = "NutriLens/1.0 (streamlit-nutrilens@example.com)"

SOURCE_NAME = "Open Food Facts"

# The version range this module was built and tested against. Not a
# hard requirement -- see check_sdk_compatibility() -- just informs a
# soft warning if the installed version is well outside this range,
# since that's when a breaking change is most plausible.
_SDK_TESTED_MIN_VERSION = (3, 0)
_SDK_TESTED_MAX_VERSION = (6, 999)

# Raw REST endpoints used only as a last-resort fallback if the SDK's
# methods are missing/renamed in a future major version -- see
# MAINTENANCE note #1 above. These mirror what the SDK itself calls
# internally as of this writing.
_LEGACY_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
_BARCODE_URL_TEMPLATE = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

_api_instance = None


class OpenFoodFactsError(Exception):
    """Raised when an Open Food Facts request genuinely fails (network
    error, timeout, rate limit, server error) -- as opposed to a
    successful request that simply found no matching products, which is
    represented by a normal empty list / None return instead."""


def check_sdk_compatibility() -> Optional[str]:
    """Soft, non-blocking check of the installed `openfoodfacts` SDK
    version. Returns a warning string if it looks like it could be
    meaningfully newer/older than what this module was tested against,
    or None if there's nothing to flag. Never raises, and a warning here
    doesn't mean anything is actually broken -- just a hint of where to
    look first if something is."""
    if not _HAS_SDK:
        return None
    version_str = getattr(openfoodfacts, "__version__", None)
    if not version_str:
        return None
    try:
        parts = tuple(int(p) for p in version_str.split(".")[:2])
    except ValueError:
        return None
    if parts < _SDK_TESTED_MIN_VERSION or parts > _SDK_TESTED_MAX_VERSION:
        return (
            f"The installed 'openfoodfacts' SDK version ({version_str}) is "
            f"outside the range this integration was tested against "
            f"({_SDK_TESTED_MIN_VERSION[0]}.{_SDK_TESTED_MIN_VERSION[1]} - "
            f"{_SDK_TESTED_MAX_VERSION[0]}.x). It will likely still work, "
            "but if Open Food Facts search/lookup misbehaves, this "
            "version gap is a good first thing to check."
        )
    return None


def _get_api():
    """Lazily construct a single shared SDK client instance."""
    global _api_instance
    if _api_instance is None:
        try:
            _api_instance = openfoodfacts.API(user_agent=USER_AGENT, timeout=15)
        except TypeError:
            # Constructor signature changed in a future SDK version (e.g.
            # 'timeout' renamed/removed) -- retry with just the one
            # argument we're confident about rather than failing outright.
            _api_instance = openfoodfacts.API(user_agent=USER_AGENT)
    return _api_instance


def _describe_request_failure(exc: Exception) -> str:
    """Turn a low-level exception into a specific, actionable message."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 429:
        return (
            "Open Food Facts rate limit reached (HTTP 429). It allows a "
            "limited number of searches per minute -- wait a moment and "
            "try again."
        )
    if status_code == 503:
        return (
            "Open Food Facts is temporarily unavailable (HTTP 503) -- "
            "this can happen during peak load or service migrations. "
            "Try again shortly."
        )
    if status_code is not None:
        return f"Open Food Facts request failed (HTTP {status_code})."
    if isinstance(exc, requests.exceptions.Timeout):
        return "Open Food Facts request timed out. Check your connection and try again."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Couldn't reach Open Food Facts -- check your internet connection."
    return f"Open Food Facts request failed ({exc})."


# Open Food Facts' own API docs state that HTTP 429/503 from the search
# endpoint reflect rate-limiting / temporary capacity limits rather than
# a hard failure (see TRANSPORT NOTE above), so a couple of short,
# automatic retries is a reasonable, documented-appropriate mitigation
# before surfacing an error to the person.
_MAX_TRANSIENT_RETRIES = 2
_RETRY_BACKOFF_SECONDS = [1.5, 3.0]


def _is_transient_status(exc: Exception) -> bool:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    return status_code in (429, 503)


def _call_with_retry(fn, *args, **kwargs):
    """Call `fn`, retrying up to `_MAX_TRANSIENT_RETRIES` times with a
    short backoff if it raises an exception carrying a 429/503 HTTP
    status. Any other exception (or exhausting the retries) propagates
    immediately -- this is deliberately narrow so it doesn't mask or
    delay surfacing genuine errors (bad request, not found, network down)."""
    last_exc = None
    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if _is_transient_status(exc) and attempt < _MAX_TRANSIENT_RETRIES:
                time.sleep(_RETRY_BACKOFF_SECONDS[attempt])
                continue
            raise
    raise last_exc  # pragma: no cover -- unreachable, defensive only


# --------------------------------------------------------------------------- #
# Raw REST fallbacks (used only if the SDK's methods are missing/renamed)
# --------------------------------------------------------------------------- #

def _raw_rest_search(query: str, page_size: int) -> dict:
    response = requests.get(
        _LEGACY_SEARCH_URL,
        params={
            "search_terms": query, "search_simple": 1, "action": "process",
            "json": 1, "page_size": page_size,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _raw_rest_get_by_barcode(barcode: str) -> Optional[dict]:
    response = requests.get(
        _BARCODE_URL_TEMPLATE.format(barcode=barcode),
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != 1:
        return None
    return data.get("product") or {}


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

    # Which of the numeric fields above were actually present in Open
    # Food Facts' data (as opposed to defaulted to 0.0 because the field
    # was missing). Used by the UI to highlight auto-filled values versus
    # ones the person should double-check/fill in themselves.
    present_fields: set = field(default_factory=set)


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


# Each nutrient this app reads maps to a list of plausible key spellings
# in Open Food Facts' `nutriments` dict, tried in order (see MAINTENANCE
# note #3 above). The first entry is the current documented spelling;
# add new ones to the front if Open Food Facts renames a field.
_NUTRIENT_KEY_ALIASES = {
    "energy-kcal": ["energy-kcal", "energy_kcal", "energy-kcal_value", "energy"],
    "carbohydrates": ["carbohydrates", "carbohydrate"],
    "fiber": ["fiber", "dietary-fiber", "dietary_fiber"],
    "sugars": ["sugars", "sugar"],
    "proteins": ["proteins", "protein"],
    "fat": ["fat", "fats", "total-fat"],
    "saturated-fat": ["saturated-fat", "saturated_fat"],
    "trans-fat": ["trans-fat", "trans_fat"],
    "sodium": ["sodium"],
    "cholesterol": ["cholesterol"],
}


def _nutriment(nutriments: dict, base_key: str, use_serving: bool) -> Optional[float]:
    """Read a nutrient value from OFF's `nutriments` dict, preferring the
    already-per-serving value when available and requested, falling back
    to the per-100g value otherwise. Tries each known alias spelling for
    the nutrient in turn (see _NUTRIENT_KEY_ALIASES)."""
    for alias in _NUTRIENT_KEY_ALIASES.get(base_key, [base_key]):
        if use_serving:
            val = nutriments.get(f"{alias}_serving")
            if val is not None:
                return val
        val = nutriments.get(f"{alias}_100g")
        if val is not None:
            return val
    return None


def _extract_products_list(data) -> list:
    """Defensively find the list of product dicts in a search response,
    trying a couple of plausible alternate top-level key names in case
    the underlying search backend/response shape changes (see
    MAINTENANCE note #2 above) -- rather than assuming "products" is the
    only possible key forever."""
    if not isinstance(data, dict):
        return []
    for key in ("products", "hits", "results"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    return []


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

    present: set = set()
    if use_serving:
        present.add("serving_size_g")

    def get(base_key: str, result_field_name: str) -> float:
        val = _nutriment(nutriments, base_key, use_serving)
        if val is None:
            return 0.0
        try:
            value = float(val)
        except (TypeError, ValueError):
            return 0.0
        present.add(result_field_name)
        return value

    brand = None
    brands_field = product.get("brands")
    if isinstance(brands_field, str) and brands_field.strip():
        brand = brands_field.split(",")[0].strip()
        present.add("brand")

    category = _clean_category(product)
    if category:
        present.add("category")

    # OFF reports sodium and cholesterol per-100g/serving in grams, like
    # every other nutrient; our schema stores them in mg for readability
    # and consistency with US label conventions, so convert here. Kept
    # unrounded until after the x1000 conversion -- these are often very
    # small gram values (e.g. 0.054g), and rounding to 2dp beforehand
    # would silently zero out real precision (0.054 -> 0.05 -> 50mg
    # instead of the correct 54mg).
    sodium_g = get("sodium", "sodium_mg")
    cholesterol_g = get("cholesterol", "cholesterol_mg")

    return ExternalFoodResult(
        name=str(name).strip(),
        brand=brand,
        category=category,
        barcode=product.get("code") or None,
        serving_size_g=serving_g if use_serving and serving_g else 100.0,
        calories=round(get("energy-kcal", "calories"), 1),
        total_carbs_g=round(get("carbohydrates", "total_carbs_g"), 2),
        fiber_g=round(get("fiber", "fiber_g"), 2),
        sugars_g=round(get("sugars", "sugars_g"), 2),
        protein_g=round(get("proteins", "protein_g"), 2),
        total_fat_g=round(get("fat", "total_fat_g"), 2),
        saturated_fat_g=round(get("saturated-fat", "saturated_fat_g"), 2),
        trans_fat_g=round(get("trans-fat", "trans_fat_g"), 2),
        cholesterol_mg=round(cholesterol_g * 1000, 1),
        sodium_mg=round(sodium_g * 1000, 1),
        present_fields=present,
    )


def search_open_food_facts(query: str, page_size: int = 10) -> list:
    """Search Open Food Facts by free-text product name.

    Returns a list of ExternalFoodResult -- an empty list means the
    search genuinely succeeded but found no matches. Raises
    OpenFoodFactsError if the request itself failed (network error,
    timeout, rate limit, server error, or the SDK isn't installed), so
    the UI can tell the two situations apart instead of showing the same
    unhelpful "no results" message either way.

    Falls back to a raw REST call if the installed SDK's `text_search`
    method is missing (e.g. renamed/removed in a future major version) --
    see MAINTENANCE note #1 at the top of this file.
    """
    if not query or not query.strip():
        return []

    clamped_page_size = max(1, min(page_size, 50))

    if not _HAS_SDK:
        raise OpenFoodFactsError(
            "The 'openfoodfacts' package isn't installed. Add "
            "`openfoodfacts` to requirements.txt and reinstall."
        )

    try:
        api = _get_api()
        if not hasattr(api.product, "text_search"):
            raise AttributeError("SDK's product.text_search method not found")
        data = _call_with_retry(api.product.text_search, query.strip(), page_size=clamped_page_size)
    except AttributeError:
        try:
            data = _call_with_retry(_raw_rest_search, query.strip(), clamped_page_size)
        except Exception as exc:
            raise OpenFoodFactsError(_describe_request_failure(exc)) from exc
    except Exception as exc:
        raise OpenFoodFactsError(_describe_request_failure(exc)) from exc

    products = _extract_products_list(data)
    results = []
    for product in products:
        result = _off_product_to_result(product)
        if result:
            results.append(result)
    return results


def fetch_product_by_barcode(barcode: str) -> Optional[ExternalFoodResult]:
    """Look up a single product by exact barcode (UPC/EAN).

    Returns None if the barcode genuinely isn't found (a successful
    request with no match). Raises OpenFoodFactsError if the request
    itself failed (network error, timeout, rate limit, server error, or
    the SDK isn't installed).

    Falls back to a raw REST call if the installed SDK's `get` method is
    missing (e.g. renamed/removed in a future major version) -- see
    MAINTENANCE note #1 at the top of this file.
    """
    if not barcode or not barcode.strip():
        return None

    if not _HAS_SDK:
        raise OpenFoodFactsError(
            "The 'openfoodfacts' package isn't installed. Add "
            "`openfoodfacts` to requirements.txt and reinstall."
        )

    try:
        api = _get_api()
        if not hasattr(api.product, "get"):
            raise AttributeError("SDK's product.get method not found")
        product = _call_with_retry(api.product.get, barcode.strip())
    except AttributeError:
        try:
            product = _call_with_retry(_raw_rest_get_by_barcode, barcode.strip())
        except Exception as exc:
            raise OpenFoodFactsError(_describe_request_failure(exc)) from exc
    except Exception as exc:
        raise OpenFoodFactsError(_describe_request_failure(exc)) from exc

    if not product:
        return None

    return _off_product_to_result(product)

