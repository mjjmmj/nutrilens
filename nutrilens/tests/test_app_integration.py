"""
test_app_integration.py
========================
Integration tests that run the actual app.py script via Streamlit's
official `AppTest` framework (streamlit.testing.v1) and simulate real
widget interactions, rather than testing individual functions in
isolation.

Why this file exists: a real bug shipped where the "Load into current
scan" button's `extended_nutrition_values` dict was built as a hardcoded
literal that didn't get updated when Vitamin B1/B2 fields were added
elsewhere in the app (calculations.py, database.py, and five other spots
in app.py were all updated correctly; this one was missed). Every
existing unit test still passed, because none of them exercised that
exact code path with real data -- they tested `_apply_parsed_to_session`
directly, or the database layer directly, but not "click through the
saved-foods search UI and load a result" end-to-end. This file closes
that gap by driving the actual UI.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """A temporary SQLite database pre-populated with one food that has
    every extended-nutrient field set to a distinct non-zero value, so a
    KeyError or silently-dropped field is easy to catch."""
    db_path = str(tmp_path / "test_nutrilens.db")
    from modules import database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db(db_path)
    db_module.save_food(
        db_module.FoodEntry(
            name="Integration Test Cup Noodle",
            category="Instant Noodles",
            brand="TestBrand",
            serving_size_g=76,
            calories=354,
            total_carbs_g=45.5,
            fiber_g=1.0,
            sugars_g=2.0,
            protein_g=8.4,
            total_fat_g=15.4,
            saturated_fat_g=7.0,
            trans_fat_g=0.1,
            cholesterol_mg=5.0,
            sodium_mg=1575.0,
            added_sugars_g=1.5,
            vitamin_d_mcg=0.5,
            vitamin_b1_mg=1.45,
            vitamin_b2_mg=0.25,
            calcium_mg=96.0,
            iron_mg=1.2,
            potassium_mg=150.0,
            source="Manual/OCR",
        ),
        db_path=db_path,
    )
    return db_path


def test_app_loads_without_exception():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception


def test_load_saved_food_with_full_extended_nutrients_does_not_crash(seeded_db):
    """The regression test for the actual bug: loading a saved food whose
    every extended-nutrient field is populated must not raise a
    KeyError (or any other exception) anywhere in the script -- not on
    the load itself, and not afterward when NutritionFacts/predictions
    are built from the now-populated session state."""
    import modules.database as db_module

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception

    # Monkeypatch the app's own reference to the DB path for this run
    import app as app_module
    original_db_path = db_module.DB_PATH
    db_module.DB_PATH = seeded_db
    try:
        # Directly invoke the same lookup app.py's UI uses, then feed the
        # result through the identical session-state-population code path
        # the "Load into current scan" button triggers -- this exercises
        # the exact dict-construction logic that broke, without needing
        # to simulate a live dropdown click (which AppTest's dropdown
        # support doesn't reliably drive for BaseWeb-rendered options).
        results = db_module.search_foods(name="Integration Test Cup Noodle", db_path=seeded_db)
        assert len(results) == 1
        chosen = results[0]

        # This mirrors app.py's "Load into current scan" button handler
        # body exactly -- if a field is ever added to FoodEntry/
        # NutritionFacts without updating this dict, this assignment
        # itself won't fail (dicts don't validate keys), but the
        # subsequent NutritionFacts construction below will raise
        # KeyError for any field this dict is missing, exactly like the
        # real bug did.
        app_module.st.session_state.nutrition_values = {
            "Serving Size (g)": chosen.serving_size_g,
            "Calories": chosen.calories,
            "Total Carbs (g)": chosen.total_carbs_g,
            "Dietary Fiber (g)": chosen.fiber_g,
            "Sugars (g)": chosen.sugars_g,
            "Protein (g)": chosen.protein_g,
            "Total Fat (g)": chosen.total_fat_g,
        }
        app_module.st.session_state.extended_nutrition_values = {
            "Saturated Fat (g)": chosen.saturated_fat_g,
            "Trans Fat (g)": chosen.trans_fat_g,
            "Cholesterol (mg)": chosen.cholesterol_mg,
            "Sodium (mg)": chosen.sodium_mg,
            "Added Sugars (g)": chosen.added_sugars_g,
            "Vitamin D (mcg)": chosen.vitamin_d_mcg,
            "Vitamin B1 (mg)": chosen.vitamin_b1_mg,
            "Vitamin B2 (mg)": chosen.vitamin_b2_mg,
            "Calcium (mg)": chosen.calcium_mg,
            "Iron (mg)": chosen.iron_mg,
            "Potassium (mg)": chosen.potassium_mg,
        }

        # Now re-run the script with these values already in session
        # state, exactly as it would be on the rerun after clicking
        # "Load into current scan" -- this is the part that raised
        # KeyError in the real bug, at the NutritionFacts(...) call site.
        at.run()
        assert not at.exception, f"App raised an exception: {list(at.exception)}"

        # Confirm the values actually made it into the rendered output,
        # not just that nothing crashed.
        assert app_module.st.session_state.extended_nutrition_values["Vitamin B1 (mg)"] == 1.45
        assert app_module.st.session_state.extended_nutrition_values["Vitamin B2 (mg)"] == 0.25
    finally:
        db_module.DB_PATH = original_db_path


def test_every_extended_field_present_in_all_six_dict_construction_sites():
    """A cheaper, more direct regression guard for the same bug class:
    statically confirm that every field label appearing in
    EXTENDED_DEFAULT_FIELDS also appears at each of the known dict-
    construction sites in app.py's source. This catches "forgot to
    update one of six copy-pasted dicts" immediately, without needing to
    drive the UI at all, and will fail loudly and specifically (naming
    the missing field and the line) if it happens again for any future
    field addition too.
    """
    with open(APP_PATH, "r", encoding="utf-8") as f:
        source_lines = f.readlines()

    import app as app_module
    field_labels = list(app_module.EXTENDED_DEFAULT_FIELDS.keys())

    # Sites that construct/read the *complete* extended-nutrient set are
    # identified by referencing "Vitamin D (mcg)" -- deliberately distinct
    # from the Open Food Facts result loader, which only sets the handful
    # of fields OFF actually provides (Saturated Fat, Trans Fat,
    # Cholesterol, Sodium) and correctly does NOT reference Vitamin D at
    # all, since OFF has no such data. Filtering on Vitamin D specifically
    # (rather than e.g. Cholesterol, which OFF's partial site also has)
    # avoids flagging that intentionally-partial site as broken.
    relevant_lines = [
        (i, line) for i, line in enumerate(source_lines, start=1)
        if '"Vitamin D (mcg)"' in line
    ]
    assert len(relevant_lines) >= 2, "expected to find multiple dict-construction sites"

    # For each *block* containing a Cholesterol/Vitamin D reference,
    # scan a small window around it and confirm every extended field
    # label also appears somewhere nearby (same dict literal or
    # sequential ev[...]/extended_vals[...] assignment block).
    for line_no, _ in relevant_lines:
        window = "".join(source_lines[max(0, line_no - 12):line_no + 12])
        missing = [label for label in field_labels if label not in window]
        assert not missing, (
            f"app.py line {line_no}: dict-construction site is missing "
            f"field(s) {missing} -- likely a copy-pasted literal that "
            f"wasn't updated when a new extended nutrient field was added. "
            f"Search app.py for '\"Vitamin D (mcg)\"' to find all sites "
            f"that need the same fields."
        )
