# Fairybook Technical Brief

## Overview
Fairybook is a two-step Streamlit application that generates short children's stories and AI illustrations using Google Gemini. The UI in `app.py` manages session state for the multi-step flow, while `gemini_client.py` encapsulates all Gemini API interactions. Supporting metadata such as story types, endings, and illustration styles live in JSON files at the repository root.

## Current Architecture
- **`app.py`** – Streamlit front-end that orchestrates user input, story generation, illustration prompts, and download actions. Session state isolation ensures reruns do not reset previously generated content.
- **`gemini_client.py`** – Wrapper around `google.generativeai` that builds prompts, handles Gemini responses, and extracts text/image payloads.
- **JSON Assets** – `storytype.json`, `story.json`, and `ending.json` provide story scaffolding. `illust_styles.json` defines illustration style presets.
- **`.env`** – Stores secrets/config such as `GEMINI_API_KEY` and optional `GEMINI_IMAGE_MODEL` override.

## Recent Enhancements
- **Image Model Fallbacks** – `gemini_client.py` now supports configurable image models via `GEMINI_IMAGE_MODEL`, defaulting to `models/gemini-2.5-flash-image-preview` with fallbacks. The client automatically chooses between `ImageGenerationModel` and `GenerativeModel`, retries multiple candidates, and surfaces actionable errors.
- **Illustration Workflow** – `app.py` integrates illustration generation: selected style metadata feeds a structured prompt, and generated images are rendered with Streamlit's `use_container_width` to avoid deprecation warnings.
- **Data & Docs** – Added `illust_styles.json` style catalog and `AGENTS.md` with repo guidelines. JSON story assets were refreshed and normalised to support the UI.
- **Configuration Hygiene** – Committed `.env` now ships with empty placeholders to avoid leaking secrets; users must populate their own keys locally.

## Usage Notes
1. Prepare the environment (Python 3.11+):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Configure `.env` with a valid `GEMINI_API_KEY` and, if needed, a supported `GEMINI_IMAGE_MODEL`.
3. Run locally:
   ```bash
   streamlit run app.py --server.headless true
   ```
4. The UI guides the user through story input, type selection, story generation, and illustration preview/download.

## Follow-up Ideas
- Add automated tests (e.g., `pytest`) with mocks for `google.generativeai`.
- Capture UI regression screenshots when making layout adjustments.
- Consider caching ListModels results to validate available image endpoints dynamically.
