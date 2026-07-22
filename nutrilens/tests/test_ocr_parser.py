import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PIL import Image, ImageOps
from modules.ocr_parser import (
    parse_nutrition_text,
    ParsedNutrition,
    _fix_orientation_and_size,
    _otsu_binarize,
    _generate_preprocess_variants,
)


SAMPLE_LABEL_CLEAN = """
Nutrition Facts
Serving Size 55g
Calories 220

Total Fat 8g
Total Carbohydrate 35g
Dietary Fiber 3g
Total Sugars 12g
Protein 5g
"""

SAMPLE_LABEL_NOISY = """
NUTRITI0N FACTS
serving size:  30 g
calories:190
total carbohydrates : 22g
fiber 2g
sugars9g
protein: 3 g
total fat:7g
"""

SAMPLE_LABEL_PARTIAL = """
Nutrition Facts
Calories 100
Protein 2g
"""

# Realistic clean Japanese label (栄養成分表示), all 7 fields present
SAMPLE_LABEL_JAPANESE_CLEAN = """
栄養成分表示
1食(40g)当たり
エネルギー 180kcal
たんぱく質 6g
脂質 6g
炭水化物 28g
糖類 9g
食物繊維 4g
"""

# Same label but with the stray spaces Tesseract's Japanese OCR commonly
# inserts between kanji/kana as word-segmentation artifacts
SAMPLE_LABEL_JAPANESE_OCR_NOISY = """
栄養 成分 表示
1 食 (40g) 当 た り
エネ ルギー 180kcal
た ん ぱく 質 6g
脂質 6g
炭水化物 28g

糖類 9g

食物 繊維 4g
"""

# Label reporting the carbohydrate breakdown (糖質 / 食物繊維) instead of a
# single 炭水化物 total -- common on Japanese labels
SAMPLE_LABEL_JAPANESE_CARB_BREAKDOWN = """
栄養成分表示
エネルギー 150kcal
たんぱく質 3g
脂質 5g
糖質 20g
食物繊維 2g
"""

# Full-width (Japanese IME style) digits and letters
SAMPLE_LABEL_FULLWIDTH = "エネルギー　１８０ｋｃａｌ\nたんぱく質　６ｇ\n脂質　６ｇ"

# A mixed English/Japanese label, as seen on some imported/bilingual products
SAMPLE_LABEL_MIXED = """
Nutrition Facts / 栄養成分表示
Serving Size 40g
Calories 180 / エネルギー 180kcal
Protein 6g / たんぱく質 6g
Total Fat 6g
Total Carbohydrate 28g
Dietary Fiber 4g
Total Sugars 9g
"""


def test_parse_clean_label_all_fields():
    result = parse_nutrition_text(SAMPLE_LABEL_CLEAN)
    assert result.serving_size_g == 55
    assert result.calories == 220
    assert result.total_fat_g == 8
    assert result.total_carbs_g == 35
    assert result.fiber_g == 3
    assert result.sugars_g == 12
    assert result.protein_g == 5
    assert result.fields_found() == 7


def test_parse_noisy_label_tolerant_spacing():
    result = parse_nutrition_text(SAMPLE_LABEL_NOISY)
    assert result.serving_size_g == 30
    assert result.calories == 190
    assert result.total_carbs_g == 22
    assert result.fiber_g == 2
    assert result.protein_g == 3
    assert result.total_fat_g == 7


def test_parse_partial_label_missing_fields_are_none():
    result = parse_nutrition_text(SAMPLE_LABEL_PARTIAL)
    assert result.calories == 100
    assert result.protein_g == 2
    assert result.total_carbs_g is None
    assert result.fiber_g is None
    assert result.fields_found() == 2
    assert not result.is_empty()


def test_parse_empty_text_returns_empty_result():
    result = parse_nutrition_text("")
    assert result.is_empty()
    assert result.fields_found() == 0


def test_parse_garbage_text_no_crash():
    garbage = "asdkjfh 92834 !!! %%% \n\n random OCR noise ###"
    result = parse_nutrition_text(garbage)
    # Should not crash; fields likely all None
    assert isinstance(result, ParsedNutrition)


def test_parse_decimal_values():
    text = "Calories 87.5\nProtein 2.5g\nTotal Fat 0.5g"
    result = parse_nutrition_text(text)
    assert result.calories == 87.5
    assert result.protein_g == 2.5
    assert result.total_fat_g == 0.5


