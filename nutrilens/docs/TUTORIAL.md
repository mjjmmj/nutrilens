# NutriLens — Complete Tutorial

A step-by-step walkthrough of every feature in NutriLens, illustrated with
real screenshots of the app in action. If you just want to get the app
running, see the main [README.md](../README.md) for installation and
deployment instructions — this document is about *using* it once it's
running.

> All screenshots below were captured from a live, running instance of
> the app — the nutrition values you'll see (180 kcal, Insulin Load Score
> 30.3, etc.) came from actually uploading a sample label image through
> the real OCR pipeline, not mocked up.

---

## Table of contents

1. [What NutriLens does](#1-what-nutrilens-does)
2. [The app at a glance](#2-the-app-at-a-glance)
3. [Setting up your profile](#3-setting-up-your-profile)
4. [Three ways to get a food's nutrition data](#4-three-ways-to-get-a-foods-nutrition-data)
   - [4a. Scan a label photo](#4a-scan-a-label-photo)
   - [4b. Search your saved foods](#4b-search-your-saved-foods)
   - [4c. Search a public food database](#4c-search-a-public-food-database)
5. [Understanding the auto-fill highlighting](#5-understanding-the-auto-fill-highlighting)
6. [Reviewing the full nutrient panel](#6-reviewing-the-full-nutrient-panel)
7. [Saving a food for next time](#7-saving-a-food-for-next-time)
8. [Reading your results](#8-reading-your-results)
9. [Choosing an OCR engine](#9-choosing-an-ocr-engine)
10. [Tips, limitations, and troubleshooting](#10-tips-limitations-and-troubleshooting)

---

## 1. What NutriLens does

NutriLens turns a nutrition facts label — photographed, searched by name,
or pulled from your own history — into two things:

- An **Insulin Load** estimate: how sharply this food is likely to spike
  insulin, based on its carb/fiber/protein/fat composition.
- A **body-fat / caloric impact** projection: what this food's caloric
  surplus or deficit means relative to your metabolic baseline.

Both are algorithmic educational estimates based on published
nutrition-science formulas — not a medical device, and not a substitute
for lab testing or professional advice. The app says this clearly in its
own disclaimer (see [§2](#2-the-app-at-a-glance)), and it's worth reading
before relying on the numbers.

---

## 2. The app at a glance

When you first open NutriLens, you'll see the title, a collapsed
disclaimer, and three ways to get nutrition data into the app (search
your own history, search a public database, or scan a photo) above the
main scan-and-review workflow.

![App overview](screenshots/01_app_overview.png)

Click **"⚠️ Important disclaimer — please read"** to expand it. It's
short, and explains exactly what the two prediction numbers do and don't
mean:

![Disclaimer expanded](screenshots/02_disclaimer_expanded.png)

---

## 3. Setting up your profile

The sidebar on the left collects the biological info the predictions are
based on: gender, age, height, weight, and activity level. **Every field
is optional** — leave any of them blank and the app fills the gap with a
standard baseline estimate (and tells you which fields it defaulted, so
you always know what's an estimate versus what you entered).

![Sidebar profile](screenshots/03_sidebar_profile.png)

Click **"📊 Your calculated baseline"** to see the numbers derived from
your profile — BMI, estimated body fat %, BMR, and TDEE (total daily
energy expenditure) — before any food is even scanned:

![Sidebar baseline](screenshots/04_sidebar_baseline.png)

**Tip:** the more accurate your own age/height/weight, the more accurate
the predictions. The defaults are population averages, not personalized
measurements.

---

## 4. Three ways to get a food's nutrition data

### 4a. Scan a label photo

This is the core feature: point your camera at a nutrition label (or
upload a photo from your gallery), and NutriLens reads it for you.

First, pick an **OCR engine** — local (free, private, works offline) is
the default; two optional cloud engines are available for photos local
OCR struggles with (see [§9](#9-choosing-an-ocr-engine)). Then use the
**Take Photo** or **Upload from Gallery** tab:

![OCR engine and capture tabs](screenshots/07_ocr_engine_and_capture.png)

Once you provide a photo, OCR runs automatically and shows you exactly
what it found:

![OCR scan result](screenshots/08_ocr_scan_result.png)

In this example, the app read **"Extracted 7/7 core fields"** — every
macro on the label was found and filled in automatically. If a photo is
blurry or at a steep angle, you might see fewer fields extracted; that's
completely fine, since every value is editable in the next step
regardless of where it came from.

### 4b. Search your saved foods

If you've scanned or saved a food before, you don't need to rescan it.
Expand **"🔎 Search your saved foods"** and filter by name, category,
brand, or tags — any combination:

![Search saved foods](screenshots/05_search_saved_foods.png)

Pick a match from the results dropdown and click **"⬇️ Load into current
scan"** to pull its saved nutrition data straight in, no camera needed.

### 4c. Search a public food database

For common packaged foods, you may not need a photo at all. Expand
**"🌐 Search a public food database"** to look up a product by name from
[Open Food Facts](https://world.openfoodfacts.org) — a free,
community-maintained database with no API key required:

![Public database search](screenshots/06_public_database_search.png)

Type a product name and click **Search**. Since this data is
crowd-sourced, treat a result the same way you'd treat an OCR scan: a
solid starting point to review, not a guaranteed-accurate source.

---

## 5. Understanding the auto-fill highlighting

However the data got in — photo, cloud OCR, or public database — every
value lands in an editable table under **"2. Confirm or correct the
nutrition facts."** A **Source** column tells you, at a glance, which
values were filled in automatically versus which are still at their
default:

![Nutrition table with highlighting](screenshots/09_nutrition_table_highlighted.png)

- **✅ Auto-filled** — this value came from the last scan or lookup.
  Worth a quick glance to confirm it looks right, especially for a
  blurry photo.
- **✏️ Manual** — this is either a default placeholder or something you
  typed in yourself.

If you edit an auto-filled value, its tag switches to "✏️ Manual"
immediately — the highlighting always reflects what the *last* scan
actually found, not just whatever happens to be sitting in the field.
Every cell in this table is directly editable, so correcting an OCR
misread is as simple as clicking the cell and typing the right number:

![Editable table close-up](screenshots/15_editable_table_closeup.png)

Set how many servings you actually plan to eat just below the table —
every prediction scales automatically from there.

---

## 6. Reviewing the full nutrient panel

NutriLens captures more than the 7 headline macros. Expand
**"➕ Additional nutrients"** to see (and edit) saturated/trans fat,
cholesterol, sodium, added sugars, vitamins D/B1/B2, calcium, iron, and
potassium — all auto-filled and highlighted the same way as the core
table when a scan/lookup finds them:

![Additional nutrients](screenshots/10_additional_nutrients.png)

These extra fields aren't used in the insulin/body-fat predictions
(which only need the core macros), but they're captured, saved, and
searchable like everything else — useful if you're tracking sodium or
micronutrients separately.

For a single consolidated view of everything at once, expand
**"📋 Full nutrition panel"** further down the page:

![Full nutrition panel](screenshots/12_full_nutrition_panel.png)

---

## 7. Saving a food for next time

Found something worth remembering? Give it a name (required) and
optionally a category, brand, and tags, then click **"💾 Save this
food."** Every field — including the full nutrient panel — is stored, so
you can search and reload it later (see [§4b](#4b-search-your-saved-foods))
without rescanning:

![Save food form](screenshots/11_save_food_form.png)

All four fields (name, category, brand, tags) offer autocomplete: start
typing and matching values from your existing saved foods narrow down
live, or just type something new if nothing matches.

---

## 8. Reading your results

Scroll down to **"4. Predicted acute impact"** to see both predictions
calculated from whatever's currently in the tables above:

![Predictions](screenshots/13_predictions.png)

**Insulin Load Score & Spike Category** — a Low/Medium/High indicator of
how sharply this food is likely to raise insulin, plus an illustrative
µIU/mL estimate scaled against a standard glucose-tolerance-test
reference. In the example above: a score of 30.3, categorized "Medium,"
roughly 18.2 µIU/mL.

**Caloric & body-fat projection** — net metabolizable energy (after
accounting for the thermic effect of digesting the food), compared
against your hourly baseline burn rate, expressed as a fat-mass
equivalent:

![Predictions detail](screenshots/14_predictions_detail.png)

Read this as a **relative, directional indicator** — a way to compare
foods against each other — not a literal claim that your body fat will
measurably shift from one meal. The app is explicit about this in the
disclaimer and again right next to this result.

---

## 9. Choosing an OCR engine

Back at the capture step, the **OCR engine** dropdown offers three
options:

| Engine | Cost | Privacy | Best for |
|---|---|---|---|
| **Local (Tesseract/EasyOCR)** | Free | Never leaves your device/server | Default; clear, well-lit photos |
| **Baidu Unlimited-OCR** | Free | Sent to a community Hugging Face Space | Blurry/angled photos local OCR struggles with |
| **Mistral OCR** | Paid (your own API key) | Sent directly to Mistral's official API | Difficult photos where you want a commercial-grade result |

Switching to a cloud engine shows a one-line note about where your photo
is being sent — worth reading once so you know what each option means
for your data. Local OCR is genuinely capable on clean, flat, well-lit
labels; for a curved, glossy, or heavily-angled photo (a soup cup, a
glossy wrapper), a cloud engine will often do noticeably better.

---

## 10. Tips, limitations, and troubleshooting

- **Both English and Japanese (日本語) labels are supported** in local
  OCR, including several real-world label-wording variants (e.g. 熱量 vs
  エネルギー for calories, multiple spellings of "protein," sodium given
  as either milligrams or grams).
- **If OCR finds nothing or gets something wrong**, there's no need to
  retake the photo from scratch — every field is editable, and switching
  OCR engines on the same photo (re-upload it) often helps.
- **The insulin and body-fat numbers are educational estimates**, not
  clinical measurements. If you have diabetes, insulin resistance, or
  another metabolic condition, talk to a healthcare provider before
  making decisions based on this app.
- **Saved foods live in a local database** (SQLite) that persists across
  sessions when run locally, but resets on restart if deployed to
  Streamlit Community Cloud's free tier (its filesystem is ephemeral).
- **Open Food Facts results vary in quality** since it's crowd-sourced —
  always glance over a loaded result the same way you would an OCR scan.

For installation, deployment, and technical/architecture details, see
the main [README.md](../README.md).
