import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.ocr_parser import parse_nutrition_text, ParsedNutrition


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
