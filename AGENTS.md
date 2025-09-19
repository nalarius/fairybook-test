# Repository Guidelines

## Project Structure & Module Organization
The Streamlit interface lives in `app.py`, orchestrating stateful UI steps and calling into `gemini_client.py`. Model prompts, story metadata, and ending templates are stored in the JSON files at the repo root (`storytype.json`, `story.json`, `ending.json`, `illust_styles.json`). Illustration thumbnails sit under `illust/`; keep additions lightweight (PNG, 512×512) to preserve load time. Configuration is loaded lazily, so introduce new modules alongside existing ones and import them from `app.py` or `gemini_client.py` to ensure Streamlit reruns cleanly.

## Build, Test, and Development Commands
Use Python 3.11+.
```
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
`streamlit run app.py --server.headless true` helps when testing without a browser. Pin new dependencies in `requirements.txt` and verify `pip freeze` diffs before committing.

## Coding Style & Naming Conventions
Follow PEP 8: 4-space indentation, snake_case for functions and variables, UpperCamelCase only for classes. Keep Streamlit keys stable (see `ensure_state`) and centralize constants in caps (`JSON_PATH`, `ILLUST_DIR`). Prefer f-strings, type hints, and short helper functions. Preserve existing Korean copy and emoji for UX consistency.

## Testing Guidelines
There is no automated suite yet; favor `pytest` with files named `test_*.py`. Mock `google.generativeai.GenerativeModel` when validating `generate_story_with_gemini` to avoid quota usage. Record manual test notes for UI flows: launch Streamlit, run through both steps, and confirm downloads. Capture regressions with screenshot diffs when adjusting layout.

## Commit & Pull Request Guidelines
Use concise, imperative commit subjects (e.g., `Refine story selection state`). Group logical changes; avoid bundling asset updates with code unless required. PRs should describe motivation, implementation notes, local verification steps, and attach UI screenshots or clips for visible changes. Link related issues and call out follow-up work so reviewers can queue next tasks.

## Secrets & Configuration Tips
Store `GEMINI_API_KEY` in `.env` (never commit it). Document any new environment variables in this file and add safe defaults. Large media belongs in remote storage; keep `illust/` limited to optimized PNGs so repo clones stay small. Rotate API keys immediately if they leak in logs or drafts.
