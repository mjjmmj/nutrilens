"""
user_profile.py
================
Streamlit sidebar UI for collecting user biological metrics.

Kept separate from calculations.py so the scientific logic stays testable
without importing Streamlit.
"""

from __future__ import annotations

import streamlit as st

from modules.calculations import (
    UserProfile,
    lbs_to_kg,
    feet_inches_to_cm,
    ACTIVITY_FACTORS,
)


def render_profile_sidebar() -> UserProfile:
    """Render the profile input widgets and return a raw (unresolved)
    UserProfile. Blank/unset fields remain None -- default-filling happens
    later in calculations.build_metabolic_baseline via resolve_defaults()."""

    st.sidebar.header("👤 Your Profile")
    st.sidebar.caption(
        "Leave any field blank to use a standard baseline estimate instead."
    )

    gender = st.sidebar.radio("Gender", options=["Male", "Female"], horizontal=True)

    age_input = st.sidebar.number_input(
        "Age (years)", min_value=0, max_value=120, value=0, step=1,
        help="Leave at 0 to use a default baseline age of 35.",
    )
    age = float(age_input) if age_input > 0 else None

    unit_system = st.sidebar.radio(
        "Units", options=["Metric (kg/cm)", "Imperial (lb/ft-in)"], horizontal=True
    )

    height_cm = None
    weight_kg = None

    if unit_system.startswith("Metric"):
        height_val = st.sidebar.number_input(
            "Height (cm)", min_value=0.0, max_value=250.0, value=0.0, step=1.0
        )
        weight_val = st.sidebar.number_input(
            "Weight (kg)", min_value=0.0, max_value=300.0, value=0.0, step=0.5
        )
        height_cm = height_val if height_val > 0 else None
        weight_kg = weight_val if weight_val > 0 else None
    else:
        col1, col2 = st.sidebar.columns(2)
        with col1:
            feet = st.number_input("Height (ft)", min_value=0, max_value=8, value=0, step=1)
        with col2:
            inches = st.number_input("Height (in)", min_value=0.0, max_value=11.9, value=0.0, step=0.5)
        weight_lb = st.sidebar.number_input(
            "Weight (lb)", min_value=0.0, max_value=660.0, value=0.0, step=1.0
        )
        if feet > 0 or inches > 0:
            height_cm = feet_inches_to_cm(feet, inches)
        if weight_lb > 0:
            weight_kg = lbs_to_kg(weight_lb)

    activity_level = st.sidebar.selectbox(
        "Activity Level",
        options=list(ACTIVITY_FACTORS.keys()),
        index=0,
        help=(
            "Sedentary: little/no exercise · Lightly Active: 1-3 days/wk · "
            "Moderately Active: 3-5 days/wk · Very Active: 6-7 days/wk"
        ),
    )

    with st.sidebar.expander("Advanced (optional)"):
        known_bf = st.number_input(
            "Known Body Fat % (from DEXA/BIA scan, if available)",
            min_value=0.0, max_value=70.0, value=0.0, step=0.1,
            help="If left at 0, this app will estimate it from your BMI/age/gender.",
        )
        body_fat_pct = known_bf if known_bf > 0 else None

    profile = UserProfile(
        age=age,
        gender=gender,
        height_cm=height_cm,
        weight_kg=weight_kg,
        activity_level=activity_level,
        body_fat_pct=body_fat_pct,
    )
    return profile


def show_resolved_profile_notice(resolved: UserProfile) -> None:
    """Inform the user which fields were auto-filled with baseline defaults."""
    if resolved.used_defaults:
        friendly = {
            "age": "Age (defaulted to 35)",
            "weight": f"Weight (defaulted to {resolved.weight_kg:.0f} kg)",
            "height": f"Height (defaulted to {resolved.height_cm:.0f} cm)",
            "body_fat_pct": "Body Fat % (estimated from BMI/age/gender)",
        }
        items = [friendly.get(f, f) for f in resolved.used_defaults]
        st.sidebar.info("Using baseline defaults for: " + ", ".join(items))
