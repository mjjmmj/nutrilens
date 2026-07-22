# 🥗 NutriLens

Scan a nutrition-facts label with your phone camera (or upload a photo) and
get instant, educational estimates of:

1. **Insulin Load** — an algorithmic proxy for how sharply a food is likely
   to spike insulin (based on the Food Insulin Index literature).
2. **Body-Fat % Projection** — a caloric-balance projection showing what
   this food's surplus/deficit, relative to your hourly metabolic burn,
   would theoretically equate to in stored/spared fat mass.

Built with **Streamlit**, **Pillow**, **pytesseract**, **pandas**, and
**numpy**. Works on desktop and mobile browsers, using `st.camera_input`
for native device-camera capture on phones.

> ⚠️ **This is an educational approximation tool, not a medical device.**
> It does not measure real blood insulin or real-time body composition.
> See [Scientific Basis & Limitations](#scientific-basis--limitations) below.

> 📸 **New to the app?** See **[docs/TUTORIAL.md](docs/TUTORIAL.md)** for
> a complete, illustrated walkthrough of every feature with real
> screenshots — profile setup, scanning a label, the three ways to get
> nutrition data in, reading your results, and more.

---

## Features

- 📷 **Camera or gallery upload** — `st.camera_input` opens the phone
  camera directly; a file uploader is provided as a fallback for gallery
  photos or desktop use.
- 🔍 **OCR label parsing** — extracts serving size, calories, carbs, fiber,
  sugars, protein, and fat via `pytesseract`, with tolerant regex parsing
  that handles common OCR noise (missing spaces, punctuation, decimal
  commas, varying label wording). Supports **English and Japanese
  (日本語)** labels in a single pass, including mixed-language labels.
- 📷 **Built for real camera photos, not just clean scans** — corrects
  EXIF orientation (phones tag rotation as metadata rather than rotating
  pixels, which silently defeats OCR on portrait photos), and tries
  multiple preprocessing variants (contrast/sharpen, Otsu binarization,
  plain grayscale) per photo, automatically keeping whichever one parses
  the most fields — this matters a lot under real-world lighting, glare,
  and slight blur.
- ☁️ **Optional cloud OCR engines** — for photos the local engine still
  struggles with, switch to Baidu Unlimited-OCR (a free Hugging Face
  Space, no key needed) or Mistral's official OCR API (your own key,
  paid) right from the same dropdown. Both feed into the exact same
  bilingual/full-nutrient parser as local OCR. See the dedicated section
  below for the tradeoffs before relying on either.
- ✏️ **Manual override** — every OCR'd value lands in an editable
  `st.data_editor` table so users can correct misreads before calculating.
  If OCR finds nothing (blurry photo, no OCR engine installed, etc.), the
  app falls back cleanly to manual entry — it never crashes.
- 👤 **Smart profile defaults** — age, height, weight, and body-fat % can
  be left blank; the app fills gaps with literature-based baselines
  (BMI-based Deurenberg body-fat formula, gender-average default weight,
  etc.) and tells you exactly which fields were defaulted.
- 📏 **Metric or Imperial units** — kg/cm or lb/ft-in, your choice.
  Multiple servings supported (scale the whole label by portion size).
- 📊 **Clear visual output** — `st.metric`, `st.progress`, and color-coded
  categories for at-a-glance results.
- 💾 **Saved food database** — save any scanned/entered food with a name,
  category, optional brand, and free-form tags (SQLite, no external
  service needed). Search saved foods by any combination of those fields
  and load one back in a click, skipping OCR entirely on repeat foods.
  Stores the **full nutrition panel** (see below), not just macros.
- 📋 **Full nutrition panel, not just macros** — captures and saves the
  complete standard label: saturated/trans fat, cholesterol, sodium,
  added sugars, vitamin D, vitamin B1, vitamin B2, calcium, iron, and
  potassium, alongside the 7 core macros. These extra fields aren't used
  in the insulin/body-fat math (which only needs the macros), but they're
  extracted from OCR when present, editable, saved, and viewable in a
  consolidated panel.
- 🌐 **Public food database lookup** — search
  [Open Food Facts](https://world.openfoodfacts.org) (free, no API key,
  millions of branded products) by product name and load a match's full
  nutrition data directly — no photo needed at all for well-known
  packaged foods.
- ⌨️ **Autocomplete everywhere** — every name/category/brand/tag field
  (both when saving and when searching) fuzzy-filters your existing
  values as you type, and lets you type a brand-new value if nothing
  matches, via Streamlit's `accept_new_options`.
- 🛡️ **Defensive engineering** — corrupted images, empty labels, zero
  weight/height, and unknown activity levels are all handled without
  crashing the app.

---

## Project structure

