"""
calculations.py
================
Pure-Python metabolic/nutritional calculation engine for NutriLens.

Every function here is UI-independent and side-effect free so it can be
unit tested without Streamlit. All formulas are algorithmic
*approximations* drawn from published nutrition-science heuristics
(Mifflin-St Jeor, Deurenberg BMI-based body-fat estimate, Food Insulin
Index proxy, Thermic Effect of Food ranges). None of this is a substitute
for clinical measurement (DEXA scans, continuous glucose monitors, or
insulin clamp studies).

Unit conventions (internal): kilograms, centimeters, kilocalories.
Conversion helpers are provided for imperial inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

KCAL_PER_KG_FAT = 7700.0
KCAL_PER_LB_FAT = 3500.0
LB_PER_KG = 2.20462
IN_PER_CM = 0.393701

ATWATER_KCAL_PER_G = {
    "protein": 4.0,
    "carbs": 4.0,
    "fat": 9.0,
    "fiber": 2.0,  # fiber is only partially metabolized (~2 kcal/g avg)
}

# Midpoint Thermic Effect of Food (TEF) fractions per macronutrient,
# based on the commonly cited literature ranges:
#   Protein 20-30%, Carbohydrate 5-15%, Fat 0-3%
TEF_FRACTIONS = {
    "protein": 0.25,
    "carbs": 0.10,
    "fat": 0.015,
}

ACTIVITY_FACTORS = {
    "Sedentary": 1.2,
    "Lightly Active": 1.375,
    "Moderately Active": 1.55,
    "Very Active": 1.725,
}

DEFAULT_WEIGHT_KG = {"Male": 80.0, "Female": 65.0}
DEFAULT_HEIGHT_CM = {"Male": 176.0, "Female": 163.0}
DEFAULT_AGE = 35


class InsulinResponseCategory(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


# --------------------------------------------------------------------------- #
# Unit conversion helpers
# --------------------------------------------------------------------------- #

def lbs_to_kg(lbs: float) -> float:
    return lbs / LB_PER_KG


def kg_to_lbs(kg: float) -> float:
    return kg * LB_PER_KG


def feet_inches_to_cm(feet: float, inches: float) -> float:
    total_inches = feet * 12 + inches
    return total_inches / IN_PER_CM


def cm_to_feet_inches(cm: float) -> tuple[float, float]:
    total_inches = cm * IN_PER_CM
    feet = int(total_inches // 12)
    inches = round(total_inches - feet * 12, 1)
    return feet, inches


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class UserProfile:
    """Biological metrics used for baseline metabolic calculations.

    Any field left as None is filled in with a literature-based default
    via `resolve_defaults()`.
    """

    age: Optional[float] = None
    gender: str = "Male"  # "Male" or "Female"
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    activity_level: str = "Sedentary"
    body_fat_pct: Optional[float] = None
    used_defaults: list = field(default_factory=list)

    def resolve_defaults(self) -> "UserProfile":
        """Return a new, fully-populated UserProfile, filling gaps with
        standard baseline values and recording what was defaulted."""
        gender = self.gender if self.gender in ("Male", "Female") else "Male"
        used = []

        age = self.age
        if age is None or age <= 0:
            age = DEFAULT_AGE
            used.append("age")

        height_cm = self.height_cm
        if height_cm is None or height_cm <= 0:
            height_cm = DEFAULT_HEIGHT_CM[gender]
            used.append("height")

        weight_kg = self.weight_kg
        if weight_kg is None or weight_kg <= 0:
            weight_kg = DEFAULT_WEIGHT_KG[gender]
            used.append("weight")

        activity_level = (
            self.activity_level
            if self.activity_level in ACTIVITY_FACTORS
            else "Sedentary"
        )

        body_fat_pct = self.body_fat_pct
        if body_fat_pct is None or body_fat_pct <= 0:
            bmi = calculate_bmi(weight_kg, height_cm)
            body_fat_pct = calculate_body_fat_percent(bmi, age, gender)
            used.append("body_fat_pct")

        return UserProfile(
            age=age,
            gender=gender,
            height_cm=height_cm,
            weight_kg=weight_kg,
            activity_level=activity_level,
            body_fat_pct=round(body_fat_pct, 2),
            used_defaults=used,
        )


@dataclass
class NutritionFacts:
    """Parsed / user-confirmed nutrition label values, per serving."""

    serving_size_g: float = 100.0
    servings_consumed: float = 1.0
    calories: float = 0.0
    total_carbs_g: float = 0.0
    fiber_g: float = 0.0
    sugars_g: float = 0.0
    protein_g: float = 0.0
    total_fat_g: float = 0.0

    # Extended nutrient panel (not used in the insulin/body-fat prediction
    # math below, which only needs the macros above, but captured and
    # stored because a nutrition label is more than its macros). Fields
    # and units follow the standard FDA "Nutrition Facts" panel.
    saturated_fat_g: float = 0.0
    trans_fat_g: float = 0.0
    cholesterol_mg: float = 0.0
    sodium_mg: float = 0.0
    added_sugars_g: float = 0.0
    vitamin_d_mcg: float = 0.0
    calcium_mg: float = 0.0
    iron_mg: float = 0.0
    potassium_mg: float = 0.0

    def scaled(self) -> "NutritionFacts":
        """Return a copy scaled by the number of servings the user intends
        to eat."""
        m = self.servings_consumed
        return NutritionFacts(
            serving_size_g=self.serving_size_g * m,
            servings_consumed=1.0,
            calories=self.calories * m,
            total_carbs_g=self.total_carbs_g * m,
            fiber_g=self.fiber_g * m,
            sugars_g=self.sugars_g * m,
            protein_g=self.protein_g * m,
            total_fat_g=self.total_fat_g * m,
            saturated_fat_g=self.saturated_fat_g * m,
            trans_fat_g=self.trans_fat_g * m,
            cholesterol_mg=self.cholesterol_mg * m,
            sodium_mg=self.sodium_mg * m,
            added_sugars_g=self.added_sugars_g * m,
            vitamin_d_mcg=self.vitamin_d_mcg * m,
            calcium_mg=self.calcium_mg * m,
            iron_mg=self.iron_mg * m,
            potassium_mg=self.potassium_mg * m,
        )


@dataclass
class MetabolicBaseline:
    bmi: float
    body_fat_pct: float
    bmr_kcal: float
    tdee_kcal: float
    hourly_baseline_kcal: float


@dataclass
class InsulinPrediction:
    insulin_load_score: float
    category: InsulinResponseCategory
    estimated_delta_uiu_ml: float
    reference_note: str


@dataclass
class BodyFatPrediction:
    gross_calories_kcal: float
    tef_kcal: float
    net_metabolizable_kcal: float
    hourly_baseline_kcal: float
    net_energy_balance_kcal: float
    projected_fat_mass_change_kg: float
    projected_fat_mass_change_lb: float
    projected_body_fat_pct_change: float
    is_surplus: bool


# --------------------------------------------------------------------------- #
# Baseline metabolic calculations
# --------------------------------------------------------------------------- #

def calculate_bmi(weight_kg: float, height_cm: float) -> float:
    if height_cm <= 0:
        raise ValueError("Height must be greater than zero.")
    height_m = height_cm / 100.0
    return weight_kg / (height_m ** 2)


def calculate_body_fat_percent(bmi: float, age: float, gender: str) -> float:
    """Deurenberg BMI-based adult body-fat % estimate.

    BF% = (1.20 * BMI) + (0.23 * age) - (10.8 * gender_factor) - 5.4
    gender_factor: Male = 1, Female = 0
    """
    gender_factor = 1 if gender == "Male" else 0
    bf = (1.20 * bmi) + (0.23 * age) - (10.8 * gender_factor) - 5.4
    return max(bf, 2.0)  # clamp to a physiologically plausible floor


def calculate_bmr(weight_kg: float, height_cm: float, age: float, gender: str) -> float:
    """Mifflin-St Jeor BMR equation."""
    if gender == "Male":
        return (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
    return (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161


def calculate_tdee(bmr_kcal: float, activity_level: str) -> float:
    factor = ACTIVITY_FACTORS.get(activity_level, 1.2)
    return bmr_kcal * factor


def build_metabolic_baseline(profile: UserProfile) -> MetabolicBaseline:
    """Compute BMI, body-fat %, BMR, and TDEE from a resolved UserProfile."""
    resolved = profile.resolve_defaults()
    bmi = calculate_bmi(resolved.weight_kg, resolved.height_cm)
    bmr = calculate_bmr(
        resolved.weight_kg, resolved.height_cm, resolved.age, resolved.gender
    )
    tdee = calculate_tdee(bmr, resolved.activity_level)
    return MetabolicBaseline(
        bmi=round(bmi, 2),
        body_fat_pct=resolved.body_fat_pct,
        bmr_kcal=round(bmr, 1),
        tdee_kcal=round(tdee, 1),
        hourly_baseline_kcal=round(tdee / 24.0, 2),
    )


# --------------------------------------------------------------------------- #
# Insulin Load prediction (Food Insulin Index proxy)
# --------------------------------------------------------------------------- #

def calculate_insulin_load(facts: NutritionFacts) -> float:
    """Insulin Load = Carbs - (0.5 * Fiber) + (0.56 * Protein) + (0.15 * Fat)"""
    return (
        facts.total_carbs_g
        - (0.5 * facts.fiber_g)
        + (0.56 * facts.protein_g)
        + (0.15 * facts.total_fat_g)
    )


def categorize_insulin_load(score: float) -> InsulinResponseCategory:
    if score < 20:
        return InsulinResponseCategory.LOW
    if score < 45:
        return InsulinResponseCategory.MEDIUM
    return InsulinResponseCategory.HIGH


def predict_insulin_response(facts: NutritionFacts) -> InsulinPrediction:
    """Map the Insulin Load Score to a qualitative category and an
    illustrative numeric change in microIU/mL, scaled relative to a
    standard 50g-glucose reference spike (~30 uIU/mL in a healthy,
    insulin-sensitive adult, per published OGTT literature ranges).
    """
    score = calculate_insulin_load(facts)
    category = categorize_insulin_load(score)

    reference_score = 50.0  # ~ carbs-only insulin load of a 50g glucose dose
    reference_spike_uiu_ml = 30.0
    ratio = max(score, 0.0) / reference_score
    estimated_delta = round(ratio * reference_spike_uiu_ml, 1)

    return InsulinPrediction(
        insulin_load_score=round(score, 2),
        category=category,
        estimated_delta_uiu_ml=estimated_delta,
        reference_note=(
            "Illustrative estimate scaled against a standard 50g oral "
            "glucose tolerance test spike (~30 uIU/mL). Not a measured "
            "clinical value."
        ),
    )


# --------------------------------------------------------------------------- #
# Body fat % change prediction
# --------------------------------------------------------------------------- #

def calculate_tef(facts: NutritionFacts) -> float:
    """Thermic Effect of Food, in kcal, using midpoint literature fractions."""
    protein_kcal = facts.protein_g * ATWATER_KCAL_PER_G["protein"]
    carb_kcal = facts.total_carbs_g * ATWATER_KCAL_PER_G["carbs"]
    fat_kcal = facts.total_fat_g * ATWATER_KCAL_PER_G["fat"]

    tef = (
        protein_kcal * TEF_FRACTIONS["protein"]
        + carb_kcal * TEF_FRACTIONS["carbs"]
        + fat_kcal * TEF_FRACTIONS["fat"]
    )
    return tef


def calculate_gross_calories(facts: NutritionFacts) -> float:
    """Prefer the label's stated calories if provided (>0); otherwise derive
    from macros via Atwater factors, netting out unabsorbed fiber energy."""
    if facts.calories and facts.calories > 0:
        return facts.calories

    protein_kcal = facts.protein_g * ATWATER_KCAL_PER_G["protein"]
    carb_kcal = max(facts.total_carbs_g - facts.fiber_g, 0) * ATWATER_KCAL_PER_G["carbs"]
    fiber_kcal = facts.fiber_g * ATWATER_KCAL_PER_G["fiber"]
    fat_kcal = facts.total_fat_g * ATWATER_KCAL_PER_G["fat"]
    return protein_kcal + carb_kcal + fiber_kcal + fat_kcal


def predict_body_fat_change(
    facts: NutritionFacts,
    baseline: MetabolicBaseline,
    weight_kg: float,
    use_lbs: bool = False,
) -> BodyFatPrediction:
    """Project a hyper-acute body-fat % change from a single eating event.

    IMPORTANT SCIENTIFIC CAVEAT (surfaced in the UI as well): true body-fat
    percentage does not measurably change from a single meal. This output
    is a directional, energy-balance *projection* -- it shows what the
    caloric surplus/deficit from this food, if sustained repeatedly, would
    theoretically equate to in stored/spared adipose tissue. Treat it as an
    educational indicator of caloric impact, not a real-time physiological
    reading.
    """
    if weight_kg <= 0:
        raise ValueError("Weight must be greater than zero for this calculation.")

    gross_kcal = calculate_gross_calories(facts)
    tef_kcal = calculate_tef(facts)
    net_kcal = gross_kcal - tef_kcal

    hourly_baseline = baseline.hourly_baseline_kcal
    net_balance = net_kcal - hourly_baseline
    is_surplus = net_balance >= 0

    fat_change_kg = net_balance / KCAL_PER_KG_FAT
    fat_change_lb = net_balance / KCAL_PER_LB_FAT

    # Express as a percentage-point shift in body-fat %, assuming the
    # change in fat mass occurs against the user's current total weight.
    projected_pct_change = (fat_change_kg / weight_kg) * 100.0

    return BodyFatPrediction(
        gross_calories_kcal=round(gross_kcal, 1),
        tef_kcal=round(tef_kcal, 1),
        net_metabolizable_kcal=round(net_kcal, 1),
        hourly_baseline_kcal=round(hourly_baseline, 1),
        net_energy_balance_kcal=round(net_balance, 1),
        projected_fat_mass_change_kg=round(fat_change_kg, 4),
        projected_fat_mass_change_lb=round(fat_change_lb, 4),
        projected_body_fat_pct_change=round(projected_pct_change, 4),
        is_surplus=is_surplus,
    )
