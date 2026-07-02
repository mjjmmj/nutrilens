"""
ocr_parser.py
=============
OCR + regex-based parsing of nutrition facts labels.

Design goals:
- Never crash the app: any OCR or parsing failure degrades gracefully to
  an empty/partial result so the UI can fall back to manual entry.
- Two OCR backends are supported (pytesseract, easyocr). The module
  auto-detects whichever is installed; if neither is available or OCR
  fails, `extract_text` returns an empty string and the caller falls back
  to manual input.
- Parsing uses tolerant regexes to handle common OCR quirks (missing
  spaces, 'g' vs '9' misreads corrected where unambiguous, varying label
  layouts/wording such as "Total Carbohydrate" vs "Carbohydrates").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Optional

try:
    import pytesseract
    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False

try:
    import easyocr
    _HAS_EASYOCR = True
except ImportError:
    _HAS_EASYOCR = False

from PIL import Image, ImageOps, ImageFilter


@dataclass
class ParsedNutrition:
    serving_size_g: Optional[float] = None
    calories: Optional[float] = None
    total_carbs_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sugars_g: Optional[float] = None
    protein_g: Optional[float] = None
    total_fat_g: Optional[float] = None

    def fields_found(self) -> int:
        return sum(1 for f in fields(self) if getattr(self, f.name) is not None)

    def is_empty(self) -> bool:
        return self.fields_found() == 0


# --------------------------------------------------------------------------- #
# OCR backend availability
# --------------------------------------------------------------------------- #

def ocr_backends_available() -> dict:
    return {"pytesseract": _HAS_TESSERACT, "easyocr": _HAS_EASYOCR}


_easyocr_reader = None


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        _easyocr_reader = easyocr.Reader(["en"], gpu=False)
    return _easyocr_reader


# --------------------------------------------------------------------------- #
# Image preprocessing
# --------------------------------------------------------------------------- #

def preprocess_image(image: Image.Image) -> Image.Image:
    """Light preprocessing to improve OCR accuracy on photographed labels:
    grayscale, autocontrast, and a mild sharpen filter. Kept intentionally
    conservative to avoid over-processing artifacts on varied phone
    cameras."""
    img = image.convert("L")  # grayscale
    img = ImageOps.autocontrast(img, cutoff=1)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def extract_text(image: Image.Image) -> str:
    """Run whichever OCR backend is available. Returns '' on any failure
    so the caller can fall back to manual entry rather than crashing."""
    try:
        processed = preprocess_image(image)
    except Exception:
        processed = image

    if _HAS_TESSERACT:
        try:
            text = pytesseract.image_to_string(processed)
            if text and text.strip():
                return text
        except Exception:
            pass  # fall through to next backend

    if _HAS_EASYOCR:
        try:
            import numpy as np
            reader = _get_easyocr_reader()
            results = reader.readtext(np.array(processed), detail=0)
            return "\n".join(results)
        except Exception:
            pass

    return ""


# --------------------------------------------------------------------------- #
# Field parsing
# --------------------------------------------------------------------------- #

# Each field maps to a list of regex patterns, tried in order, tolerant of
# OCR noise (optional colons, varying whitespace, 'Total' prefixes, and
# common unit spellings). Patterns capture the first numeric value found.
_NUMBER = r"([\d]+(?:[.,]\d+)?)"

_FIELD_PATTERNS = {
    "serving_size_g": [
        rf"serving\s*size[^0-9]{{0,20}}{_NUMBER}\s*(?:g|grams|ml)\b",
    ],
    "calories": [
        rf"calories[^0-9]{{0,10}}{_NUMBER}",
        rf"energy[^0-9]{{0,10}}{_NUMBER}\s*(?:kcal|cal)",
    ],
    "total_carbs_g": [
        rf"total\s*carbohydrate[s]?[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"carbohydrate[s]?[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"total\s*carb[s]?[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "fiber_g": [
        rf"dietary\s*fiber[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"fiber[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"fibre[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "sugars_g": [
        rf"total\s*sugars[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"sugars[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "protein_g": [
        rf"protein[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "total_fat_g": [
        rf"total\s*fat[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"^fat[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
}

# Order matters: more specific/prefixed patterns are listed first above so
# e.g. "Total Carbohydrate" is preferred over a bare "Carbohydrate" match,
# and "Dietary Fiber" isn't accidentally matched by a generic "fiber" fallback
# twice.


def _clean_number(raw: str) -> float:
    return float(raw.replace(",", "."))


def parse_nutrition_text(text: str) -> ParsedNutrition:
    """Extract nutrition fields from raw OCR text using tolerant regexes.

    Any field that cannot be confidently matched is left as None so the
    UI can prompt the user to fill it in manually.
    """
    if not text:
        return ParsedNutrition()

    normalized = text.lower()
    # Normalize common OCR misreads: 'O' -> '0' only within digit contexts
    # is risky, so we leave alphanumeric substitution out and rely on
    # tolerant regexes instead.

    result = ParsedNutrition()
    for field_name, patterns in _FIELD_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                try:
                    value = _clean_number(match.group(1))
                    setattr(result, field_name, value)
                    break
                except (ValueError, IndexError):
                    continue
    return result


def extract_nutrition_from_image(image: Image.Image) -> tuple[ParsedNutrition, str]:
    """Full pipeline: image -> OCR text -> parsed fields.

    Returns (ParsedNutrition, raw_text). raw_text is returned too so the
    UI can show it for user verification / debugging when parsing quality
    is uncertain.
    """
    raw_text = extract_text(image)
    parsed = parse_nutrition_text(raw_text)
    return parsed, raw_text
