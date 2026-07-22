"""
One-off script to capture real screenshots of the running NutriLens app
for the tutorial documentation. Not part of the app itself -- run
manually against a live `streamlit run app.py` instance with a
pre-seeded database (see docs/README for the seeding snippet used).

Requires Playwright (a dev-only dependency, not needed to run the app
itself): `pip install playwright && playwright install chromium`
"""

import time
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8703"
OUT_DIR = "/home/claude/nutrilens/docs/screenshots"
SAMPLE_LABEL_PATH = "/tmp/sample_label_for_upload.png"


def shot(page, name, full_page=False):
    path = f"{OUT_DIR}/{name}.png"
    page.screenshot(path=path, full_page=full_page)
    print(f"  saved {name}.png")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 1000}, device_scale_factor=2)
        page.goto(BASE_URL, timeout=30000)
        page.wait_for_selector("h1", timeout=20000)
        time.sleep(2)

        # 1. Top of app: title + disclaimer (collapsed)
        print("1. App overview")
        shot(page, "01_app_overview")

        # 2. Expand the disclaimer
        print("2. Disclaimer expanded")
        page.get_by_text("⚠️ Important disclaimer").click(force=True)
        time.sleep(1)
        shot(page, "02_disclaimer_expanded")
        page.get_by_text("⚠️ Important disclaimer").click(force=True)  # collapse again
        time.sleep(0.5)

        # 3. Sidebar profile
        print("3. Sidebar profile")
        shot(page, "03_sidebar_profile")

        # 4. Sidebar calculated baseline expanded
        print("4. Sidebar calculated baseline")
        page.get_by_text("📊 Your calculated baseline").click(force=True)
        time.sleep(1)
        shot(page, "04_sidebar_baseline")
        page.get_by_text("📊 Your calculated baseline").click(force=True)
        time.sleep(0.5)

        # Collapse the sidebar so every subsequent screenshot shows clean,
        # full-width main content instead of sidebar bleed-through.
        print("(collapsing sidebar for remaining screenshots)")
        collapse_btn = page.locator("[data-testid='stSidebarCollapseButton'] button")
        if collapse_btn.count() == 0:
            collapse_btn = page.locator("button[kind='header']")
        if collapse_btn.count() > 0:
            collapse_btn.first.click(force=True)
            time.sleep(1)

        # 5. Search saved foods expanded
        print("5. Search saved foods")
        page.get_by_text("🔎 Search your saved foods").click(force=True)
        time.sleep(1.5)
        shot(page, "05_search_saved_foods", full_page=False)
        page.get_by_text("🔎 Search your saved foods").click(force=True)
        time.sleep(0.5)

        # 6. Public food database search section
        print("6. Public database search section")
        off_header = page.get_by_text("🌐 Search a public food database")
        off_header.click(force=True)
        time.sleep(1)
        shot(page, "06_public_database_search")
        off_header.click(force=True)
        time.sleep(0.5)

        # 7. OCR engine selector + camera/upload tabs (before any scan)
        print("7. OCR engine + capture section")
        page.get_by_text("1. Capture or upload the nutrition label").scroll_into_view_if_needed()
        time.sleep(1)
        shot(page, "07_ocr_engine_and_capture")

        # 8. Real OCR scan: upload a real label image and let actual OCR run
        print("8. Uploading a real label photo through the actual OCR pipeline")
        page.get_by_role("tab", name="Upload from Gallery").click(force=True)
        time.sleep(1)
        page.locator("input[type='file']").first.set_input_files(SAMPLE_LABEL_PATH)
        page.wait_for_selector("text=Extracted", timeout=30000)
        time.sleep(1)
        page.get_by_text("Captured label").scroll_into_view_if_needed()
        time.sleep(0.5)
        shot(page, "08_ocr_scan_result")

        # 9. Nutrition table with genuine auto-filled highlighting
        print("9. Nutrition table with real auto-fill highlighting")
        page.get_by_text("2. Confirm or correct the nutrition facts").scroll_into_view_if_needed()
        time.sleep(1)
        shot(page, "09_nutrition_table_highlighted")

        # 10. Additional nutrients expander
        print("10. Additional nutrients")
        page.get_by_text("➕ Additional nutrients").click(force=True)
        time.sleep(1)
        page.get_by_text("➕ Additional nutrients").scroll_into_view_if_needed()
        time.sleep(0.5)
        shot(page, "10_additional_nutrients")

        # 11. Save food form
        print("11. Save food form")
        page.get_by_text("3. Save this food for next time").scroll_into_view_if_needed()
        time.sleep(1)
        shot(page, "11_save_food_form")

        # 12. Full nutrition panel
        print("12. Full nutrition panel")
        panel = page.get_by_text("📋 Full nutrition panel")
        if panel.count() > 0:
            panel.first.click(force=True)
            time.sleep(1)
            panel.first.scroll_into_view_if_needed()
            time.sleep(0.5)
            shot(page, "12_full_nutrition_panel")

        # 13. Predictions section (insulin + body fat)
        print("13. Predictions")
        pred_header = page.get_by_text("4. Predicted acute impact")
        if pred_header.count() > 0:
            pred_header.first.scroll_into_view_if_needed()
            time.sleep(1)
            shot(page, "13_predictions")

        # 14. Full predictions detail
        print("14. Predictions full detail")
        insulin_header = page.get_by_text("Insulin Load Score")
        if insulin_header.count() > 0:
            insulin_header.first.scroll_into_view_if_needed()
            time.sleep(1)
            shot(page, "14_predictions_detail")

        # 15. Close-up of the editable table showing the Source column
        print("15. Editable table close-up")
        page.get_by_text("2. Confirm or correct the nutrition facts").scroll_into_view_if_needed()
        time.sleep(1)
        shot(page, "15_editable_table_closeup")

        browser.close()
        print("\nDone.")


if __name__ == "__main__":
    main()
