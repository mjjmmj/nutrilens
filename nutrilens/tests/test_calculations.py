import math
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from modules.calculations import (
    UserProfile,
    NutritionFacts,
    calculate_bmi,
    calculate_body_fat_percent,
    calculate_bmr,
    calculate_tdee,
    build_metabolic_baseline,
    calculate_insulin_load,
    categorize_insulin_load,
    predict_insulin_response,
    calculate_tef,
    calculate_gross_calories,
    predict_body_fat_change,
    lbs_to_kg,
    kg_to_lbs,
    feet_inches_to_cm,
    cm_to_feet_inches,
    InsulinResponseCategory,
)


# --------------------------------------------------------------------------- #
# Unit conversions
# --------------------------------------------------------------------------- #

def test_lbs_kg_roundtrip():
    assert math.isclose(kg_to_lbs(lbs_to_kg(150)), 150, rel_tol=1e-6)


def test_feet_inches_cm_roundtrip():
    cm = feet_inches_to_cm(5, 10)
    f, i = cm_to_feet_inches(cm)
    assert f == 5
    assert math.isclose(i, 10, abs_tol=0.2)


# --------------------------------------------------------------------------- #
# BMI / Body fat %
# --------------------------------------------------------------------------- #

def test_bmi_known_value():
    # 70kg, 175cm -> BMI ~22.86
    bmi = calculate_bmi(70, 175)
    assert math.isclose(bmi, 22.86, abs_tol=0.05)


def test_bmi_zero_height_raises():
    with pytest.raises(ValueError):
        calculate_bmi(70, 0)


def test_body_fat_percent_male_vs_female():
    bmi = 25.0
    age = 30
    male_bf = calculate_body_fat_percent(bmi, age, "Male")
    female_bf = calculate_body_fat_percent(bmi, age, "Female")
    # Female should be higher than male at same BMI/age (Deurenberg formula)
    assert female_bf > male_bf
    assert math.isclose(female_bf - male_bf, 10.8, abs_tol=0.01)


def test_body_fat_percent_floor_clamped():
    # Extremely low BMI/age combo should not go negative
    bf = calculate_body_fat_percent(bmi=10, age=1, gender="Female")
    assert bf >= 2.0


# --------------------------------------------------------------------------- #
# BMR / TDEE
# --------------------------------------------------------------------------- #

def test_bmr_male_known_value():
    # Mifflin-St Jeor, male, 80kg, 180cm, 30y
    bmr = calculate_bmr(80, 180, 30, "Male")
    expected = 10 * 80 + 6.25 * 180 - 5 * 30 + 5
    assert math.isclose(bmr, expected)


def test_bmr_female_known_value():
    bmr = calculate_bmr(65, 165, 28, "Female")
    expected = 10 * 65 + 6.25 * 165 - 5 * 28 - 161
    assert math.isclose(bmr, expected)


def test_tdee_scales_with_activity():
    bmr = 1600
    sedentary = calculate_tdee(bmr, "Sedentary")
    very_active = calculate_tdee(bmr, "Very Active")
    assert very_active > sedentary
    assert math.isclose(sedentary, 1600 * 1.2)


def test_tdee_unknown_activity_defaults_sedentary():
    bmr = 1600
    result = calculate_tdee(bmr, "NotARealLevel")
    assert math.isclose(result, 1600 * 1.2)


# --------------------------------------------------------------------------- #
# UserProfile defaults
# --------------------------------------------------------------------------- #

def test_profile_full_defaults_when_empty():
    profile = UserProfile()
    resolved = profile.resolve_defaults()
    assert resolved.age == 35
    assert resolved.weight_kg == 80.0  # default male
    assert "age" in resolved.used_defaults
    assert "weight" in resolved.used_defaults
    assert "body_fat_pct" in resolved.used_defaults


def test_profile_female_defaults():
    profile = UserProfile(gender="Female")
    resolved = profile.resolve_defaults()
    assert resolved.weight_kg == 65.0
    assert resolved.height_cm == 163.0


def test_profile_respects_provided_values():
    profile = UserProfile(age=40, gender="Male", height_cm=180, weight_kg=90, body_fat_pct=18)
    resolved = profile.resolve_defaults()
    assert resolved.age == 40
    assert resolved.weight_kg == 90
    assert resolved.body_fat_pct == 18
    assert resolved.used_defaults == []


def test_profile_negative_values_treated_as_missing():
    profile = UserProfile(age=-5, weight_kg=-10)
    resolved = profile.resolve_defaults()
    assert resolved.age == 35
    assert resolved.weight_kg == 80.0


def test_build_metabolic_baseline():
    profile = UserProfile(age=30, gender="Male", height_cm=180, weight_kg=80,
                           activity_level="Moderately Active")
    baseline = build_metabolic_baseline(profile)
    assert baseline.bmi > 0
    assert baseline.bmr_kcal > 0
    assert baseline.tdee_kcal > baseline.bmr_kcal
    assert math.isclose(baseline.hourly_baseline_kcal, baseline.tdee_kcal / 24, abs_tol=0.01)


