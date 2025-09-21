# Fairybook

Fairybook is a Streamlit application that helps educators and parents craft short Korean children's stories and AI-generated illustrations powered by Google Gemini. The app now guides users through a six-step flow that locks in a single illustration style after the title stage, previews the cover art, and exports the finished story as a lightweight HTML bundle.

## Core Features
- Guided story creation: choose an age band, provide a one-line idea, and pick from randomized story archetypes.
- Gemini-backed storytelling: prompts the Gemini text model for multi-paragraph narratives tailored to the selected age and topic.
- Story pre-production: auto-generates a synopsis, detailed protagonist profile, and character concept art before the title phase.
- Consistent illustration style: the initial generation locks a single art direction and reuses it for character art, stage visuals, and the cover.
- HTML exports: bundle the title, cover, stage illustrations, and prose into timestamped HTML files stored under `html_exports/`.
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
2. Choose one of eight randomized story types. Clicking **✨ 제목 만들기** runs a pre-production pipeline that drafts a synopsis, defines the protagonist, locks an illustration style, renders character concept art, and then produces the title and cover prompt.
3. Review the generated title, synopsis, protagonist brief, character art, and cover illustration, then continue when satisfied.
4. Pick one of four narrative cards drawn from `story.json` (the final stage automatically swaps in `ending.json` cards so the conclusion matches the desired mood).
5. Let Gemini write the current stage with continuity context and create its illustration (optionally guided by the character art as an image reference); repeat until all five stages are complete.
6. Open **전체 이야기를 모아봤어요** to review the full sequence. The app auto-saves an HTML bundle under `html_exports/` and surfaces the latest file path. Use **📂 저장본 보기** any time to browse previously exported stories.

## Repository Tour
- `app.py` – Streamlit UI and session-state management for the multi-step workflow, including the automated synopsis → protagonist → character art → title seeding loop.
- `gemini_client.py` – Gemini integration, including story prompt composition, synopsis/protagonist prompt builders, illustration prompt generation, and image model fallbacks.
- `storytype.json`, `story.json`, `ending.json` – Data assets that describe story archetypes, reusable beats, and ending templates.
- `illust_styles.json` – Illustration style catalog used to randomize art direction.
- `illust/` – Lightweight 512×512 thumbnail PNGs showcased in the UI.
- `html_exports/` – Output directory for generated HTML bundles (created on first export).
- `docs/TECHNICAL_BRIEF.md` – Deep dive into app architecture and recent enhancements.

## Development Notes
- Follow PEP 8, keep Streamlit widget keys stable, and prefer helper functions for repeated logic.
- When adding dependencies, pin them in `requirements.txt` and capture the change with `pip freeze` before committing.
- Tests are ad hoc today; add `pytest` suites under `test_*.py` and mock `google.generativeai` to avoid hitting external APIs.
- Manual verification: launch the app, walk through all six creation steps (including the cover preview), ensure each stage inherits the locked illustration style, and reload saved HTML exports to confirm rendering.

## Troubleshooting
- **Missing story types or styles**: ensure `storytype.json` and `illust_styles.json` remain in the project root and are valid UTF-8 JSON.
- **Gemini errors**: double-check the API key, confirm the configured model is available to your account, and review console logs for rate limit or safety blocks.
- **Headless sessions**: use `streamlit run app.py --server.headless true` and access via the CLI-provided URL or enable Streamlit Cloud deployment.

## Further Reading
- Technical overview: `docs/TECHNICAL_BRIEF.md`
- Repository contribution guidelines: `AGENTS.md`
- Illustration style reference: `illust_styles.json`
