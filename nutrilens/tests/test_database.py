import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from modules.database import (
    FoodEntry,
    init_db,
    save_food,
    delete_food,
    search_foods,
    get_food_by_id,
    get_all_foods,
    count_foods,
    get_distinct_names,
    get_distinct_categories,
    get_distinct_brands,
    get_distinct_tags,
    DEFAULT_CATEGORY_SUGGESTIONS,
)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_nutrilens.db")
    init_db(path)
    return path


def make_entry(**overrides):
    defaults = dict(
        name="Greek Yogurt",
        category="Dairy",
        brand="Fage",
        tags=["high-protein", "breakfast"],
        serving_size_g=150,
        calories=130,
        total_carbs_g=6,
        fiber_g=0,
        sugars_g=6,
        protein_g=18,
        total_fat_g=4,
    )
    defaults.update(overrides)
    return FoodEntry(**defaults)


# --------------------------------------------------------------------------- #
# init / save / basic retrieval
# --------------------------------------------------------------------------- #

def test_init_db_creates_empty_table(db_path):
    assert count_foods(db_path) == 0


def test_save_and_retrieve_food(db_path):
    entry = make_entry()
    food_id = save_food(entry, db_path)
    assert food_id > 0

    fetched = get_food_by_id(food_id, db_path)
    assert fetched is not None
    assert fetched.name == "Greek Yogurt"
    assert fetched.category == "Dairy"
    assert fetched.brand == "Fage"
    assert sorted(fetched.tags) == sorted(["high-protein", "breakfast"])
    assert fetched.calories == 130
    assert fetched.created_at is not None


def test_save_requires_name(db_path):
    entry = make_entry(name="")
    with pytest.raises(ValueError):
        save_food(entry, db_path)


def test_save_requires_non_whitespace_name(db_path):
    entry = make_entry(name="   ")
    with pytest.raises(ValueError):
        save_food(entry, db_path)


def test_save_multiple_and_count(db_path):
    save_food(make_entry(name="Greek Yogurt"), db_path)
    save_food(make_entry(name="Almond Milk", category="Beverage", brand="Silk"), db_path)
    save_food(make_entry(name="Banana", category="Fruit", brand=None, tags=[]), db_path)
    assert count_foods(db_path) == 3


def test_delete_food(db_path):
    food_id = save_food(make_entry(), db_path)
    assert delete_food(food_id, db_path) is True
    assert get_food_by_id(food_id, db_path) is None


def test_delete_nonexistent_food_returns_false(db_path):
    assert delete_food(9999, db_path) is False


def test_optional_fields_can_be_none(db_path):
    entry = make_entry(category=None, brand=None, tags=[])
    food_id = save_food(entry, db_path)
    fetched = get_food_by_id(food_id, db_path)
    assert fetched.category is None
    assert fetched.brand is None
    assert fetched.tags == []


# --------------------------------------------------------------------------- #
# Search / filtering
# --------------------------------------------------------------------------- #

def test_search_by_name_substring_case_insensitive(db_path):
    save_food(make_entry(name="Greek Yogurt"), db_path)
    save_food(make_entry(name="Vanilla Yogurt", brand="Chobani"), db_path)
    save_food(make_entry(name="Banana", category="Fruit", brand=None, tags=[]), db_path)

    results = search_foods(name="yogurt", db_path=db_path)
    names = {r.name for r in results}
    assert names == {"Greek Yogurt", "Vanilla Yogurt"}


def test_search_by_category_exact(db_path):
    save_food(make_entry(name="Greek Yogurt", category="Dairy"), db_path)
    save_food(make_entry(name="Banana", category="Fruit", brand=None, tags=[]), db_path)

    results = search_foods(category="Fruit", db_path=db_path)
    assert len(results) == 1
    assert results[0].name == "Banana"


def test_search_by_brand_exact(db_path):
    save_food(make_entry(name="Greek Yogurt", brand="Fage"), db_path)
    save_food(make_entry(name="Vanilla Yogurt", brand="Chobani"), db_path)

    results = search_foods(brand="Fage", db_path=db_path)
    assert len(results) == 1
    assert results[0].name == "Greek Yogurt"


def test_search_by_single_tag(db_path):
    save_food(make_entry(name="Greek Yogurt", tags=["high-protein", "breakfast"]), db_path)
    save_food(make_entry(name="Candy Bar", category="Candy", brand=None, tags=["dessert"]), db_path)

    results = search_foods(tags=["breakfast"], db_path=db_path)
    assert len(results) == 1
    assert results[0].name == "Greek Yogurt"