def test_parse_comma_decimal_values():
    # Some European-formatted OCR text may render decimals with commas
    text = "Calories 87,5\nProtein 2,5g"
    result = parse_nutrition_text(text)
    assert result.calories == 87.5
    assert result.protein_g == 2.5


def test_prefers_total_carbohydrate_over_generic_fallback():
    text = "Total Carbohydrate 40g\nCarbohydrate 999g"
    result = parse_nutrition_text(text)
    assert result.total_carbs_g == 40


# --------------------------------------------------------------------------- #
# Japanese label parsing
# --------------------------------------------------------------------------- #

def test_parse_japanese_clean_label_all_fields():
    result = parse_nutrition_text(SAMPLE_LABEL_JAPANESE_CLEAN)
    assert result.serving_size_g == 40
    assert result.calories == 180
    assert result.protein_g == 6
    assert result.total_fat_g == 6
    assert result.total_carbs_g == 28
    assert result.sugars_g == 9
    assert result.fiber_g == 4
    assert result.fields_found() == 7


def test_parse_japanese_label_tolerant_of_ocr_spacing():
    # Tesseract's Japanese OCR frequently inserts spaces between
    # kanji/kana as word-segmentation artifacts; parsing must not break.
    result = parse_nutrition_text(SAMPLE_LABEL_JAPANESE_OCR_NOISY)
    assert result.serving_size_g == 40
    assert result.calories == 180
    assert result.protein_g == 6
    assert result.total_fat_g == 6
    assert result.total_carbs_g == 28
    assert result.sugars_g == 9
    assert result.fiber_g == 4
    assert result.fields_found() == 7


def test_parse_japanese_carb_breakdown_derives_total_carbs():
    # 糖質 (carbs excl. fiber) + 食物繊維 (fiber), no single 炭水化物 total
    result = parse_nutrition_text(SAMPLE_LABEL_JAPANESE_CARB_BREAKDOWN)
    assert result.calories == 150
    assert result.protein_g == 3
    assert result.total_fat_g == 5
    assert result.fiber_g == 2
    assert result.total_carbs_g == 22  # 20 + 2, derived


def test_parse_japanese_direct_total_takes_precedence_over_breakdown():
    # When both 炭水化物 (direct total) and 糖質 (breakdown component) are
    # present, the direct total should win rather than being overwritten
    # by the derived breakdown sum.
    text = "炭水化物 30g\n糖質 20g\n食物繊維 2g"
    result = parse_nutrition_text(text)
    assert result.total_carbs_g == 30


def test_parse_fullwidth_digits_normalized():
    result = parse_nutrition_text(SAMPLE_LABEL_FULLWIDTH)
    assert result.calories == 180
    assert result.protein_g == 6
    assert result.total_fat_g == 6


def test_parse_mixed_english_japanese_label():
    result = parse_nutrition_text(SAMPLE_LABEL_MIXED)
    assert result.serving_size_g == 40
    assert result.calories == 180
    assert result.protein_g == 6
    assert result.total_fat_g == 6
    assert result.total_carbs_g == 28
    assert result.fiber_g == 4
    assert result.sugars_g == 9


def test_parse_japanese_protein_kanji_variant():
    # Some labels use 蛋白質 instead of たんぱく質 for "protein"
    text = "エネルギー 100kcal\n蛋白質 4g"
    result = parse_nutrition_text(text)
    assert result.protein_g == 4


def test_parse_japanese_protein_tan_haku_variant():
    # Some labels use たん白質 (kanji 白 instead of hiragana ぱく) --
    # confirmed on a real product label
    text = "エネルギー 198kcal\nたん白質 9.1g"
    result = parse_nutrition_text(text)
    assert result.protein_g == 9.1


def test_parse_japanese_energy_as_netsuryou():
    # 熱量 ("amount of heat/energy") is an equally valid, real-world
    # alternate wording for calories, distinct from エネルギー -- some
    # brands (e.g. certain instant noodle cups) use this instead
    text = "熱量: 354kcal\nたんぱく質: 8.4g"
    result = parse_nutrition_text(text)
    assert result.calories == 354


def test_parse_japanese_energy_netsuryou_with_ocr_spacing():
    text = "熱 　 量: 354kcal"
    result = parse_nutrition_text(text)
    assert result.calories == 354


