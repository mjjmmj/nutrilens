"""
NutriLens
=========
A Streamlit app that reads a nutrition-facts label from a photo (or manual
entry) and produces two algorithmic, educational projections:

1. An "Insulin Load" indicator (Food Insulin Index proxy).
2. A hyper-acute body-fat % change projection based on caloric surplus /
   deficit versus the user's hourly TDEE baseline.

⚠️  Educational tool only. Not medical advice. See the in-app disclaimer.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from PIL import Image, UnidentifiedImageError

from modules.calculations import (
    NutritionFacts,
    build_metabolic_baseline,
    predict_insulin_response,
    predict_body_fat_change,
    InsulinResponseCategory,
)
from modules.ocr_parser import (
    extract_nutrition_from_image,
    ocr_backends_available,
    ParsedNutrition,
)
from modules.user_profile import render_profile_sidebar, show_resolved_profile_notice


# --------------------------------------------------------------------------- #
# Page configuration
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="NutriLens — Nutrition Label Scanner",
    page_icon="🥗",
    layout="centered",
    initial_sidebar_state="expanded",
)

# Session state defaults for the editable nutrition table
DEFAULT_FIELDS = {
    "Serving Size (g)": 100.0,
    "Calories": 0.0,
    "Total Carbs (g)": 0.0,
    "Dietary Fiber (g)": 0.0,
    "Sugars (g)": 0.0,
    "Protein (g)": 0.0,
    "Total Fat (g)": 0.0,
}

if "nutrition_values" not in st.session_state:
    st.session_state.nutrition_values = dict(DEFAULT_FIELDS)
if "raw_ocr_text" not in st.session_state:
    st.session_state.raw_ocr_text = ""
if "ocr_fields_found" not in st.session_state:
    st.session_state.ocr_fields_found = None


def _apply_parsed_to_session(parsed: ParsedNutrition) -> None:
    mapping = {
        "Serving Size (g)": parsed.serving_size_g,
        "Calories": parsed.calories,
        "Total Carbs (g)": parsed.total_carbs_g,
        "Dietary Fiber (g)": parsed.fiber_g,
        "Sugars (g)": parsed.sugars_g,
        "Protein (g)": parsed.protein_g,
        "Total Fat (g)": parsed.total_fat_g,
    }
    for label, value in mapping.items():
        if value is not None:
            st.session_state.nutrition_values[label] = value


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

st.title("🥗 NutriLens")
st.caption(
    "Scan a nutrition label → get an educational estimate of its insulin "
    "impact and caloric/body-fat effect."
)

with st.expander("⚠️ Important disclaimer — please read", expanded=False):
    st.warning(
        "**NutriLens provides algorithmic approximations based on published "
        "nutrition-science formulas (Mifflin-St Jeor, Deurenberg BMI-based "
        "body-fat estimate, Food Insulin Index proxy, and Thermic Effect of "
        "Food ranges). It is not a substitute for professional medical "
        "advice, laboratory testing, or continuous glucose/insulin "
        "monitoring.**\n\n"
        "In particular, real body-fat percentage does not measurably change "
        "from eating a single food item — the body-fat projection shown "
        "here is a *directional, energy-balance indicator* (what this "
        "food's caloric surplus/deficit would equate to in fat mass if "
        "sustained), not a real-time physiological reading. "
        "Insulin values are illustrative estimates, not measured blood "
        "levels. Always consult a doctor, dietitian, or endocrinologist for "
        "clinical decisions, especially if you have diabetes or a "
        "metabolic condition."
    )

# --------------------------------------------------------------------------- #
# Sidebar: user profile
# --------------------------------------------------------------------------- #

raw_profile = render_profile_sidebar()
resolved_profile = raw_profile.resolve_defaults()
show_resolved_profile_notice(resolved_profile)

try:
    baseline = build_metabolic_baseline(raw_profile)
except Exception as exc:  # defensive: should not happen given resolve_defaults()
    st.sidebar.error(f"Could not compute metabolic baseline: {exc}")
    st.stop()

with st.sidebar.expander("📊 Your calculated baseline"):
    st.metric("BMI", f"{baseline.bmi:.1f}")
    st.metric("Estimated Body Fat %", f"{baseline.body_fat_pct:.1f}%")
    st.metric("BMR (kcal/day)", f"{baseline.bmr_kcal:.0f}")
    st.metric("TDEE (kcal/day)", f"{baseline.tdee_kcal:.0f}")
    st.caption(f"Hourly baseline burn: {baseline.hourly_baseline_kcal:.1f} kcal/hr")


# --------------------------------------------------------------------------- #
# Image capture / upload
# --------------------------------------------------------------------------- #

st.subheader("1. Capture or upload the nutrition label")

backends = ocr_backends_available()
if not any(backends.values()):
    st.info(
        "No OCR engine (pytesseract / easyocr) was detected in this "
        "environment. You can still enter nutrition values manually below."
    )

tab_camera, tab_upload = st.tabs(["📷 Use Camera", "📁 Upload from Gallery"])

captured_image = None
with tab_camera:
    camera_file = st.camera_input(
        "Take a photo of the nutrition label",
        help="On mobile, this opens your device camera directly.",
    )
    if camera_file is not None:
        captured_image = camera_file

with tab_upload:
    uploaded_file = st.file_uploader(
        "Upload an image (JPG, PNG)", type=["jpg", "jpeg", "png", "webp"]
    )
    if uploaded_file is not None:
        captured_image = uploaded_file

image_obj = None
if captured_image is not None:
    try:
        image_obj = Image.open(captured_image)
        st.image(image_obj, caption="Captured label", use_container_width=True)
    except UnidentifiedImageError:
        st.error(
            "That file couldn't be read as an image (it may be corrupted). "
            "Please try again or enter values manually below."
        )
    except Exception as exc:
        st.error(f"Unexpected error opening the image: {exc}. Please try again.")

    if image_obj is not None:
        with st.spinner("Reading label with OCR..."):
            try:
                parsed, raw_text = extract_nutrition_from_image(image_obj)
                st.session_state.raw_ocr_text = raw_text
                st.session_state.ocr_fields_found = parsed.fields_found()
                if parsed.is_empty():
                    st.warning(
                        "Couldn't confidently read any nutrition values from "
                        "this image. Please enter them manually below."
                    )
                else:
                    _apply_parsed_to_session(parsed)
                    st.success(
                        f"Extracted {parsed.fields_found()} of 7 fields. "
                        "Please double-check the values below — OCR can "
                        "misread labels, especially on blurry or angled photos."
                    )
            except Exception as exc:
                st.error(
                    f"OCR processing failed ({exc}). Please enter the "
                    "nutrition values manually below."
                )

    if st.session_state.raw_ocr_text:
        with st.expander("🔍 View raw OCR text (for debugging misreads)"):
            st.text(st.session_state.raw_ocr_text)


# --------------------------------------------------------------------------- #
# Editable nutrition table
# --------------------------------------------------------------------------- #

st.subheader("2. Confirm or correct the nutrition facts")
st.caption("Values are per serving, as printed on the label.")

df = pd.DataFrame(
    {
        "Field": list(st.session_state.nutrition_values.keys()),
        "Value": list(st.session_state.nutrition_values.values()),
    }
)

edited_df = st.data_editor(
    df,
    column_config={
        "Field": st.column_config.TextColumn("Nutrition Field", disabled=True),
        "Value": st.column_config.NumberColumn("Value", min_value=0.0, step=0.1, format="%.1f"),
    },
    hide_index=True,
    use_container_width=True,
    key="nutrition_editor",
)

# Sync edits back to session state
for _, row in edited_df.iterrows():
    st.session_state.nutrition_values[row["Field"]] = float(row["Value"]) if pd.notna(row["Value"]) else 0.0

servings_consumed = st.number_input(
    "How many servings do you plan to eat?",
    min_value=0.1, max_value=20.0, value=1.0, step=0.5,
)

reset_col, _ = st.columns([1, 3])
with reset_col:
    if st.button("↺ Reset values"):
        st.session_state.nutrition_values = dict(DEFAULT_FIELDS)
        st.session_state.raw_ocr_text = ""
        st.rerun()


# --------------------------------------------------------------------------- #
# Build NutritionFacts and validate
# --------------------------------------------------------------------------- #

vals = st.session_state.nutrition_values
facts = NutritionFacts(
    serving_size_g=vals["Serving Size (g)"] or 100.0,
    servings_consumed=servings_consumed,
    calories=vals["Calories"],
    total_carbs_g=vals["Total Carbs (g)"],
    fiber_g=vals["Dietary Fiber (g)"],
    sugars_g=vals["Sugars (g)"],
    protein_g=vals["Protein (g)"],
    total_fat_g=vals["Total Fat (g)"],
)

has_any_data = any(
    [facts.calories, facts.total_carbs_g, facts.protein_g, facts.total_fat_g]
)

st.divider()
st.subheader("3. Predicted acute impact")

if not has_any_data:
    st.info("Enter or scan nutrition values above to see predictions.")
    st.stop()

scaled_facts = facts.scaled()

# --------------------------------------------------------------------------- #
# Insulin prediction
# --------------------------------------------------------------------------- #

insulin_pred = predict_insulin_response(scaled_facts)

category_color = {
    InsulinResponseCategory.LOW: "🟢",
    InsulinResponseCategory.MEDIUM: "🟡",
    InsulinResponseCategory.HIGH: "🔴",
}

col1, col2 = st.columns(2)
with col1:
    st.metric(
        "Insulin Load Score",
        f"{insulin_pred.insulin_load_score:.1f}",
    )
with col2:
    st.metric(
        f"{category_color[insulin_pred.category]} Spike Category",
        insulin_pred.category.value,
        delta=f"~{insulin_pred.estimated_delta_uiu_ml:.1f} µIU/mL",
        delta_color="inverse",
    )

max_scale = 80.0
progress_val = min(insulin_pred.insulin_load_score / max_scale, 1.0)
st.progress(max(progress_val, 0.0), text=f"Insulin Load relative scale (0–{max_scale:.0f}+)")
st.caption(insulin_pred.reference_note)

# --------------------------------------------------------------------------- #
# Body fat change prediction
# --------------------------------------------------------------------------- #

try:
    fat_pred = predict_body_fat_change(
        scaled_facts, baseline, weight_kg=resolved_profile.weight_kg
    )
except ValueError as exc:
    st.error(f"Could not compute body-fat projection: {exc}")
    st.stop()

st.markdown("#### Caloric & body-fat projection")

col3, col4, col5 = st.columns(3)
with col3:
    st.metric("Net Metabolizable Energy", f"{fat_pred.net_metabolizable_kcal:.0f} kcal")
with col4:
    st.metric("Hourly Baseline Burn", f"{fat_pred.hourly_baseline_kcal:.1f} kcal")
with col5:
    direction = "Surplus" if fat_pred.is_surplus else "Deficit"
    st.metric(
        f"Net Energy {direction}",
        f"{abs(fat_pred.net_energy_balance_kcal):.0f} kcal",
        delta=f"{'+' if fat_pred.is_surplus else '−'}{abs(fat_pred.net_energy_balance_kcal):.0f} kcal",
        delta_color="inverse" if fat_pred.is_surplus else "normal",
    )

sign = "+" if fat_pred.is_surplus else ""
st.metric(
    "Projected Body Fat % Change (if this pattern repeated hourly)",
    f"{sign}{fat_pred.projected_body_fat_pct_change:.4f} pp",
)

st.caption(
    f"Thermic Effect of Food consumed ~{fat_pred.tef_kcal:.0f} kcal during digestion. "
    f"Gross energy from this portion: {fat_pred.gross_calories_kcal:.0f} kcal."
)

st.info(
    "📌 **How to read this:** this is *not* a claim that your body fat will "
    "instantly change. It shows the theoretical fat-mass equivalent "
    "(kg / lb) of this food's net caloric surplus or deficit relative to "
    "your baseline hourly burn rate — useful as a relative comparison "
    "between foods, not as a literal, real-time measurement.\n\n"
    f"Fat-mass equivalent: **{fat_pred.projected_fat_mass_change_kg:+.4f} kg** "
    f"({fat_pred.projected_fat_mass_change_lb:+.4f} lb)."
)

st.divider()
st.caption(
    "NutriLens · Algorithmic nutrition estimator · Not medical advice · "
    "Consult a healthcare professional for clinical guidance."
)
