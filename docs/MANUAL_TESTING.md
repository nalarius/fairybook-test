# Manual Testing Guide

Use this checklist when validating changes locally. Capture notes or screenshots for regressions and attach them to your PR.

## Setup
- Activate the virtual environment and install dependencies (`pip install -r requirements.txt`).
- Populate `.env` with a valid `GEMINI_API_KEY`; restart Streamlit after edits.
- (Optional) Clear `html_exports/` to simulate a first-run experience.

## Story Creation Flow
1. Launch `streamlit run app.py` (headless flag permitted).
2. On Step 0 select **✏️ 동화 만들기**.
3. Provide an idea, choose each available age band, and advance to Step 2.
4. Verify eight archetype cards load with the expected thumbnails.
5. Generate at least two stories:
   - Confirm story text appears under the chosen card heading.
   - Download the plain-text export and open it locally.

## Illustration Checks
- Ensure an illustration displays for at least one story (retry if quota or safety blocks trigger).
- If the image fails, expand **이미지 프롬프트 보기** and confirm the prompt text exists for debugging.
- Download the HTML export and confirm the embedded image renders in a browser.

## Saved Story Review
1. Return to Step 0 and choose **📂 저장본 보기** (only available after an export exists).
2. Select the latest HTML file and verify the preview and download actions work.
3. Use navigation buttons to return to earlier steps and confirm session state resets without errors.

## Regression Smoke Tests
- Reload the page or rerun Streamlit to confirm cached data persists and the UI rehydrates correctly.
- Disconnect the network temporarily; expect clear error messages when Gemini calls fail.
- Validate that deleting or corrupting `illust_styles.json` produces the warning banner instead of crashing.

Document outcomes, anomalies, and follow-up actions in the PR description.
