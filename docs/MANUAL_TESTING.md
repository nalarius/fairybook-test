# Manual Testing Guide

Use this checklist when validating changes locally. Capture notes or screenshots for regressions and attach them to your PR.

## Setup
- Activate the virtual environment and install dependencies (`pip install -r requirements.txt`).
- Populate `.env` with a valid `GEMINI_API_KEY`; restart Streamlit after edits.
- (Optional) Clear `html_exports/` to simulate a first-run experience.

## Story Creation Flow
1. Launch `streamlit run app.py` (headless flag permitted).
2. On Step 0 select **✏️ 동화 만들기**.
3. Step 1: Provide an idea, try each age band, and confirm the form advances.
4. Step 2: Verify eight story-type cards load with the expected thumbnails and that clicking **제목 만들기** produces a title.
5. Step 3: Ensure four narrative cards appear, switch between them, and trigger **이야기 만들기**.
6. Step 4: Confirm the loading spinner appears, the story and illustration render, and downloads work.
7. Generate at least two stories covering 다른 이야기 톤 (예: 하나는 밝고 희망적인 방향, 다른 하나는 서늘하거나 비극적인 방향)으로 각각 다른 type/card 조합을 사용하고, 두 결과를 비교해 톤이 다양하게 반영됐는지 확인한다. 각 결과의 일반 텍스트 내보내기를 다운로드해 정상적으로 열리는지도 점검한다.

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
- 검증 과정에서 생성한 여러 이야기의 분위기가 재실행 후에도 다양하게 유지되는지 살펴본다.
- Disconnect the network temporarily; expect clear error messages when Gemini calls fail.
- Validate that deleting or corrupting `illust_styles.json` produces the warning banner instead of crashing.

Document outcomes, anomalies, and follow-up actions in the PR description.
