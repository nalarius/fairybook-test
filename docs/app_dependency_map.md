# Application Dependency Map

This document captures how the Streamlit entry points orchestrate supporting
modules after the recent refactor. Use it as a guide when adding features or
moving logic into new packages.

## Entry Points

| File | Responsibilities | Key dependencies |
| ---- | ---------------- | ---------------- |
| `app.py` | Loads JSON configuration, boots activity logging/story library, builds a `CreatePageContext`, delegates create-flow steps, renders saved-story and board views. | `ui/create/*`, `session_state`, `services.story_service`, `gemini_client`, `ui.board`, `ui.home`, `telemetry` |
| `admin_app.py` | Handles admin authentication, renders navigation, routes to admin subviews. | `admin_ui/dashboard`, `admin_ui/moderation`, `admin_ui/explorer`, `admin_ui/exports`, `admin_tool.*` |

## Create Flow (`ui/create`)

`CreatePageContext` bundles session proxy access plus static assets
(story types, cards, illustration styles). Each step module consumes the
context and focuses solely on UI + state transitions:

| Step module | Function | External calls |
| ----------- | -------- | -------------- |
| `step1.py` | Collect age/topic, reset story session | `session_state.reset_*` |
| `step2.py` | Story-type selection, “generate all” workflow | `gemini_client.generate_*`, `telemetry.emit_log_event`, `random`, `session_state.reset_*` |
| `step3.py` | Review title, cover, protagonist info | Session reads only |
| `step4.py` | Card selection per story phase | `session_state.reset_*`, uses `STORY_PHASES`, `random` |
| `step5.py` | Stage generation progress/results | `gemini_client.generate_story_with_gemini`, `gemini_client.build_image_prompt`, `telemetry.emit_log_event` |
| `step6.py` | Story aggregation/export | `services.story_service.export_story_to_html`, `gcs_storage`, `story_library.record_story_export` |

Shared create-flow dependencies:

- `session_state` now proxies through `StorySessionProxy`, avoiding direct
  Streamlit globals in downstream helpers.
- `gemini_client` exposes high-level text/image helpers but delegates
  transport concerns to `services.gemini_api` and prompt assembly to
  `prompts.story`.
- `services.story_service` owns HTML export plus stage dataclasses.

## Gemini Client Stack

| Layer | Purpose |
| ----- | ------- |
| `services/gemini_api.py` | SDK configuration (`google.generativeai`), retry logic, image handling. |
| `prompts/story.py` | Centralised text templates, stage guidance constants, image prompt builder. |
| `gemini_client.py` | Backwards-compatible façade used by UI: validates inputs, marshals parameters, returns dict payloads. |

Tests patch the API key in both `gemini_client` and `services.gemini_api` to
avoid hitting real endpoints (`tests/test_gemini_client.py`).

## Session Management

- `session_proxy.py` defines `StorySessionProxy`, which wraps
  `st.session_state` without storing custom objects inside Streamlit state.
- `session_state.ensure_state` seeds defaults through the proxy and the new
  smoke test (`tests/test_session_proxy_smoke.py`) verifies helper behaviour
  without requiring Streamlit.

## Admin Console (`admin_app.py`)

| Module | Responsibilities | Notes |
| ------ | ---------------- | ----- |
| `admin_ui/common.py` | Shared filter builders, Altair/pandas bridges. | Imported by other views. |
| `dashboard.py` | Aggregated metrics, charts, summary cards. | Calls `admin_tool.activity_service`. |
| `explorer.py` | Paged activity log explorer with cursor support. | Uses `fetch_activity_page`. |
| `moderation.py` | User directory, role management, sanctions. | Wraps `admin_tool.user_service`, logs via callbacks. |
| `exports.py` | CSV / Sheets export flow. | Uses `admin_tool.exporter`. |

`admin_app.py` keeps authentication, navigation, and logging hooks so each
view stays stateless and composable.

## Related Tests

- `tests/test_prompts_story.py` confirms prompt guidance remains in sync.
- `tests/test_gemini_client.py` exercises the façade after layering changes.
- `tests/test_session_proxy_smoke.py` ensures session helpers behave with the
  proxy abstraction.
- `tests/test_story_service_smoke.py` (optional) smokes the HTML export path
  and can be staged when needed.

This layout allows new functionality to live in focused modules — when adding a
step or admin view, prefer creating a sibling file rather than expanding the
entry points.