```
nutrilens/
├── app.py                     # Main Streamlit application (UI + orchestration)
├── modules/
│   ├── calculations.py        # Pure-Python metabolic/nutrition math (UI-independent)
│   ├── ocr_parser.py          # Local OCR text extraction + regex field parsing
│   ├── cloud_ocr.py           # Optional cloud OCR backends (Baidu, Mistral)
│   ├── database.py            # SQLite CRUD + search for saved foods (UI-independent)
│   ├── food_database_api.py   # Open Food Facts integration (UI-independent)
│   └── user_profile.py        # Sidebar UI for collecting profile inputs
├── tests/
│   ├── test_calculations.py    # Unit tests for the calculation engine
│   ├── test_ocr_parser.py      # Unit tests for label text parsing (EN + JP)
│   ├── test_cloud_ocr.py       # Unit tests for cloud OCR (mocked HTTP/gradio_client)
│   ├── test_database.py        # Unit tests for the food database
│   ├── test_food_database_api.py  # Unit tests for Open Food Facts (mocked HTTP)
│   └── test_app_integration.py    # AppTest-based end-to-end UI integration tests
├── docs/
│   ├── TUTORIAL.md             # Illustrated user tutorial (this is what most people want)
│   ├── screenshots/            # Real screenshots used in TUTORIAL.md
│   └── capture_screenshots.py  # Playwright script that generated them (dev tool)
├── data/                      # Created automatically; holds nutrilens.db (gitignored)
├── .streamlit/
│   └── config.toml            # Theme + server configuration
├── requirements.txt           # Python dependencies
├── packages.txt               # System (apt) dependencies: tesseract-ocr + jpn language data
├── .gitignore
└── README.md
```

The calculation engine (`modules/calculations.py`), the database layer
(`modules/database.py`), and the public food database client
(`modules/food_database_api.py`) have **zero Streamlit dependency**, so
they can be unit tested, reused in a CLI, or swapped into a different
frontend without modification.

---

## Running locally

```bash
# 1. Clone / copy this project, then create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install the Tesseract OCR binary (pytesseract is just a wrapper —
#    it needs the actual `tesseract` executable on your system), plus the
#    Japanese trained-data files for Japanese label support:
#    macOS:    brew install tesseract tesseract-lang
#    Ubuntu:   sudo apt-get install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert
#    Windows:  https://github.com/UB-Mannheim/tesseract/wiki
#              (select "Japanese" in the installer's language options)

# 4. Run the app
streamlit run app.py
```

Open the URL Streamlit prints (typically `http://localhost:8501`). On your
phone, use the "Network URL" shown in the terminal (same Wi-Fi network) to
test camera capture on a real device.

---

## Deploying to Streamlit Community Cloud