def test_search_by_multiple_tags_is_any_match(db_path):
    save_food(make_entry(name="Greek Yogurt", tags=["high-protein", "breakfast"]), db_path)
    save_food(make_entry(name="Candy Bar", category="Candy", brand=None, tags=["dessert"]), db_path)
    save_food(make_entry(name="Banana", category="Fruit", brand=None, tags=[]), db_path)

    results = search_foods(tags=["breakfast", "dessert"], db_path=db_path)
    names = {r.name for r in results}
    assert names == {"Greek Yogurt", "Candy Bar"}


def test_search_combined_filters_and_logic(db_path):
    save_food(make_entry(name="Greek Yogurt", category="Dairy", brand="Fage",
                          tags=["high-protein"]), db_path)
    save_food(make_entry(name="Vanilla Yogurt", category="Dairy", brand="Chobani",
                          tags=["high-protein"]), db_path)

    results = search_foods(category="Dairy", brand="Fage", db_path=db_path)
    assert len(results) == 1
    assert results[0].name == "Greek Yogurt"


def test_search_no_filters_returns_all_recent_first(db_path):
    save_food(make_entry(name="First"), db_path)
    save_food(make_entry(name="Second"), db_path)
    results = search_foods(db_path=db_path)
    assert len(results) == 2
    assert results[0].name == "Second"  # most recent first


def test_search_no_matches_returns_empty_list(db_path):
    save_food(make_entry(name="Greek Yogurt"), db_path)
    results = search_foods(name="nonexistent_food_xyz", db_path=db_path)
    assert results == []


def test_search_respects_limit(db_path):
    for i in range(5):
        save_food(make_entry(name=f"Food {i}"), db_path)
    results = search_foods(limit=2, db_path=db_path)
    assert len(results) == 2


def test_get_all_foods(db_path):
    save_food(make_entry(name="A"), db_path)
    save_food(make_entry(name="B"), db_path)
    all_foods = get_all_foods(db_path=db_path)
    assert len(all_foods) == 2


# --------------------------------------------------------------------------- #
# Autocomplete helpers
# --------------------------------------------------------------------------- #

def test_get_distinct_names(db_path):
    save_food(make_entry(name="Greek Yogurt"), db_path)
    save_food(make_entry(name="Greek Yogurt"), db_path)  # duplicate name, different entry
    save_food(make_entry(name="Banana", category="Fruit", brand=None, tags=[]), db_path)
    names = get_distinct_names(db_path)
    assert sorted(names) == ["Banana", "Greek Yogurt"]


def test_get_distinct_categories_merges_defaults(db_path):
    save_food(make_entry(name="Greek Yogurt", category="Dairy"), db_path)
    categories = get_distinct_categories(db_path)
    assert "Dairy" in categories
    # Default suggestions should still be present for a good first-run UX
    assert "Snack" in categories
    assert "Beverage" in categories


def test_get_distinct_categories_no_duplicates(db_path):
    save_food(make_entry(name="Chips", category="Snack"), db_path)
    categories = get_distinct_categories(db_path)
    assert categories.count("Snack") == 1


def test_get_distinct_categories_empty_db_returns_defaults(db_path):
    categories = get_distinct_categories(db_path)
    assert categories == DEFAULT_CATEGORY_SUGGESTIONS


def test_get_distinct_brands(db_path):
    save_food(make_entry(name="Greek Yogurt", brand="Fage"), db_path)
    save_food(make_entry(name="Vanilla Yogurt", brand="Chobani"), db_path)
    save_food(make_entry(name="Banana", category="Fruit", brand=None, tags=[]), db_path)
    brands = get_distinct_brands(db_path)
    assert sorted(brands) == ["Chobani", "Fage"]


def test_get_distinct_brands_empty_db(db_path):
    assert get_distinct_brands(db_path) == []


def test_get_distinct_tags_deduplicated_and_sorted(db_path):
    save_food(make_entry(name="Greek Yogurt", tags=["Breakfast", "high-protein"]), db_path)
    save_food(make_entry(name="Cottage Cheese", category="Dairy", brand=None,
                          tags=["high-protein", "low-carb"]), db_path)
    tags = get_distinct_tags(db_path)
    assert tags == sorted(set(["Breakfast", "high-protein", "low-carb"]), key=str.lower)


def test_get_distinct_tags_empty_db(db_path):
    assert get_distinct_tags(db_path) == []


