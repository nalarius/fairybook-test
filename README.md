# Fairybook

Fairybook is a Streamlit application that helps educators and parents craft short Korean children's stories and AI-generated illustrations powered by Google Gemini. The app guides the user through a four-step flow, picks a matching illustration style, and can export the final story as HTML for easy sharing.

## Core Features
- Guided story creation: choose an age band, provide a one-line idea, and pick from randomized story archetypes.
- Gemini-backed storytelling: prompts the Gemini text model for multi-paragraph narratives tailored to the selected age and topic.
- Illustration generation: derives an English art prompt from the story plus an illustration style catalog, then calls the Gemini image model.
- One-click exports: download the story text or bundle text and artwork into timestamped HTML files stored under `html_exports/`.
- Saved story browser: revisit previous exports inside the app without leaving Streamlit.

## Getting Started

### Prerequisites
- Python 3.11 or newer
- Google Gemini API access (text + image endpoints)

### Installation
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\\Scripts\\activate
pip install -r requirements.txt
```

### Configure Secrets
1. Create a `.env` file in the project root (do not commit real keys).
2. Add the required variables:
   ```ini
   GEMINI_API_KEY="your-api-key"
   # Optional: override the default image model
   GEMINI_IMAGE_MODEL="models/gemini-2.5-flash-image-preview"
   ```
3. Restart the Streamlit app after changing `.env` so the new values load.

> Tip: rotate keys immediately if they ever appear in command output, logs, or commit history.

## Run the App
```bash
streamlit run app.py
# or headless mode (useful on remote servers)
streamlit run app.py --server.headless true
```

The UI opens to a task selector. Choose **✏️ 동화 만들기** to start the story flow:
1. Pick an age group and describe the idea or theme.
2. Choose one of eight randomized story types to generate an on-theme title.
3. Pick one of four narrative cards drawn from `story.json` to steer the plot.
4. Wait while Gemini writes the story and illustration; review the results and export as text or HTML.
5. Use **저장된 동화 보기** to browse previously exported HTML files located in `html_exports/`.

## Repository Tour
- `app.py` – Streamlit UI and session-state management for the multi-step workflow.
- `gemini_client.py` – Gemini integration, including story prompt composition, illustration prompt generation, and image model fallbacks.
- `storytype.json`, `story.json`, `ending.json` – Data assets that describe story archetypes, reusable beats, and ending templates.
- `illust_styles.json` – Illustration style catalog used to randomize art direction.
- `illust/` – Lightweight 512×512 thumbnail PNGs showcased in the UI.
- `html_exports/` – Output directory for generated HTML bundles (created on first export).
- `docs/TECHNICAL_BRIEF.md` – Deep dive into app architecture and recent enhancements.

## Development Notes
- Follow PEP 8, keep Streamlit widget keys stable, and prefer helper functions for repeated logic.
- When adding dependencies, pin them in `requirements.txt` and capture the change with `pip freeze` before committing.
- Tests are ad hoc today; add `pytest` suites under `test_*.py` and mock `google.generativeai` to avoid hitting external APIs.
- Manual verification: launch the app, walk through all four creation steps, exercise illustration downloads, and reload saved HTML exports to confirm rendering.

## Troubleshooting
- **Missing story types or styles**: ensure `storytype.json` and `illust_styles.json` remain in the project root and are valid UTF-8 JSON.
- **Gemini errors**: double-check the API key, confirm the configured model is available to your account, and review console logs for rate limit or safety blocks.
- **Headless sessions**: use `streamlit run app.py --server.headless true` and access via the CLI-provided URL or enable Streamlit Cloud deployment.

## Further Reading
- Technical overview: `docs/TECHNICAL_BRIEF.md`
- Repository contribution guidelines: `AGENTS.md`
- Illustration style reference: `illust_styles.json`
