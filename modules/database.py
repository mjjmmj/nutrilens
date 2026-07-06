"""
database.py
============
Persistent storage for scanned foods, backed by SQLite.

Design goals:
- Zero external services / no API keys — a single local .db file.
- UI-independent: every function here is plain Python + sqlite3, so it's
  unit-testable without Streamlit (point DB_PATH at a tmp file in tests).
- Safe for Streamlit's rerun model: each call opens and closes its own
  short-lived connection (`check_same_thread=False`, but no long-lived
  shared connection object), which avoids cross-thread/session issues
  without needing a connection pool for an app of this size.

Schema (table `foods`):
    id             INTEGER PRIMARY KEY
    name           TEXT NOT NULL        -- e.g. "Greek Yogurt"
    category       TEXT                 -- e.g. "Dairy"
    brand          TEXT                 -- e.g. "Fage"
    tags           TEXT                 -- comma-separated, e.g. "high-protein,breakfast"
    serving_size_g REAL
    calories       REAL
    total_carbs_g  REAL
    fiber_g        REAL
    sugars_g       REAL
    protein_g      REAL
    total_fat_g    REAL
    saturated_fat_g REAL
    trans_fat_g     REAL
    cholesterol_mg  REAL
    sodium_mg       REAL
    added_sugars_g  REAL
    vitamin_d_mcg   REAL
    calcium_mg      REAL
    iron_mg         REAL
    potassium_mg    REAL
    source          TEXT                 -- e.g. "Open Food Facts", "Manual/OCR"
    created_at     TEXT                 -- ISO 8601 timestamp

The extended nutrient columns (saturated_fat_g through potassium_mg) were
added after the initial release. `init_db()` runs a lightweight migration
on every startup that adds any missing columns to an existing database
file via `ALTER TABLE`, so upgrading the app doesn't break a database
someone already has on disk from an earlier version.

NOTE ON DEPLOYMENT: on Streamlit Community Cloud, the filesystem is
ephemeral — the database resets whenever the app restarts or redeploys.
For durable, multi-user persistence in production, swap this module's
connection logic for a hosted database (Postgres/Supabase/etc.) while
keeping the same function signatures used by app.py.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "nutrilens.db")
DB_PATH = os.path.normpath(DB_PATH)

# A handful of common categories seeded so the category autocomplete isn't
# completely empty (and therefore not disabled) on a brand-new database.
DEFAULT_CATEGORY_SUGGESTIONS = [
    "Snack", "Beverage", "Dairy", "Grain", "Protein", "Fruit", "Vegetable",
    "Frozen Meal", "Condiment", "Fast Food", "Baked Good", "Candy", "Other",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS foods (
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
    saturated_fat_g REAL,
    trans_fat_g REAL,
    cholesterol_mg REAL,
    sodium_mg REAL,
    added_sugars_g REAL,
    vitamin_d_mcg REAL,
    calcium_mg REAL,
    iron_mg REAL,
    potassium_mg REAL,
    source TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_foods_name ON foods(name);
CREATE INDEX IF NOT EXISTS idx_foods_category ON foods(category);
CREATE INDEX IF NOT EXISTS idx_foods_brand ON foods(brand);
"""

# Columns added after the initial release. Used by `_migrate_schema` to
# bring an older database file up to date without losing existing data.
_MIGRATION_COLUMNS = {
    "saturated_fat_g": "REAL DEFAULT 0",
    "trans_fat_g": "REAL DEFAULT 0",
    "cholesterol_mg": "REAL DEFAULT 0",
    "sodium_mg": "REAL DEFAULT 0",
    "added_sugars_g": "REAL DEFAULT 0",
    "vitamin_d_mcg": "REAL DEFAULT 0",
    "calcium_mg": "REAL DEFAULT 0",
    "iron_mg": "REAL DEFAULT 0",
    "potassium_mg": "REAL DEFAULT 0",
    "source": "TEXT",
}


