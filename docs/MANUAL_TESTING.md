# Manual Testing Guide

Use this checklist when validating changes locally. Capture notes or screenshots for regressions and attach them to your PR.

## Setup
- Activate the virtual environment and install dependencies (`pip install -r requirements.txt`).
- Install the dev dependency (`pip install pytest`) and verify the automated suite passes (`python -m pytest`).
- Populate `.env` with a valid `GEMINI_API_KEY`; restart Streamlit after edits.
- (Optional) Clear `html_exports/` to simulate a first-run experience.

## Story Creation Flow
1. Launch `streamlit run app.py` (headless flag permitted).
2. On Step 0 select **✏️ 동화 만들기**.
3. Step 1: Provide an idea, try each age band, and confirm the form advances.
4. Step 2: Verify eight story-type cards load with the expected thumbnails. Click **✨ 제목 만들기** and confirm the full pre-production pipeline completes (synopsis text, protagonist profile, locked illustration style, character concept art, generated title, and cover prompt all populate without errors).
5. Step 3: Review the title, synopsis, protagonist write-up, character art, and cover illustration. Confirm the selected style name persists and that navigation buttons let you regenerate or continue without losing the locked style.
6. Step 4: Ensure four narrative cards appear, switch between them, and trigger **이 단계 이야기 만들기** (when you reach 결말, 확인해 `ending.json` 카드 세트가 노출되는지 반드시 점검).
7. Step 5: Check that the loading spinner appears, the story paragraphs render alongside the stage illustration, and the art reuses the locked style (character portrait should influence poses when reference images are enabled).
8. Step 6: Confirm the recap screen auto-saves an HTML bundle, surfaces the latest file path, and allows returning to remaining stages if any are incomplete.
9. Generate at least two stories covering 다른 이야기 톤 (예: 하나는 밝고 희망적인 방향, 다른 하나는 서늘하거나 비극적인 방향)으로 각각 다른 type/card 조합을 사용하고, 두 결과를 비교해 톤이 다양하게 반영됐는지 확인한다.

## Illustration Checks
- Ensure the cover illustration renders, the character concept art appears, and later stages reuse the same style descriptor.
- Validate that the stage prompts respect the protagonist details (e.g., outfit, mood) and that reference-image reuse keeps characters consistent.
- If a stage image fails, note the surfaced error and confirm you can retry without losing prior stages or the locked style.
- Save an HTML export from the recap step and confirm every embedded image renders in a browser.

## Saved Story Review
1. Return to Step 0 and choose **📂 저장본 보기** (available after an export exists).
2. Select the latest HTML file (the filename should match Step 6's toast) and verify the preview works.
3. Use navigation buttons to return to earlier steps and confirm session state resets without errors.

## Regression Smoke Tests
- Reload the page or rerun Streamlit to confirm cached data persists and the UI rehydrates correctly.
- 검증 과정에서 생성한 여러 이야기의 분위기가 재실행 후에도 다양하게 유지되는지 살펴본다.
- Disconnect the network temporarily; expect clear error messages when Gemini calls fail (pre-production stages should surface per-step failures gracefully).
- Validate that deleting or corrupting `illust_styles.json` produces the warning banner instead of crashing, and that the auto-export signature prevents duplicate HTML writes when replaying Step 6.

Document outcomes, anomalies, and follow-up actions in the PR description.
