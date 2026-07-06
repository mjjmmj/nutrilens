"""
ocr_parser.py
=============
OCR + regex-based parsing of nutrition facts labels, in English and
Japanese.

Design goals:
- Never crash the app: any OCR or parsing failure degrades gracefully to
  an empty/partial result so the UI can fall back to manual entry.
- Work on *real phone-camera photos*, not just clean scans: this means
  correcting EXIF rotation (phones tag orientation instead of rotating
  pixels), and coping with uneven lighting, glare, and shadows. A single
  fixed preprocessing recipe is not robust enough across devices and
  lighting conditions, so this module generates a few different
  preprocessed variants of the same photo, OCRs each one, and keeps
  whichever result actually parses the most nutrition fields.
- Two OCR backends are supported (pytesseract, easyocr), both configured
  for combined English + Japanese recognition. If neither is available or
  OCR fails entirely, extraction returns an empty string and the caller
  falls back to manual entry.
- Parsing uses tolerant regexes for both English and Japanese label
  wording, and normalizes full-width (Japanese input method) digits and
  punctuation to standard ASCII before matching.
"""

from __future__ import annotations

import re
import unicodedata
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

import numpy as np
from PIL import Image, ImageOps, ImageFilter

# Languages passed to each OCR backend. Tesseract uses '+'-joined language
# codes; EasyOCR takes a list. Both are configured for combined
# English + Japanese recognition so labels in either language (or a mix,
# common on imported products) are read in a single pass.
_TESSERACT_LANGS = "eng+jpn"
_EASYOCR_LANGS = ["en", "ja"]


@dataclass
class ParsedNutrition:
    serving_size_g: Optional[float] = None
    calories: Optional[float] = None
    total_carbs_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sugars_g: Optional[float] = None
    protein_g: Optional[float] = None
    total_fat_g: Optional[float] = None

    # Extended nutrient panel -- same "not used in predictions, but
    # captured because it's on the label" rationale as NutritionFacts.
    saturated_fat_g: Optional[float] = None
    trans_fat_g: Optional[float] = None
    cholesterol_mg: Optional[float] = None
    sodium_mg: Optional[float] = None
    added_sugars_g: Optional[float] = None
    vitamin_d_mcg: Optional[float] = None
    calcium_mg: Optional[float] = None
    iron_mg: Optional[float] = None
    potassium_mg: Optional[float] = None

    def fields_found(self) -> int:
        return sum(1 for f in fields(self) if getattr(self, f.name) is not None)

    def is_empty(self) -> bool:
        return self.fields_found() == 0


# --------------------------------------------------------------------------- #
# OCR backend availability
# --------------------------------------------------------------------------- #

def ocr_backends_available() -> dict:
    return {"pytesseract": _HAS_TESSERACT, "easyocr": _HAS_EASYOCR}


def tesseract_japanese_available() -> bool:
    """Check whether the Japanese trained-data file is installed alongside
    tesseract. Missing language data fails silently in some pytesseract
    versions (falls back to English-only), so the UI surfaces this
    explicitly rather than leaving the person guessing why Japanese text
    isn't being read."""
    if not _HAS_TESSERACT:
        return False
    try:
        return "jpn" in pytesseract.get_languages(config="")
    except Exception:
        return False


_easyocr_reader = None


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        _easyocr_reader = easyocr.Reader(_EASYOCR_LANGS, gpu=False)
    return _easyocr_reader


# --------------------------------------------------------------------------- #
# Image preprocessing
# --------------------------------------------------------------------------- #

_MAX_DIMENSION = 2200  # downscale huge phone-camera photos for speed/accuracy
_MIN_DIMENSION = 800   # upscale small/cropped images so text isn't too thin


def _fix_orientation_and_size(image: Image.Image) -> Image.Image:
    """Apply the photo's EXIF orientation tag (phones store rotation as
    metadata rather than rotating pixels, which silently defeats OCR on
    portrait photos) and normalize size for OCR."""
    try:
        image = ImageOps.exif_transpose(image) or image
    except Exception:
        pass
    image = image.convert("RGB")

    w, h = image.size
    longest = max(w, h)
    if longest > _MAX_DIMENSION:
        scale = _MAX_DIMENSION / longest
        image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    elif longest < _MIN_DIMENSION and longest > 0:
        scale = _MIN_DIMENSION / longest
        image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return image