@dataclass
class FoodEntry:
    """A saved food record, per serving as printed on its label."""

    name: str
    category: Optional[str] = None
    brand: Optional[str] = None
    tags: list = field(default_factory=list)  # list[str]
    serving_size_g: float = 100.0
    calories: float = 0.0
    total_carbs_g: float = 0.0
    fiber_g: float = 0.0
    sugars_g: float = 0.0
    protein_g: float = 0.0
    total_fat_g: float = 0.0

    # Extended nutrient panel (same rationale as calculations.NutritionFacts
    # and ocr_parser.ParsedNutrition -- captured because it's on the
    # label, even though predictions only use the macros above).
    saturated_fat_g: float = 0.0
    trans_fat_g: float = 0.0
    cholesterol_mg: float = 0.0
    sodium_mg: float = 0.0
    added_sugars_g: float = 0.0
    vitamin_d_mcg: float = 0.0
    calcium_mg: float = 0.0
    iron_mg: float = 0.0
    potassium_mg: float = 0.0

    source: Optional[str] = None  # e.g. "Open Food Facts", "Manual/OCR"
    id: Optional[int] = None
    created_at: Optional[str] = None

    def tags_display(self) -> str:
        return ", ".join(self.tags) if self.tags else ""


# --------------------------------------------------------------------------- #
# Connection / schema management
# --------------------------------------------------------------------------- #

def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Create the foods table (and indexes) if they don't already exist,
    then migrate any missing columns into an existing table. Safe to call
    on every app startup."""
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        _migrate_schema(conn)
    finally:
        conn.close()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add any columns introduced after the initial release to an
    existing database file, so upgrading the app doesn't crash or lose
    data for someone who already has a `foods` table on disk from an
    older version without the extended nutrient columns."""
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(foods)").fetchall()
    }
    for column, column_type in _MIGRATION_COLUMNS.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE foods ADD COLUMN {column} {column_type}")
    conn.commit()


def _tags_to_str(tags: list) -> str:
    cleaned = [t.strip() for t in tags if t and t.strip()]
    return ",".join(sorted(set(cleaned), key=str.lower))


def _tags_from_str(raw: Optional[str]) -> list:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _row_to_entry(row: sqlite3.Row) -> FoodEntry:
    # Use .get()-style access via row.keys() so this stays safe even if
    # called against a row from a not-yet-migrated older schema (defensive;
    # init_db() always migrates first in normal operation).
    available = row.keys()

    def get(col: str, default: float = 0.0) -> float:
        return (row[col] if col in available else None) or default

    return FoodEntry(
        id=row["id"],
        name=row["name"],
        category=row["category"],
        brand=row["brand"],
        tags=_tags_from_str(row["tags"]),
        serving_size_g=get("serving_size_g"),
        calories=get("calories"),
        total_carbs_g=get("total_carbs_g"),
        fiber_g=get("fiber_g"),
        sugars_g=get("sugars_g"),
        protein_g=get("protein_g"),
        total_fat_g=get("total_fat_g"),
        saturated_fat_g=get("saturated_fat_g"),
        trans_fat_g=get("trans_fat_g"),
        cholesterol_mg=get("cholesterol_mg"),
        sodium_mg=get("sodium_mg"),
        added_sugars_g=get("added_sugars_g"),
        vitamin_d_mcg=get("vitamin_d_mcg"),
        calcium_mg=get("calcium_mg"),
        iron_mg=get("iron_mg"),
        potassium_mg=get("potassium_mg"),
        source=row["source"] if "source" in available else None,
        created_at=row["created_at"],
    )


# --------------------------------------------------------------------------- #
# Write operations
# --------------------------------------------------------------------------- #