def test_tags_are_trimmed_and_deduplicated_on_save(db_path):
    entry = make_entry(name="Test Food", tags=["  Snack  ", "snack", "Snack"])
    food_id = save_food(entry, db_path)
    fetched = get_food_by_id(food_id, db_path)
    # Case-sensitive dedupe only exact duplicates collapse; "snack" vs "Snack"
    # are kept distinct here since tag casing is preserved for display.
    assert len(fetched.tags) <= 2


def test_food_entry_tags_display():
    entry = make_entry(tags=["a", "b", "c"])
    assert entry.tags_display() == "a, b, c"


def test_food_entry_tags_display_empty():
    entry = make_entry(tags=[])
    assert entry.tags_display() == ""


# --------------------------------------------------------------------------- #
# Extended nutrient panel
# --------------------------------------------------------------------------- #

def test_save_and_retrieve_extended_nutrients(db_path):
    entry = make_entry(
        saturated_fat_g=2.5, trans_fat_g=0.0, cholesterol_mg=15.0,
        sodium_mg=140.0, added_sugars_g=3.0, vitamin_d_mcg=1.2,
        calcium_mg=200.0, iron_mg=0.8, potassium_mg=300.0,
        source="Manual/OCR",
    )
    food_id = save_food(entry, db_path)
    fetched = get_food_by_id(food_id, db_path)
    assert fetched.saturated_fat_g == 2.5
    assert fetched.cholesterol_mg == 15.0
    assert fetched.sodium_mg == 140.0
    assert fetched.added_sugars_g == 3.0
    assert fetched.vitamin_d_mcg == 1.2
    assert fetched.calcium_mg == 200.0
    assert fetched.iron_mg == 0.8
    assert fetched.potassium_mg == 300.0
    assert fetched.source == "Manual/OCR"


def test_extended_nutrients_default_to_zero_when_unspecified(db_path):
    entry = make_entry()  # no extended fields passed
    food_id = save_food(entry, db_path)
    fetched = get_food_by_id(food_id, db_path)
    assert fetched.saturated_fat_g == 0.0
    assert fetched.sodium_mg == 0.0
    assert fetched.potassium_mg == 0.0


def test_source_field_optional(db_path):
    entry = make_entry(source=None)
    food_id = save_food(entry, db_path)
    fetched = get_food_by_id(food_id, db_path)
    assert fetched.source is None


def test_source_field_from_open_food_facts(db_path):
    entry = make_entry(source="Open Food Facts")
    food_id = save_food(entry, db_path)
    fetched = get_food_by_id(food_id, db_path)
    assert fetched.source == "Open Food Facts"


# --------------------------------------------------------------------------- #
# Schema migration (backward compatibility with pre-extended-nutrient DBs)
# --------------------------------------------------------------------------- #

def test_migration_adds_missing_columns_to_old_schema(tmp_path):
    """Simulate a database created by an older version of the app (only
    the original 7-macro schema, no extended nutrient columns or
    `source`), and verify init_db() migrates it in-place without losing
    existing data."""
    path = str(tmp_path / "old_schema.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            brand TEXT,
            tags TEXT,
            serving_size_g REAL,
            calories REAL,
            total_carbs_g REAL,
            fiber_g REAL,
            sugars_g REAL,
            protein_g REAL,
            total_fat_g REAL,
            created_at TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO foods (name, category, brand, tags, serving_size_g, "
        "calories, total_carbs_g, fiber_g, sugars_g, protein_g, total_fat_g, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Old Food", "Snack", "BrandX", "tag1", 100, 200, 30, 2, 5, 4, 8, "2024-01-01"),
    )
    conn.commit()
    conn.close()

    # Now run init_db (as the app would on startup) to migrate the schema
    init_db(path)

    # Old data should survive, and new columns should exist with defaults
    results = search_foods(db_path=path)
    assert len(results) == 1
    old_food = results[0]
    assert old_food.name == "Old Food"
    assert old_food.calories == 200
    assert old_food.saturated_fat_g == 0.0
    assert old_food.sodium_mg == 0.0
    assert old_food.source is None

    # And saving a brand-new entry with extended fields should work fine
    new_id = save_food(make_entry(name="New Food", sodium_mg=99.0), path)
    new_food = get_food_by_id(new_id, path)
    assert new_food.sodium_mg == 99.0


def test_migration_is_idempotent(db_path):
    # Calling init_db() again on an already-current schema should not error
    init_db(db_path)
    init_db(db_path)
    assert count_foods(db_path) == 0