# --------------------------------------------------------------------------- #
# Insulin load
# --------------------------------------------------------------------------- #

def test_insulin_load_known_value():
    facts = NutritionFacts(total_carbs_g=50, fiber_g=4, sugars_g=10, protein_g=10, total_fat_g=5)
    score = calculate_insulin_load(facts)
    expected = 50 - (0.5 * 4) + (0.56 * 10) + (0.15 * 5)
    assert math.isclose(score, expected)


def test_insulin_load_zero_macros():
    facts = NutritionFacts()
    assert calculate_insulin_load(facts) == 0


@pytest.mark.parametrize("score,expected", [
    (0, InsulinResponseCategory.LOW),
    (19.9, InsulinResponseCategory.LOW),
    (20, InsulinResponseCategory.MEDIUM),
    (44.9, InsulinResponseCategory.MEDIUM),
    (45, InsulinResponseCategory.HIGH),
    (100, InsulinResponseCategory.HIGH),
])
def test_categorize_insulin_load_boundaries(score, expected):
    assert categorize_insulin_load(score) == expected


def test_predict_insulin_response_high_carb_meal():
    # White rice-like: high carb, low fiber/protein/fat
    facts = NutritionFacts(total_carbs_g=60, fiber_g=1, sugars_g=0, protein_g=4, total_fat_g=1)
    prediction = predict_insulin_response(facts)
    assert prediction.category == InsulinResponseCategory.HIGH
    assert prediction.estimated_delta_uiu_ml > 0


def test_predict_insulin_response_low_carb_meal():
    # Leafy greens: minimal everything
    facts = NutritionFacts(total_carbs_g=2, fiber_g=1, sugars_g=0, protein_g=1, total_fat_g=0)
    prediction = predict_insulin_response(facts)
    assert prediction.category == InsulinResponseCategory.LOW


def test_predict_insulin_response_never_negative():
    # Pathological negative-ish case (high fiber relative to carbs)
    facts = NutritionFacts(total_carbs_g=5, fiber_g=20, sugars_g=0, protein_g=0, total_fat_g=0)
    prediction = predict_insulin_response(facts)
    assert prediction.estimated_delta_uiu_ml >= 0


# --------------------------------------------------------------------------- #
# TEF / gross calories / body fat change
# --------------------------------------------------------------------------- #

def test_calculate_tef_positive():
    facts = NutritionFacts(protein_g=20, total_carbs_g=40, total_fat_g=10)
    tef = calculate_tef(facts)
    assert tef > 0


def test_gross_calories_prefers_label_value():
    facts = NutritionFacts(calories=250, protein_g=10, total_carbs_g=30, total_fat_g=5)
    assert calculate_gross_calories(facts) == 250


def test_gross_calories_derives_from_macros_when_missing():
    facts = NutritionFacts(calories=0, protein_g=10, total_carbs_g=30, fiber_g=5, total_fat_g=5)
    kcal = calculate_gross_calories(facts)
    expected = (10 * 4) + (25 * 4) + (5 * 2) + (5 * 9)
    assert math.isclose(kcal, expected)


def test_predict_body_fat_change_surplus():
    profile = UserProfile(age=30, gender="Male", height_cm=180, weight_kg=80,
                           activity_level="Sedentary")
    baseline = build_metabolic_baseline(profile)
    # A very large meal relative to hourly baseline should be a surplus
    facts = NutritionFacts(calories=1200, protein_g=40, total_carbs_g=100, total_fat_g=50)
    result = predict_body_fat_change(facts, baseline, weight_kg=80)
    assert result.is_surplus is True
    assert result.projected_fat_mass_change_kg > 0
    assert result.projected_body_fat_pct_change > 0


def test_predict_body_fat_change_deficit():
    profile = UserProfile(age=30, gender="Male", height_cm=180, weight_kg=80,
                           activity_level="Very Active")
    baseline = build_metabolic_baseline(profile)
    # Tiny snack relative to a very active person's hourly baseline
    facts = NutritionFacts(calories=15, protein_g=1, total_carbs_g=2, total_fat_g=0)
    result = predict_body_fat_change(facts, baseline, weight_kg=80)
    assert result.is_surplus is False
    assert result.projected_fat_mass_change_kg < 0


def test_predict_body_fat_change_zero_weight_raises():
    profile = UserProfile(age=30, gender="Male", height_cm=180, weight_kg=80)
    baseline = build_metabolic_baseline(profile)
    facts = NutritionFacts(calories=200)
    with pytest.raises(ValueError):
        predict_body_fat_change(facts, baseline, weight_kg=0)


def test_nutrition_facts_scaled():
    facts = NutritionFacts(calories=100, total_carbs_g=20, servings_consumed=2.5)
    scaled = facts.scaled()
    assert scaled.calories == 250
    assert scaled.total_carbs_g == 50
    assert scaled.servings_consumed == 1.0