def save_food(entry: FoodEntry, db_path: str = DB_PATH) -> int:
    """Insert a new food record. Returns the new row's id.

    Raises ValueError if `name` is blank, since a nameless entry can't be
    meaningfully searched for later.
    """
    if not entry.name or not entry.name.strip():
        raise ValueError("Food name is required to save an entry.")

    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO foods (
                name, category, brand, tags, serving_size_g, calories,
                total_carbs_g, fiber_g, sugars_g, protein_g, total_fat_g,
                saturated_fat_g, trans_fat_g, cholesterol_mg, sodium_mg,
                added_sugars_g, vitamin_d_mcg, calcium_mg, iron_mg,
                potassium_mg, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.name.strip(),
                (entry.category or "").strip() or None,
                (entry.brand or "").strip() or None,
                _tags_to_str(entry.tags),
                entry.serving_size_g,
                entry.calories,
                entry.total_carbs_g,
                entry.fiber_g,
                entry.sugars_g,
                entry.protein_g,
                entry.total_fat_g,
                entry.saturated_fat_g,
                entry.trans_fat_g,
                entry.cholesterol_mg,
                entry.sodium_mg,
                entry.added_sugars_g,
                entry.vitamin_d_mcg,
                entry.calcium_mg,
                entry.iron_mg,
                entry.potassium_mg,
                (entry.source or "").strip() or None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def delete_food(food_id: int, db_path: str = DB_PATH) -> bool:
    """Delete a saved food by id. Returns True if a row was removed."""
    conn = _connect(db_path)
    try:
        cursor = conn.execute("DELETE FROM foods WHERE id = ?", (food_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Read / search operations
# --------------------------------------------------------------------------- #

def search_foods(
    name: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    tags: Optional[list] = None,
    limit: int = 50,
    db_path: str = DB_PATH,
) -> list:
    """Search saved foods with optional filters, all combined with AND.

    - `name`: substring match, case-insensitive (fuzzy-ish free text).
    - `category`, `brand`: exact match (use values from autocomplete).
    - `tags`: list of tags; a food matches if it has ANY of the given tags.
    - Results are ordered most-recently-saved first.
    """
    conn = _connect(db_path)
    try:
        clauses = []
        params: list = []

        if name and name.strip():
            clauses.append("LOWER(name) LIKE ?")
            params.append(f"%{name.strip().lower()}%")

        if category and category.strip():
            clauses.append("LOWER(category) = ?")
            params.append(category.strip().lower())

        if brand and brand.strip():
            clauses.append("LOWER(brand) = ?")
            params.append(brand.strip().lower())

        if tags:
            tag_clauses = []
            for tag in tags:
                tag = tag.strip().lower()
                if tag:
                    tag_clauses.append("LOWER(tags) LIKE ?")
                    params.append(f"%{tag}%")
            if tag_clauses:
                clauses.append("(" + " OR ".join(tag_clauses) + ")")

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT * FROM foods
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [_row_to_entry(r) for r in rows]
    finally:
        conn.close()


def get_food_by_id(food_id: int, db_path: str = DB_PATH) -> Optional[FoodEntry]:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
        return _row_to_entry(row) if row else None
    finally:
        conn.close()


def get_all_foods(limit: int = 500, db_path: str = DB_PATH) -> list:
    return search_foods(limit=limit, db_path=db_path)


def count_foods(db_path: str = DB_PATH) -> int:
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Autocomplete helpers
# --------------------------------------------------------------------------- #

def get_distinct_names(db_path: str = DB_PATH) -> list:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT name FROM foods ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [r["name"] for r in rows]
    finally:
        conn.close()


def get_distinct_categories(db_path: str = DB_PATH) -> list:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT category FROM foods WHERE category IS NOT NULL "
            "ORDER BY category COLLATE NOCASE"
        ).fetchall()
        saved = [r["category"] for r in rows]
    finally:
        conn.close()
    # Merge with default suggestions so new users see helpful starter
    # options, without duplicating anything already saved.
    merged = list(dict.fromkeys(saved + DEFAULT_CATEGORY_SUGGESTIONS))
    return merged


def get_distinct_brands(db_path: str = DB_PATH) -> list:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT brand FROM foods WHERE brand IS NOT NULL "
            "ORDER BY brand COLLATE NOCASE"
        ).fetchall()
        return [r["brand"] for r in rows]
    finally:
        conn.close()


def get_distinct_tags(db_path: str = DB_PATH) -> list:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT tags FROM foods WHERE tags IS NOT NULL AND tags != ''"
        ).fetchall()
    finally:
        conn.close()
    tag_set = set()
    for row in rows:
        tag_set.update(_tags_from_str(row["tags"]))
    return sorted(tag_set, key=str.lower)