def test_parse_japanese_sodium_natrium_in_grams():
    # Some labels state ナトリウム (sodium) directly in grams rather than
    # mg -- confirmed on a real product label. Must convert g -> mg.
    text = "ナトリウム: 1.8g"
    result = parse_nutrition_text(text)
    assert result.sodium_mg == 1800.0


def test_parse_japanese_sodium_natrium_in_mg_still_works():
    # The pre-existing mg-based pattern must still take priority and
    # work correctly (not be broken by the new grams fallback)
    text = "ナトリウム: 140mg"
    result = parse_nutrition_text(text)
    assert result.sodium_mg == 140.0


def test_parse_japanese_sodium_mg_priority_over_grams_fallback():
    # If somehow both an mg-form and g-form value are present, the
    # direct mg match (found by the main pattern loop) must win over
    # the grams-based fallback
    text = "ナトリウム: 500mg\nナトリウム: 1.8g"
    result = parse_nutrition_text(text)
    assert result.sodium_mg == 500.0


def test_parse_japanese_vitamin_b1_b2():
    text = "ビタミンB1: 1.45mg\nビタミンB2: 0.25mg"
    result = parse_nutrition_text(text)
    assert result.vitamin_b1_mg == 1.45
    assert result.vitamin_b2_mg == 0.25


def test_parse_japanese_vitamin_b1_b2_with_ocr_spacing():
    text = "ビタ ミン B1: 1.45mg\nビタ ミン B2: 0.25mg"
    result = parse_nutrition_text(text)
    assert result.vitamin_b1_mg == 1.45
    assert result.vitamin_b2_mg == 0.25


def test_parse_real_label_1_nissin_style_cup_noodle():
    """Reconstructed verbatim from a real cup-noodle nutrition label:
    uses 熱量 (not エネルギー) for calories, 食塩相当量 for sodium, and
    includes Vitamin B1/B2 + calcium -- no fiber/sugars/fat-breakdown
    listed at all, which is normal and expected for this label."""
    text = """
    栄養成分表示 1食(76g)当たり
    熱量: 354kcal
    たんぱく質: 8.4g
    脂質: 15.4g
    炭水化物: 45.5g
    食塩相当量: 4.0g
    （めん・かやく1.7g）
    （スープ2.3g）
    ビタミンB1: 1.45mg
    ビタミンB2: 0.25mg
    カルシウム: 96mg
    """
    result = parse_nutrition_text(text)
    assert result.serving_size_g == 76
    assert result.calories == 354
    assert result.protein_g == 8.4
    assert result.total_fat_g == 15.4
    assert result.total_carbs_g == 45.5
    assert result.sodium_mg == round(4.0 / 2.54 * 1000, 1)
    assert result.vitamin_b1_mg == 1.45
    assert result.vitamin_b2_mg == 0.25
    assert result.calcium_mg == 96
    # Everything present on the real label was found
    assert result.fields_found() == 9


def test_parse_real_label_2_alternate_style_cup_noodle():
    """Reconstructed verbatim from a second real cup-noodle nutrition
    label: uses たん白質 (not たんぱく質) for protein, states ナトリウム
    directly in grams (not mg), and reports the carbohydrate breakdown
    (糖質 + 食物繊維) rather than a single 炭水化物 total."""
    text = """
    標準栄養成分表1食(53g)当たり
    エネルギー: 198kcal
    たん白質: 9.1g
    脂質: 4.7g
    糖質: 24.8g
    食物繊維: 10.2g
    ナトリウム: 1.8g
    （めん・かやく0.7g）
    （スープ1.1g）
    ビタミンB1: 0.12mg
    ビタミンB2: 0.16mg
    カルシウム: 94mg
    """
    result = parse_nutrition_text(text)
    assert result.serving_size_g == 53
    assert result.calories == 198
    assert result.protein_g == 9.1
    assert result.total_fat_g == 4.7
    assert result.fiber_g == 10.2
    assert result.total_carbs_g == 35.0  # 24.8 + 10.2, derived
    assert result.sodium_mg == 1800.0
    assert result.vitamin_b1_mg == 0.12
    assert result.vitamin_b2_mg == 0.16
    assert result.calcium_mg == 94
    assert result.fields_found() == 10