def _otsu_binarize(gray_image: Image.Image) -> Image.Image:
    """Binarize using Otsu's method (automatic global threshold). Helps a
    lot on real photos with uneven lighting/glare where a fixed threshold
    would either wash out or block up the text."""
    arr = np.array(gray_image)
    histogram, _ = np.histogram(arr, bins=256, range=(0, 256))
    total = arr.size

    sum_total = np.dot(np.arange(256), histogram)
    sum_bg, weight_bg, max_variance, threshold = 0.0, 0, 0.0, 128
    for t in range(256):
        weight_bg += histogram[t]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += t * histogram[t]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        variance_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if variance_between > max_variance:
            max_variance = variance_between
            threshold = t

    return gray_image.point(lambda p: 255 if p > threshold else 0)


def _generate_preprocess_variants(image: Image.Image) -> list:
    """Produce a small set of differently-preprocessed versions of the
    same (orientation-corrected, size-normalized) photo. Real camera
    photos vary too much in lighting/glare/focus for one fixed recipe to
    reliably work, so multiple variants are OCR'd and the best-scoring
    result is kept (see `extract_text`)."""
    base = _fix_orientation_and_size(image)
    gray = ImageOps.grayscale(base)

    contrast_sharpened = ImageOps.autocontrast(gray, cutoff=1).filter(ImageFilter.SHARPEN)
    binarized = _otsu_binarize(ImageOps.autocontrast(gray, cutoff=1))

    return [contrast_sharpened, binarized, gray]


def preprocess_image(image: Image.Image) -> Image.Image:
    """Kept for backward compatibility / simple callers: returns the
    primary (contrast + sharpen) preprocessing variant only."""
    return _generate_preprocess_variants(image)[0]


# --------------------------------------------------------------------------- #
# OCR execution
# --------------------------------------------------------------------------- #

def _run_tesseract(image: Image.Image) -> str:
    return pytesseract.image_to_string(image, lang=_TESSERACT_LANGS)


def _run_easyocr(image: Image.Image) -> str:
    reader = _get_easyocr_reader()
    results = reader.readtext(np.array(image), detail=0)
    return "\n".join(results)


def _ocr_single_variant(image: Image.Image) -> str:
    """Run whichever OCR backend is available on one preprocessed image.
    Returns '' on any failure so callers can move on to the next variant
    or backend rather than crashing."""
    if _HAS_TESSERACT:
        try:
            text = _run_tesseract(image)
            if text and text.strip():
                return text
        except Exception:
            pass  # fall through to next backend

    if _HAS_EASYOCR:
        try:
            return _run_easyocr(image)
        except Exception:
            pass

    return ""


def _score_text(text: str) -> tuple:
    """Rank OCR results by how many nutrition fields they actually let us
    parse, then by raw text length as a tiebreaker/fallback signal."""
    parsed = parse_nutrition_text(text)
    return (parsed.fields_found(), len(text.strip()))


def extract_text(image: Image.Image) -> str:
    """Run OCR across multiple preprocessing variants of the image and
    return the text that yields the best parse. This is what makes
    real-world camera photos (uneven lighting, slight blur, glare)
    meaningfully more reliable than a single fixed preprocessing pass.
    Returns '' if OCR isn't available or every variant fails, so the
    caller can fall back to manual entry rather than crashing.
    """
    try:
        variants = _generate_preprocess_variants(image)
    except Exception:
        variants = [image]

    best_text = ""
    best_score = (-1, -1)
    for variant in variants:
        text = _ocr_single_variant(variant)
        score = _score_text(text)
        if score > best_score:
            best_score = score
            best_text = text

    return best_text


# --------------------------------------------------------------------------- #
# Text normalization
# --------------------------------------------------------------------------- #

def _normalize_text(text: str) -> str:
    """Convert full-width digits/letters/punctuation (common in
    Japanese-input-method text and some OCR output) to standard
    half-width ASCII equivalents, e.g. '３０ｇ' -> '30g'. Uses Unicode
    NFKC normalization, which is the standard approach for this."""
    return unicodedata.normalize("NFKC", text)


# --------------------------------------------------------------------------- #
# Field parsing
# --------------------------------------------------------------------------- #

# Each field maps to a list of regex patterns (English first, then
# Japanese), tried in order, tolerant of OCR noise (optional colons,
# varying whitespace, 'Total' prefixes, and common unit spellings).
# Patterns capture the first numeric value found. Text is normalized
# (full-width -> half-width, NFKC) and lowercased before matching, which
# is safe for Japanese since kanji/kana have no case.
_NUMBER = r"([\d]+(?:[.,]\d+)?)"


