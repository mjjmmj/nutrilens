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

---

## Features

- 📷 **Camera or gallery upload** — `st.camera_input` opens the phone
  camera directly; a file uploader is provided as a fallback for gallery
  photos or desktop use.
- 🔍 **OCR label parsing** — extracts serving size, calories, carbs, fiber,
  sugars, protein, and fat via `pytesseract`, with tolerant regex parsing
  that handles common OCR noise (missing spaces, punctuation, decimal
  commas, varying label wording).
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
│   ├── ocr_parser.py          # OCR text extraction + regex field parsing
│   └── user_profile.py        # Sidebar UI for collecting profile inputs
├── tests/
│   ├── test_calculations.py   # 33 unit tests for the calculation engine
│   └── test_ocr_parser.py     # 8 unit tests for label text parsing
├── .streamlit/
│   └── config.toml            # Theme + server configuration
├── requirements.txt           # Python dependencies
├── packages.txt               # System (apt) dependency: tesseract-ocr binary
└── README.md
```

The calculation engine (`modules/calculations.py`) has **zero Streamlit
dependency**, so it can be unit tested, reused in a CLI, or swapped into a
different frontend without modification.

---

## Running locally

```bash
# 1. Clone / copy this project, then create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install the Tesseract OCR binary (pytesseract is just a wrapper —
#    it needs the actual `tesseract` executable on your system)
#    macOS:    brew install tesseract
#    Ubuntu:   sudo apt-get install tesseract-ocr
#    Windows:  https://github.com/UB-Mannheim/tesseract/wiki

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
     provides the `tesseract-ocr` binary that `pytesseract` calls out to.
     **Don't skip `packages.txt`** — without it, `pytesseract` will raise
     `TesseractNotFoundError` in the cloud environment (the app catches
     this gracefully and falls back to manual entry, but OCR won't work).

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

- **Meal history & trends** — log scanned foods over a day/week and chart
  cumulative insulin load and caloric balance (`st.session_state` +
  a simple CSV/SQLite log), rather than only showing single-item results.
- **Barcode scanning fallback** — for packaged foods, look up
  Open Food Facts by barcode as a higher-accuracy alternative to OCR.
- **Personalized insulin sensitivity input** — let users with a known
  HOMA-IR or clinical insulin-sensitivity value scale the estimate.
- **Multi-language OCR** — add `easyocr` or `tesseract` language packs for
  non-English labels.
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

41 unit tests cover:
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
  garbage/empty text inputs

All 41 tests pass. The app was also smoke-tested end-to-end: launched
headlessly, confirmed a clean HTTP 200 boot with no runtime exceptions,
and run through the full image → OCR → parse → predict pipeline using
both a clear synthetic label (7/7 fields extracted correctly) and a noisy
one (partial extraction, correctly triggering the manual-correction UI).

---

## License / attribution

Formulas used are drawn from publicly available nutrition-science
literature (Mifflin-St Jeor 1990; Deurenberg et al. 1991; Food Insulin
Index research, Bao et al. 2009 and related work). No proprietary or
licensed clinical algorithms are used.