1. Push this project to a GitHub repository.
2. On [share.streamlit.io](https://share.streamlit.io), create a new app
   pointing at `app.py`.
3. Streamlit Cloud automatically:
   - installs everything in `requirements.txt`, and
   - installs everything in `packages.txt` via `apt-get` — this is what
     provides the `tesseract-ocr` binary and the `tesseract-ocr-jpn` /
     `tesseract-ocr-jpn-vert` Japanese trained-data files that
     `pytesseract` calls out to. **Don't skip `packages.txt`** — without
     it, `pytesseract` will raise `TesseractNotFoundError` in the cloud
     environment (the app catches this gracefully and falls back to
     manual entry, but OCR won't work), and without the `-jpn` packages
     specifically, Japanese labels will silently fail to parse even
     though English labels work fine (the app shows a warning banner in
     this case, via `tesseract_japanese_available()`).

No secrets or API keys are required — everything runs locally in the
Streamlit process.

---

## How the predictions work

### 1. Metabolic baseline
- **BMI** = weight(kg) / height(m)²
- **Body Fat %** (Deurenberg formula, used only when not provided):
  `BF% = 1.20·BMI + 0.23·age − 10.8·genderFactor − 5.4` (Male=1, Female=0)
- **BMR** (Mifflin-St Jeor equation)
- **TDEE** = BMR × activity multiplier (1.2 / 1.375 / 1.55 / 1.725)

### 2. Insulin Load (Food Insulin Index proxy)
```
Insulin Load = Carbs − (0.5 × Fiber) + (0.56 × Protein) + (0.15 × Fat)
```
Scored against a reference: a standard 50g oral-glucose-tolerance-test
dose (~insulin load of 50) causes an illustrative ~30 µIU/mL spike in a
healthy adult. Your food's score is scaled proportionally against that
reference and bucketed into Low (<20) / Medium (20–45) / High (≥45).

### 3. Body-fat % change projection
1. **Gross calories** — uses the label's stated calorie count if present;
   otherwise derives it from macros via Atwater factors (protein/carbs
   4 kcal/g, fat 9 kcal/g, fiber ~2 kcal/g).
2. **Thermic Effect of Food (TEF)** — subtracts the energy your body
   burns digesting the food, using literature midpoints: protein 25%,
   carbs 10%, fat 1.5%.
3. **Net energy balance** — compares net metabolizable energy against
   your **hourly** TDEE baseline (TDEE ÷ 24).
4. **Fat-mass equivalent** — surplus/deficit ÷ 7700 kcal/kg (or
   ÷ 3500 kcal/lb), expressed as a percentage-point shift relative to
   your current body weight.

---

## Saved food database & search

Every scanned or manually-entered food can be saved with:

- **Name** (required)
- **Category** (optional — e.g. Dairy, Snack, Beverage; a starter list of
  common categories is suggested even before you've saved anything)
- **Brand** (optional)
- **Tags** (optional, any number — e.g. `high-protein`, `breakfast`,
  `gluten-free`)
- All 7 nutrition fields, per serving

Saved foods live in a local SQLite file at `data/nutrilens.db`, created
automatically on first run — no external database or API key needed.

**Searching:** the "🔎 Search your saved foods" panel lets you filter by
any combination of name, category, brand, and tags, then pick a match
from the results and load it straight into the current scan — skipping
the camera/OCR step entirely for foods you've logged before.

**Autocomplete:** every name/category/brand/tag field (both when saving
and when searching) is a fuzzy-filterable dropdown — start typing and
matching existing values narrow down live — and you can always type a
brand-new value if nothing matches, via `st.selectbox`/`st.multiselect`
with `accept_new_options=True`. Fields fall back to a plain text input
only when there are zero existing values yet to suggest.

> ⚠️ **Streamlit Community Cloud note:** that platform's filesystem is
> ephemeral, so `data/nutrilens.db` is wiped on every app restart or
> redeploy there. For durable multi-user persistence in production,
> replace the connection logic in `modules/database.py` with a hosted
> database (e.g. Postgres/Supabase) — the function signatures used by
> `app.py` (`save_food`, `search_foods`, `get_distinct_*`, etc.) can stay
> the same. Running locally, or on any host with a persistent disk, the
> SQLite file persists normally across restarts.

---

## Full nutrient panel & public database lookup

**Beyond the 7 macros**, NutriLens now captures the complete standard
nutrition label:

| Field | Unit | Used in predictions? |
|---|---|---|
| Serving size, calories, carbs, fiber, sugars, protein, fat | g / kcal | ✅ yes |
| Saturated fat, trans fat | g | Saved only |
| Cholesterol, sodium | mg | Saved only |
| Added sugars | g | Saved only |
| Vitamin D | mcg | Saved only |
| Calcium, iron, potassium | mg | Saved only |

The extended fields aren't part of the insulin/body-fat math (which only
needs the macros), but they're extracted by OCR when present on the
label, editable in an "➕ Additional nutrients" section, saved to the
database, and viewable together in a "📋 Full nutrition panel" summary.
OCR patterns for these fields cover both English and Japanese label
wording, including the 食塩相当量 → sodium (mg) conversion Japanese labels
require (see the OCR reliability section above).

**Auto-extraction from a public food database:** the
"🌐 Search a public food database" panel queries
[Open Food Facts](https://world.openfoodfacts.org) — a free,
community-maintained database of millions of branded products, no API
key required — by product name, and loads a match's full nutrition data
(including the extended fields where OFF has them) with one click. This
is the fastest path for common packaged foods and doesn't need a photo
at all.

**✅ Highlighting auto-filled values.** Every value pulled in automatically
— by local OCR, a cloud OCR engine, or an Open Food Facts lookup — is
marked with a "✅ Auto-filled" tag in a *Source* column on both editable
tables, distinct from "✏️ Manual" for anything left at its default or
typed in by hand. This makes it obvious at a glance which numbers came
from the scan/lookup and deserve a closer look, versus which ones are
just a zero placeholder waiting to be filled in. If you edit an
auto-filled value yourself, it correctly switches to "✏️ Manual" — the
highlight only ever reflects what the *last* scan/lookup actually found,
not what's merely still sitting in the field.

**A Streamlit quirk worth knowing about (fixed):** editing a cell in
either table used to sometimes require typing a value twice before it
"stuck" — the first edit would visually revert, and only the second
identical edit would actually register. The cause: both tables are
reconstructed fresh from session state on every rerun *and* given a
fixed widget key, and Streamlit's `data_editor` can momentarily conflict
between its own internally-tracked edit and that freshly-passed data on
the very rerun the edit happens. The fix versions each table's key,
bumping it only at the exact moments this app intentionally overwrites
the values from outside (a new OCR scan, an Open Food Facts/saved-food
load, or Reset) — so a normal edit reliably registers on the first try,
while a programmatic update still cleanly replaces what's shown.

**A more serious bug that fix briefly exposed:** versioning the table
key made a *second*, pre-existing bug much more visible — manual edits
stopped registering at all once a photo had ever been scanned. The real
cause: `st.camera_input`/`st.file_uploader` keep returning the same
captured file on every rerun until it's explicitly replaced, and the OCR
code re-ran unconditionally whenever a captured image was present —
meaning it silently re-ran (and reset both tables back to the original
OCR result) on *every* interaction anywhere on the page, not just when a
new photo was taken. Editing an unrelated cell, changing servings, even
just switching tabs would trigger a full script rerun, which re-ran OCR
on the same photo and stomped on whatever the person had just typed. The
fix hashes the captured image's bytes and only actually runs OCR when
that hash changes (i.e. a genuinely new photo), remembering the last
result for display in the meantime — manual edits now stick immediately,
even after scanning a label first.

A few implementation notes:
- OFF reports nutrients per 100g and, when available, per serving; the
  per-serving values are preferred when present (`modules/food_database_api.py`),
  falling back to per-100g otherwise (with serving size defaulting to 100g).
- OFF stores sodium and cholesterol in grams like everything else; this
  app converts them to mg for consistency with US label conventions and
  the rest of the app.
- Since Open Food Facts is crowd-sourced, data quality varies — treat a
  loaded result the same way you'd treat an OCR scan: a starting point to
  review, not an authoritative source. All values remain fully editable
  after loading.
- Every food record also stores where its data came from
  (`source`: "Open Food Facts" or "Manual/OCR"), shown next to the save
  form when it isn't your own manual entry.
- **Transport & rate limits (important):** Open Food Facts' own API docs
  state plainly that full-text product search has no v2/v3 REST
  replacement yet — `/cgi/search.pl` (what this app's official
  `openfoodfacts` SDK calls internally) remains the documented,
  currently-intended way to do it. That endpoint is explicitly
  rate-limited to **10 requests/minute/IP**, with a shared global
  capacity cap on top — Open Food Facts' docs state a **HTTP 503 is the
  expected response when either limit is exceeded**, and explicitly warn
  integrators not to use it for search-as-you-type. An earlier version of
  this app did exactly that by accident: it re-ran the search on *every*
  script rerun as long as the search box was non-empty, and Streamlit
  reruns the whole script on *any* widget interaction anywhere on the
  page — so editing an unrelated nutrition cell, changing servings, or
  switching OCR engines silently re-fired the same Open Food Facts search
  every time, right into that rate limit. Two fixes address this:
  1. **An explicit "🔍 Search" button**, with the last-searched query and
     its results cached in session state — a search only actually calls
     Open Food Facts when the term is new, not on every unrelated rerun.
  2. **Automatic retry with a short backoff on 429/503** specifically
     (not on other errors), since Open Food Facts' own docs frame those
     two as transient/rate-limit conditions worth a brief retry rather
     than failing immediately.
- **Error handling:** a genuinely empty search ("no products matched")
  and an actual failure (rate limit, timeout, server outage, no
  internet) are deliberately kept distinct — the app raises a specific
  `OpenFoodFactsError` for real failures with a message that says what
  went wrong (e.g. "rate limit reached, try again shortly"), rather than
  collapsing every failure mode into the same unhelpful "no matches
  found" message. All of this — including the retry behavior and the
  "don't re-search on an unrelated rerun" caching — is unit/integration
  tested (the latter via Streamlit's `AppTest`, driving the actual search
  button and a separate widget to confirm the call count doesn't
  increase) so it doesn't depend on Open Food Facts' live uptime to verify.

---

## Future-proofing the third-party integrations

Three integrations in this app — Open Food Facts, Baidu Unlimited-OCR,
and Mistral OCR — depend on services this app doesn't control, each with
its own history of interface changes (Open Food Facts' search backend
migration is a real example that broke an earlier version of this app;
see above). Rather than hardcoding one exact response shape and hoping it
never changes, each integration has layered fallbacks so a future API
change degrades gracefully instead of breaking outright. Full details are
in each module's own "MAINTENANCE" docstring, but in summary:

**`modules/food_database_api.py` (Open Food Facts):**
- If a future SDK version renames/removes `api.product.text_search` or
  `api.product.get`, the module catches that and falls back to a raw
  REST call against the same endpoints the SDK uses internally.
- If Open Food Facts' response shape changes (e.g. `"products"` becomes
  `"hits"` as part of the ongoing search backend migration), a small
  list of plausible key names is tried rather than assuming one forever.
- Each nutrient field is looked up via a list of plausible key spellings
  (`_NUTRIENT_KEY_ALIASES`) — if Open Food Facts renames a nutrient key,
  add the new spelling to that list rather than changing extraction logic.
- `check_sdk_compatibility()` does a soft, non-blocking version check and
  surfaces a note in the UI if the installed SDK looks meaningfully
  outside the tested range — informational only, never blocks the feature.

**`modules/cloud_ocr.py` (Baidu Unlimited-OCR):**
- Tries the currently-known API call shape first
  (`api_name="/run_ocr"`, specific parameter names).
- If that fails for any reason, it automatically asks the Space itself
  what endpoints currently exist (`client.view_api()`) and matches
  parameters *by label* (looking for words like "image"/"mode"/"prompt"
  rather than exact names) instead of assuming a fixed signature. Only if
  both attempts fail does it raise an error — and that error names both
  attempts and links to the Space's live API page.
- Once a strategy is confirmed working, it's remembered for the rest of
  the process so later calls don't repeat an already-failed attempt.
- Response parsing checks a few plausible key names (`text`, `output`,
  `result`, `markdown`, `content`) rather than only one.

**`modules/cloud_ocr.py` (Mistral OCR):**
- Maintains an ordered list of model IDs to try (`_MISTRAL_MODEL_CANDIDATES`).
  If the primary model is rejected as unknown/unavailable (distinguished
  from other 400-class errors like a malformed request), it automatically
  retries with the next candidate, and remembers whichever one worked.
- Response parsing checks a couple of plausible alternate schemas in
  case Mistral changes their response shape.

**What "future-proof" does and doesn't mean here:** these mechanisms
handle the most common, realistic classes of change (renamed methods,
renamed response keys, renamed model IDs, minor parameter changes) without
a code update. They can't anticipate a truly complete API redesign — if
that happens, the MAINTENANCE notes in each module point at exactly what
to look at first. All of this is unit-tested by deliberately simulating
"the API changed" scenarios (missing methods, alternate response keys,
rejected model IDs, renamed endpoints) and confirming the fallback
actually engages and still produces a correct result — not just tested
against the currently-expected shape.

---

## Optional cloud OCR engines

Local OCR (Tesseract/EasyOCR) is the default: it's free, private (nothing
leaves the device/server), and works offline. For photos it still
struggles with — heavy blur, steep angles, poor lighting — the "OCR
engine" dropdown above the camera/upload tabs offers two cloud
alternatives, both larger vision-language models that can handle messier
input than a traditional OCR engine:

1. **Baidu Unlimited-OCR** — a free
   [Hugging Face Space](https://huggingface.co/spaces/baidu/Unlimited-OCR),
   no API key needed. Called via the `gradio_client` package.
2. **Mistral OCR** — Mistral's official commercial OCR API, using your
   own API key from [console.mistral.ai](https://console.mistral.ai/).

Both return plain text that flows through the exact same bilingual,
full-nutrient-panel parser as local OCR (`parse_nutrition_text()`) — the
engine is just a different way of getting text out of the photo.

**A design choice worth explaining:** the person who requested this
feature pointed at
[huggingface.co/spaces/merterbak/Mistral-OCR](https://huggingface.co/spaces/merterbak/Mistral-OCR)
as the "needs an API key" option. Reading that Space's source shows it's
just a thin demo UI that takes a user's API key and calls Mistral's own
official OCR endpoint. So this app calls that same official Mistral
endpoint (`https://api.mistral.ai/v1/ocr`) **directly**, rather than
routing through the community Space — your API key then goes straight to
Mistral and never transits a third party's server, and doesn't depend on
someone's demo Space staying online or unchanged.

**Please read before relying on either:**
- Neither integration could be exercised against the live services while
  building this — this development environment's network access doesn't
  extend to `huggingface.co`, `*.hf.space`, or `api.mistral.ai`. The
  request-building and response-parsing code (`modules/cloud_ocr.py`) was
  written directly from each service's own published source/docs and is
  covered by unit tests against realistic mocked responses, but you
  should test both against the real services once deployed, and treat
  the code as a solid starting point rather than a guarantee — either
  provider could change their interface without notice, since these are
  third-party services this app doesn't control.
- **Baidu Unlimited-OCR** runs on Hugging Face's shared "ZeroGPU" pool.
  As an anonymous (non-logged-in) caller, expect queueing delays and
  occasional unavailability at busy times — it's a free community demo,
  not a service with an uptime guarantee. Its API is also a custom
  streaming endpoint specific to that Space (not a standardized OCR API),
  so it's inherently more fragile to upstream changes than a stable,
  versioned commercial API.
- **Mistral OCR** is a paid commercial API (check current pricing at
  mistral.ai) — your key is billed by Mistral, not by this app.
- **Privacy:** either cloud option sends your photo to that provider's
  servers for processing. Local OCR is the only option where the photo
  never leaves your own device/server. The app shows a note about this
  whenever a cloud engine is selected.
- The Mistral API key field is a password-masked, session-only input —
  it's used for that one request and never written to disk, the
  database, or session state that persists across a page reload.

---

## OCR reliability on real camera photos

Clean, flat scans OCR easily; real phone photos are a different problem —
rotation metadata, uneven lighting, glare, blur, and curved/glossy
packaging surfaces all degrade recognition. Several concrete fixes
address this:

1. **EXIF orientation correction.** Phones store rotation as EXIF
   metadata rather than rotating the actual pixels. Without correcting
   for it, a portrait photo can OCR as sideways or upside-down text —
   which reliably produces zero readable fields. `modules/ocr_parser.py`
   applies `ImageOps.exif_transpose()` before any OCR pass.
2. **Multiple preprocessing variants, each tried with multiple page
   segmentation modes.** A single fixed recipe (e.g. "always binarize")
   helps some photos and hurts others, depending on lighting — and even
   for a good image, Tesseract's default layout-analysis mode sometimes
   badly under-performs "assume one uniform text block" (PSM 6) on a
   label surrounded by other packaging graphics (icons, logos, glare).
   Each photo is now processed **four** ways — contrast-enhanced +
   sharpened, Otsu-binarized, plain grayscale, and (when OpenCV is
   installed) denoised + 2x-upscaled + CLAHE-enhanced — and each variant
   is OCR'd with **two** PSM settings, with whichever of these ~8 attempts
   parses the most nutrition fields kept. CLAHE (Contrast Limited
   Adaptive Histogram Equalization) enhances local contrast rather than
   applying one global threshold, which matters a lot on curved, glossy
   surfaces (e.g. a cup-noodle container) where lighting varies sharply
   across the label — verified directly against real product photos
   during development, where this variant alone took a photo from zero
   readable fields to recovering most of the label.

**Japanese (日本語) label support**, including vocabulary confirmed
against real product label photos (not just idealized text):

- Both OCR backends run in combined English + Japanese mode
  (`lang="eng+jpn"` for tesseract, `["en", "ja"]` for EasyOCR), so mixed
  or either-language labels are read in one pass.
- Field-matching regexes cover multiple real-world wordings for the same
  field, since manufacturers genuinely vary: **calories** as either
  エネルギー or 熱量; **protein** as たんぱく質, 蛋白質, or たん白質 (三
  different real spellings); **sodium** as ナトリウム in either mg or
  grams (converting g→mg automatically), or derived from 食塩相当量 (salt
  equivalent) when sodium isn't stated directly. All patterns are
  **whitespace-tolerant between every character** — Tesseract's Japanese
  engine frequently inserts stray spaces as word-segmentation artifacts
  (e.g. "エネルギー" → "エネ ルギー"), which would silently break an
  exact-string match.
- Full-width digits and punctuation (e.g. "１８０ｋｃａｌ", common with
  Japanese input methods) are normalized to standard ASCII via Unicode
  NFKC normalization before parsing.
- Some Japanese labels report a carbohydrate *breakdown* (糖質 + 食物繊維)
  instead of a single 炭水化物 total; when no direct total is found, it's
  derived automatically as 糖質 + 食物繊維.
- Vitamin B1 (ビタミンB1) and Vitamin B2 (ビタミンB2) are tracked
  alongside Vitamin D, calcium, iron, and potassium in the extended
  nutrient panel — common on Japanese labels, confirmed present on real
  product photos.
- `tesseract_japanese_available()` checks whether the `jpn` trained-data
  file is actually installed and surfaces a clear warning in the app if
  it's missing, rather than silently reading Japanese labels as garbage.

**An honest limit worth stating plainly:** even with all of the above,
local Tesseract OCR has a real, inherent ceiling on genuinely difficult
photos — a curved cup-noodle label shot at an angle with small print and
glossy glare is a fundamentally hard case for any traditional OCR engine,
not just a preprocessing problem to tune away. In testing against real
photos of this kind, local OCR sometimes still mis-reads a digit or drops
a decimal point (e.g. "4.7g" read as "478"), even once the surrounding
text is otherwise recognizable. This is exactly the situation the
**optional cloud OCR engines** (below) exist for — large vision-language
models handle curved surfaces, small fonts, and glare meaningfully better
than traditional OCR, and are worth switching to for a photo local OCR
struggles with, rather than expecting endless local preprocessing tuning
to close that gap completely. Every value extracted — by any engine — is
also always shown as editable and clearly marked "✅ Auto-filled" so
anything mis-read is easy to spot and correct (see the highlighting
feature above).

---

## Scientific basis & limitations

This app deliberately uses **published, named formulas** (Mifflin-St
Jeor, Deurenberg, Food Insulin Index) rather than opaque black-box
predictions, so every number is traceable and explainable. That said:

- **A single meal does not measurably change your body-fat percentage.**
  Real adipose tissue changes occur over days-to-weeks of sustained
  caloric surplus/deficit, not within an hour of eating. The body-fat
  output here is a **projection/what-if indicator** — "if this food's
  caloric impact repeated every hour," not a literal forecast — and the
  app says so explicitly in the UI.
- **Insulin values are not measured blood levels.** True plasma insulin
  response depends on individual insulin sensitivity, meal composition
  interactions, glycemic index, time of day, and more — factors this
  algorithmic proxy does not capture.
- **OCR is imperfect.** Blurry photos, glare, curved packaging, and small
  print all degrade extraction accuracy. Always verify the auto-filled
  values against the physical label before relying on results.
- **Defaults are population averages**, not personalized measurements.
  For meaningful accuracy, enter your own age, height, weight, and
  (if known) body-fat percentage rather than relying on defaults.

**This tool is not a substitute for professional medical, dietary, or
diabetes-management advice.** If you have diabetes, insulin resistance,
an eating disorder, or any other metabolic condition, consult a
qualified healthcare provider before making decisions based on this app.

---

## Suggested future enhancements

A few ideas that would meaningfully improve usability beyond the current
scope:

- **Barcode scanning UI.** `modules/food_database_api.py` already
  includes `fetch_product_by_barcode()` for exact-match lookup — it just
  isn't wired into the UI yet. Adding a barcode input (or decoding one
  from the camera photo via a library like `pyzbar`) would make packaged-
  food lookup even faster and more precise than a name search.
- **Daily meal log & trends** — beyond one-off saved foods, log what was
  actually *eaten* with a timestamp, and chart cumulative insulin load
  and caloric balance over a day/week (the `foods` table could grow a
  companion `meal_log` table referencing it).
- **Per-user accounts** — the current database is single-user/local; a
  hosted DB (see the note above) plus simple auth would let each person
  have their own saved-food library.
- **Personalized insulin sensitivity input** — let users with a known
  HOMA-IR or clinical insulin-sensitivity value scale the estimate.
- **Multi-language OCR** — Japanese is supported now; add more
  `tesseract-ocr-<lang>` packages and matching field-name patterns for
  other non-English labels (Korean, Chinese, Spanish, etc.).
- **Offline PWA support** — cache the app shell so it's usable with a
  spotty connection while grocery shopping.
- **Export/share results** — let users export a scan as PDF/image to
  share with a dietitian.

---

## Testing

```bash
pip install pytest
pytest tests/ -v
```

223 unit and integration tests cover:
- Unit conversions (kg↔lb, ft/in↔cm)
- BMI, Deurenberg body-fat %, Mifflin-St Jeor BMR/TDEE (including
  known-value checks and edge cases: zero height, negative inputs,
  unknown activity levels)
- Profile default-filling logic (blank fields → baseline values)
- Insulin Load scoring and category boundaries
- TEF and gross-calorie derivation (label value vs. macro-derived
  fallback)
- Body-fat change projection for both surplus and deficit scenarios,
  plus the zero-weight guard
- OCR regex parsing against clean, noisy, partial, decimal-comma, and
  garbage/empty English text inputs, now including the **full extended
  nutrient panel** (saturated/trans fat, cholesterol, sodium, added
  sugars, vitamin D, calcium, iron, potassium) — including a bug caught
  and fixed during testing where the "Added Sugars" pattern could
  misread the *previous* line's "Total Sugars" value across a line break
- **Japanese label parsing**: clean labels, OCR-inserted-whitespace
  tolerance, the 糖質+食物繊維 carbohydrate-breakdown fallback (and that a
  direct 炭水化物 total correctly takes precedence over it), the
  食塩相当量→sodium(mg) conversion, full-width digit normalization, mixed
  English/Japanese labels, three real-world protein spellings (たんぱく質
  / 蛋白質 / たん白質), 熱量 as an alternate wording for calories, sodium
  stated directly in grams via ナトリウム (converting to mg, with the
  existing mg-based match correctly taking priority when both forms are
  present), and Vitamin B1/B2 parsing — plus **two full label
  reconstructions taken directly from real product photos**, each
  asserting every field actually present on that label is extracted
  correctly and nothing else is fabricated
- **Image preprocessing**: EXIF orientation correction (including a
  round-trip through a real JPEG with an orientation tag), huge-image
  downscaling, small-image upscaling, Otsu binarization producing
  pure black/white output, CLAHE-based enhancement (denoise + upscale +
  adaptive contrast, including graceful fallback when OpenCV isn't
  installed and when the underlying OpenCV calls themselves fail), RGBA
  input handling, and that multiple
  preprocessing variants are generated per photo
- Food database: save/retrieve/delete, required-name validation, search
  by name/category/brand/tags individually and combined (AND logic
  across filters, ANY-match within tags), result ordering and limits,
  autocomplete value lookups, the full extended nutrient panel and
  `source` field, and **schema migration** — a dedicated test builds a
  database with the original pre-extended-nutrient schema, inserts a
  row, runs `init_db()` against it, and confirms the old data survives
  with the new columns defaulted correctly
- **Open Food Facts integration**, mocking the official SDK's `API`
  object directly (no live network dependency or flakiness from a
  third-party service): preferring per-serving values over per-100g when
  available, the gram→mg conversion for sodium/cholesterol (including a
  precision bug caught and fixed where rounding small gram values
  *before* the ×1000 conversion silently lost precision), serving-size
  text parsing, category/brand cleanup, malformed/missing-field
  responses, and — the specific bug this round of testing caught and
  fixed — confirming that a genuine "no matches" response and an actual
  failure (network error, timeout, HTTP 429/503) are raised as distinct
  outcomes (`OpenFoodFactsError` vs. an empty list) rather than both
  silently collapsing into the same "no matches" result
- **Auto-fill highlighting**: which fields a scan/lookup actually found
  (`present_fields` from Open Food Facts, non-None fields from OCR
  parsing) correctly map to highlighted labels across both the core and
  extended nutrient tables, and manually editing a highlighted value
  correctly clears just that field's highlight without affecting others
- **Cloud OCR engines** (Baidu Unlimited-OCR, Mistral OCR), via mocked
  `gradio_client`/`requests` calls: correct request construction
  (API name, payload shape, auth header), successful-response parsing for
  both engines, missing-dependency and missing-API-key guards, and every
  failure mode (network error, timeout, 401/429/500 HTTP errors,
  malformed JSON, empty results) raising a clear `CloudOCRError` rather
  than crashing — plus a test confirming a cloud engine's output flows
  correctly into the same bilingual/full-nutrient parser used by local
  OCR
- **Future-proofing fallbacks**, each verified by deliberately simulating
  "the upstream API changed" rather than only testing the happy path:
  Open Food Facts' SDK-method-missing → raw-REST fallback, alternate
  response-shape keys (`hits`/`results` instead of `products`), nutrient
  key aliasing surviving a renamed field, and SDK-constructor-signature
  drift; Baidu's known-API-fails → runtime endpoint discovery (including
  that it correctly matches parameters by label on a completely renamed
  endpoint, skips non-image endpoints, and remembers which strategy
  worked across calls); and Mistral's model-ID fallback chain (including
  that an unrelated 400 error does *not* trigger the fallback, only a
  genuine "model not found" does)

All 223 tests pass, including a dedicated `test_app_integration.py` suite
using Streamlit's official `AppTest` framework to drive the real app
script end-to-end rather than only testing functions in isolation. That
file exists because of a real bug this level of testing caught: adding
Vitamin B1/B2 fields required updating six different places in `app.py`,
and one — the saved-food "Load" button's dict construction — was missed.
Every existing unit test still passed, since none of them exercised that
exact code path with real data. The integration suite now includes both
a live UI-driven reproduction of that exact bug and a static check that
scans `app.py` for every known dict-construction site and fails loudly,
by name, if a future nutrient field is ever added to some but not all of
them. The retry-with-backoff mechanism is specifically
tested with a function that fails transiently then succeeds (confirming
recovery), one that fails consistently (confirming it gives up after the
documented number of attempts rather than retrying forever), and one
that fails with a non-transient error (confirming it does *not* retry
and fails immediately) — plus an end-to-end test confirming a search
that hits one transient 503 still returns results normally. The
search-caching fix is verified with Streamlit's `AppTest`: driving the
actual search button, then a *different* widget elsewhere in the app, and
confirming the underlying Open Food Facts call count doesn't increase
from the unrelated interaction — while a genuinely new search term still
correctly triggers a fresh call. The app was also smoke-tested end-to-end: launched
headlessly from multiple working directories, confirmed a clean HTTP 200
boot with no runtime exceptions, and run through the full image → OCR →
parse → predict pipeline using a clear synthetic label (7/7 fields),
a synthetic label rotated 90° with a real EXIF orientation tag (verified
this fails completely — 0/7 fields — without the orientation fix, and
recovers to 7/7 with it), and a Japanese label (verified the initial
whitespace-tolerance bug — 3/7 fields — and its fix — 7/7 fields — with a
real OCR run against rendered Japanese text). The autocomplete fields
were specifically designed and tested against a real Streamlit edge case:
an empty-options `st.selectbox`/`st.multiselect` with
`accept_new_options=True` can disable free-text entry in some versions,
so those fields fall back to a plain text input until at least one value
exists to suggest — and each fallback mode uses a distinct widget key so
the field can never crash from a session-state type mismatch as the
option pool grows between reruns.

The full app was additionally exercised with Streamlit's official
`AppTest` framework (`streamlit.testing.v1`), which runs the real script
and simulates widget interaction without needing a browser: confirmed a
clean run with zero exceptions, drove the Open Food Facts search UI
end-to-end, and verified the complete "type a name → click Save → row
actually lands in SQLite with the correct fields" flow.

---

## License / attribution

Formulas used are drawn from publicly available nutrition-science
literature (Mifflin-St Jeor 1990; Deurenberg et al. 1991; Food Insulin
Index research, Bao et al. 2009 and related work). No proprietary or
licensed clinical algorithms are used.