def test_parse_japanese_empty_and_garbage_no_crash():
    assert parse_nutrition_text("").is_empty()
    garbage = "◯△×☆ノイズテキスト１２３"
    result = parse_nutrition_text(garbage)
    assert isinstance(result, ParsedNutrition)


# --------------------------------------------------------------------------- #
# Image preprocessing (EXIF orientation, resizing, binarization)
# --------------------------------------------------------------------------- #

def test_fix_orientation_no_exif_passthrough():
    img = Image.new("RGB", (100, 100), color="white")
    fixed = _fix_orientation_and_size(img)
    assert fixed.mode == "RGB"


def test_fix_orientation_applies_exif_rotation():
    # EXIF orientation 6 on a 100x200 (portrait) image means the photo
    # needs a 90-degree rotation to display correctly (landscape).
    # The image is also small enough to trigger the min-dimension
    # upscale, so we assert on orientation (aspect ratio) rather than an
    # exact pixel size.
    img = Image.new("RGB", (100, 200), color="white")
    exif = img.getexif()
    exif[274] = 6  # Orientation tag
    import io
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    buf.seek(0)
    reloaded = Image.open(buf)
    fixed = _fix_orientation_and_size(reloaded)
    w, h = fixed.size
    assert w > h  # portrait (100x200) rotated to landscape (wide x tall)


def test_fix_orientation_downscales_huge_images():
    img = Image.new("RGB", (5000, 3000), color="white")
    fixed = _fix_orientation_and_size(img)
    assert max(fixed.size) <= 2200


def test_fix_orientation_upscales_tiny_images():
    img = Image.new("RGB", (200, 100), color="white")
    fixed = _fix_orientation_and_size(img)
    assert max(fixed.size) >= 800


def test_otsu_binarize_produces_only_black_and_white():
    img = Image.new("L", (50, 50), color=128)
    for x in range(25):
        for y in range(50):
            img.putpixel((x, y), 20)
    for x in range(25, 50):
        for y in range(50):
            img.putpixel((x, y), 220)
    binarized = _otsu_binarize(img)
    unique_values = set(binarized.tobytes())
    assert unique_values.issubset({0, 255})


def test_generate_preprocess_variants_returns_multiple_images():
    img = Image.new("RGB", (300, 300), color="white")
    variants = _generate_preprocess_variants(img)
    # 3 base variants always; a 4th (CLAHE-enhanced) is added when OpenCV
    # is installed, so accept either count rather than hardcoding one.
    assert len(variants) in (3, 4)
    for v in variants:
        assert isinstance(v, Image.Image)


def test_generate_preprocess_variants_handles_rgba_input():
    # st.camera_input / uploaded PNGs can be RGBA; must not crash
    img = Image.new("RGBA", (300, 300), color=(255, 255, 255, 255))
    variants = _generate_preprocess_variants(img)
    assert len(variants) in (3, 4)


def test_clahe_enhanced_variant_when_cv2_available():
    from modules.ocr_parser import _clahe_enhanced, _HAS_CV2
    gray = ImageOps.grayscale(Image.new("RGB", (100, 100), color="white"))
    result = _clahe_enhanced(gray)
    if _HAS_CV2:
        assert result is not None
        assert isinstance(result, Image.Image)
        # Upscaled 2x
        assert result.size == (200, 200)
    else:
        assert result is None


def test_clahe_enhanced_returns_none_when_cv2_unavailable():
    from modules.ocr_parser import _clahe_enhanced
    gray = ImageOps.grayscale(Image.new("RGB", (100, 100), color="white"))
    with patch("modules.ocr_parser._HAS_CV2", False):
        assert _clahe_enhanced(gray) is None


def test_clahe_enhanced_handles_exception_gracefully():
    from modules.ocr_parser import _clahe_enhanced
    gray = ImageOps.grayscale(Image.new("RGB", (100, 100), color="white"))
    with patch("modules.ocr_parser._HAS_CV2", True), \
         patch("modules.ocr_parser.cv2.resize", side_effect=Exception("boom")):
        assert _clahe_enhanced(gray) is None


def test_generate_preprocess_variants_includes_clahe_when_available():
    from modules.ocr_parser import _HAS_CV2
    img = Image.new("RGB", (300, 300), color="white")
    variants = _generate_preprocess_variants(img)
    if _HAS_CV2:
        assert len(variants) == 4
    else:
        assert len(variants) == 3