def _jp(phrase: str) -> str:
    """Build a regex fragment for a Japanese keyword that tolerates stray
    whitespace between *any* two characters. Tesseract's Japanese OCR
    frequently inserts spaces as word-segmentation artifacts (e.g.
    'エネルギー' comes out as 'エネ ルギー'), so a literal substring match
    against clean keywords misses real OCR output constantly. Escaping
    each character and joining with \\s* fixes this without needing a
    separate whitespace-stripping pass over the whole text (which would
    also strip meaningful spacing in mixed English/Japanese labels)."""
    return r"\s*".join(re.escape(ch) for ch in phrase)


_FIELD_PATTERNS = {
    "serving_size_g": [
        # English
        rf"serving\s*size[^0-9]{{0,20}}{_NUMBER}\s*(?:g|grams|ml)\b",
        # Japanese: "内容量 30g", "1食(30g)当たり", "100gあたり"
        rf"{_jp('内容量')}[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"{_NUMBER}\s*g.{{0,3}}?(?:{_jp('あたり')}|{_jp('当たり')})",
    ],
    "calories": [
        rf"calories[^0-9]{{0,10}}{_NUMBER}",
        rf"energy[^0-9]{{0,10}}{_NUMBER}\s*(?:kcal|cal)",
        # Japanese: "エネルギー 180kcal"
        rf"{_jp('エネルギー')}[^0-9]{{0,10}}{_NUMBER}",
    ],
    "total_carbs_g": [
        rf"total\s*carbohydrate[s]?[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"carbohydrate[s]?[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"total\s*carb[s]?[^0-9]{{0,10}}{_NUMBER}\s*g",
        # Japanese: "炭水化物 28g"
        rf"{_jp('炭水化物')}[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "fiber_g": [
        rf"dietary\s*fiber[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"fiber[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"fibre[^0-9]{{0,10}}{_NUMBER}\s*g",
        # Japanese: "食物繊維 4g"
        rf"{_jp('食物繊維')}[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "sugars_g": [
        rf"total\s*sugars[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"sugars[^0-9]{{0,10}}{_NUMBER}\s*g",
        # Japanese: "糖類 9g"  (NOT 糖質, which is carbs-excluding-fiber
        # and is handled separately below to help derive total carbs)
        rf"{_jp('糖類')}[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "protein_g": [
        rf"protein[^0-9]{{0,10}}{_NUMBER}\s*g",
        # Japanese: "たんぱく質 5g" (also accept the 蛋白質 kanji spelling)
        rf"{_jp('たんぱく質')}[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"{_jp('蛋白質')}[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "total_fat_g": [
        rf"total\s*fat[^0-9]{{0,10}}{_NUMBER}\s*g",
        rf"^fat[^0-9]{{0,10}}{_NUMBER}\s*g",
        # Japanese: "脂質 6g"
        rf"{_jp('脂質')}[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "saturated_fat_g": [
        rf"saturated\s*fat[^0-9]{{0,10}}{_NUMBER}\s*g",
        # Japanese: "飽和脂肪酸 2g"
        rf"{_jp('飽和脂肪酸')}[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "trans_fat_g": [
        rf"trans\s*fat[^0-9]{{0,10}}{_NUMBER}\s*g",
        # Japanese: "トランス脂肪酸 0g"
        rf"{_jp('トランス脂肪酸')}[^0-9]{{0,10}}{_NUMBER}\s*g",
    ],
    "cholesterol_mg": [
        rf"cholesterol[^0-9]{{0,10}}{_NUMBER}\s*mg",
        # Japanese: "コレステロール 5mg"
        rf"{_jp('コレステロール')}[^0-9]{{0,10}}{_NUMBER}\s*mg",
    ],
    "sodium_mg": [
        rf"sodium[^0-9]{{0,10}}{_NUMBER}\s*mg",
        # Japanese labels sometimes show sodium directly as ナトリウム,
        # though 食塩相当量 (salt equivalent) is far more common -- that's
        # handled as a gram-based fallback conversion below, since it's a
        # different unit/quantity (salt, not sodium) and needs converting.
        rf"{_jp('ナトリウム')}[^0-9]{{0,10}}{_NUMBER}\s*mg",
    ],
    "added_sugars_g": [
        # Most common OCR'd order: "Added Sugars 3g"
        rf"added\s*sugars[^0-9]{{0,10}}{_NUMBER}\s*g",
        # FDA sub-line format: "Includes 3g Added Sugars". 'includes' is
        # required (not optional) here -- without it, this pattern would
        # match across a line break and grab the number from an unrelated
        # preceding line (e.g. "Total Sugars 9g\nAdded Sugars 3g" could
        # otherwise misread the 9 as the added-sugars value, since \s*
        # matches newlines too).
        rf"includes\s*{_NUMBER}\s*g\s*added\s*sugars",
    ],
    "vitamin_d_mcg": [
        rf"vitamin\s*d[^0-9]{{0,10}}{_NUMBER}\s*(?:mcg|µg|μg|ug)",
        # Japanese: "ビタミンD 2.0μg"
        rf"{_jp('ビタミンd')}[^0-9]{{0,10}}{_NUMBER}\s*(?:mcg|µg|μg|ug)",
    ],
    "calcium_mg": [
        rf"calcium[^0-9]{{0,10}}{_NUMBER}\s*mg",
        # Japanese: "カルシウム 68mg"
        rf"{_jp('カルシウム')}[^0-9]{{0,10}}{_NUMBER}\s*mg",
    ],
    "iron_mg": [
        rf"iron[^0-9]{{0,10}}{_NUMBER}\s*mg",
        # Japanese: "鉄 0.1mg"
        rf"{_jp('鉄')}[^0-9]{{0,10}}{_NUMBER}\s*mg",
    ],
    "potassium_mg": [
        rf"potassium[^0-9]{{0,10}}{_NUMBER}\s*mg",
        # Japanese: "カリウム 150mg"
        rf"{_jp('カリウム')}[^0-9]{{0,10}}{_NUMBER}\s*mg",
    ],
}

# Japanese nutrition labels report sodium as 食塩相当量 ("salt equivalent",
# in grams) rather than sodium in mg. When no direct sodium_mg match was
# found, this pattern captures the salt-equivalent value so it can be
# converted: sodium(mg) = salt(g) / 2.54 * 1000. The 2.54 factor is the
# standard NaCl<->sodium conversion used on Japanese labels (salt = sodium
# x 2.54).
_SALT_EQUIVALENT_PATTERN = rf"{_jp('食塩相当量')}[^0-9]{{0,10}}{_NUMBER}\s*g"
_SALT_TO_SODIUM_FACTOR = 2.54

# Some Japanese labels break "carbohydrate" into two separate lines --
# 糖質 (carbs excluding fiber) and 食物繊維 (fiber) -- instead of printing
# a single 炭水化物 total. This pattern captures 糖質 specifically so
# parse_nutrition_text can derive total_carbs_g = 糖質 + 食物繊維 when no
# direct 炭水化物 total was found.
_CARBS_EX_FIBER_PATTERN = rf"{_jp('糖質')}[^0-9]{{0,10}}{_NUMBER}\s*g"


def _clean_number(raw: str) -> float:
    return float(raw.replace(",", "."))


def parse_nutrition_text(text: str) -> ParsedNutrition:
    """Extract nutrition fields from raw OCR text (English and/or
    Japanese) using tolerant regexes.

    Any field that cannot be confidently matched is left as None so the
    UI can prompt the user to fill it in manually.
    """
    if not text:
        return ParsedNutrition()

    normalized = _normalize_text(text).lower()

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

    # Fallback: derive total carbs from 糖質 (carbs excl. fiber) + fiber,
    # for Japanese labels that report the carbohydrate breakdown instead
    # of a single 炭水化物 total.
    if result.total_carbs_g is None:
        match = re.search(_CARBS_EX_FIBER_PATTERN, normalized, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            try:
                carbs_ex_fiber = _clean_number(match.group(1))
                result.total_carbs_g = round(carbs_ex_fiber + (result.fiber_g or 0.0), 1)
            except (ValueError, IndexError):
                pass

    # Fallback: Japanese labels report 食塩相当量 (salt equivalent, in
    # grams) instead of sodium in mg. Convert it when no direct sodium
    # value was already found.
    if result.sodium_mg is None:
        match = re.search(_SALT_EQUIVALENT_PATTERN, normalized, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            try:
                salt_g = _clean_number(match.group(1))
                result.sodium_mg = round(salt_g / _SALT_TO_SODIUM_FACTOR * 1000, 1)
            except (ValueError, IndexError):
                pass

    return result


def extract_nutrition_from_image(image: Image.Image) -> tuple:
    """Full pipeline: image -> OCR text -> parsed fields.

    Returns (ParsedNutrition, raw_text). raw_text is returned too so the
    UI can show it for user verification / debugging when parsing quality
    is uncertain.
    """
    raw_text = extract_text(image)
    parsed = parse_nutrition_text(raw_text)
    return parsed, raw_text
