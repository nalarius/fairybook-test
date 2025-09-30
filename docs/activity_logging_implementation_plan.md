# Activity Logging Implementation Plan

## Scope & Goals
- Capture the story, user, and board activity events defined in the product logging spec without altering existing UX flows.
- Provide a centralized logging module that persists structured rows to Firestore (default collection `activity_logs`).
- Preserve client-IP placeholders in the schema while deferring actual IP collection until infrastructure support exists.

## Non-Goals
- No UI changes or additional prompts for users.
- No immediate ingestion/analytics pipeline; focus on durable, structured persistence.
- Direct public URL tracking remains out of scope.

## Target Storage Architecture
1. **Firestore Collection (`activity_logs`)**
   - Firestore is the primary store. The module resolves the target project from `GCP_PROJECT_ID` or the loaded service-account credentials (`google_credentials.get_service_account_credentials()`).
   - Each document captures `type`, `action`, `result`, `user_id`, `client_ip`, localized timestamp metadata, and five flexible params (`param1`~`param5`).
   - `init_activity_log()` warms the collection during Streamlit startup so credential failures surface early.
2. **Runtime Toggle**
   - `ACTIVITY_LOG_ENABLED` (default `true`) disables logging without code edits. When disabled, the module is a no-op.
3. **Future Enhancements (Deferred)**
   - A lightweight SQLite fallback or dual-write mode can be revisited if offline capture becomes necessary. No local database ships today.

## Logging Module Outline
`activity_log.py` currently provides:
- `ActivityLogEntry` dataclass mirroring the Firestore payload for ergonomic testing and future consumers.
- `init_activity_log()` which caches a Firestore client, verifies collection access, and flips an internal `_ACTIVITY_LOG_ACTIVE` flag. Failures call `_disable_logging()` so the UI can degrade gracefully.
- `log_event(*, type: str, action: str, result: str, user_id: str | None, params: Sequence[str | None] | None = None, client_ip: str | None = None, metadata: Mapping[str, Any] | None = None)` that normalizes inputs, pads/trims params to five slots, stamps KST metadata, writes the document, and returns an `ActivityLogEntry` when successful.
- Result normalization (`success` / `fail`), KST-aware timestamps (`timestamp`, `timestamp_iso`, `year`, `month`, `day`), and automatic disabling on repeated Firestore failures.
- Reserved IP slot: `client_ip` is stored separately and remains `None` until upstream infrastructure forwards the value.

## Event Mapping
### Story (`type="story"`)
| Action          | Trigger Point                                                                 | Param Mapping                                                                                                                     |
|-----------------|------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `story start`   | Step 2에서 `✨ 제목 만들기` 버튼을 눌러 통합 생성을 시작할 때.                  | `param1`: `story_id`, `param2`: age, `param3`: story type name, `param4`: topic(빈칸 시 "(빈칸)"), `param5`: unused.             |
| `story card`    | 각 단계의 카드 선택 또는 생성이 완료되었을 때.                               | `param1`: `story_id`, `param2`: 카드 이름, `param3`: 단계 이름, `param4`: unused, `param5`: 오류 메시지(실패 시) 또는 `None`.          |
| `story end`     | 마지막 단계(결말) 카드가 완료되었을 때.                                       | `param1`: `story_id`, `param2`: 카드 이름, `param3`: "결말", `param4`: unused, `param5`: 오류 메시지(실패 시) 또는 `None`.           |
| `story save`    | `export_story_to_html()`가 새로운 저장본을 작성했을 때.                         | `param1`: `story_id`, `param2`: 제목, `param3`: 로컬 경로 또는 GCS 객체, `param4`: 원격 URL, `param5`: 결과 메시지/에러.             |
| `story view`    | 저장된 HTML을 불러올 때.                                                      | `param1`: `story_id` 또는 선택 토큰, `param2`: 제목, `param3`: origin (`record`/`legacy-remote` 등), `param4`: 경로 또는 URL, `param5`: 오류. |

### User (`type="user"`)
| Action  | Trigger Point                                    | Param Mapping                                                                 |
|---------|--------------------------------------------------|--------------------------------------------------------------------------------|
| signup  | `firebase_auth.sign_up` succeeds/fails           | `param1`: (future IP placeholder), `param2`: display name, others empty.       |
| login   | `firebase_auth.sign_in` succeeds/fails           | Same mapping as signup.                                                        |
| logout  | Logout handler in `app.py` (popover)             | `param1`: IP placeholder, `param2`: display name at logout time.               |

### Board (`type="board"`)
| Action      | Trigger Point                                               | Param Mapping                                                               |
|-------------|-------------------------------------------------------------|------------------------------------------------------------------------------|
| board read  | Entering board mode (`render_board_page` call).              | `param1`: IP placeholder, `param2`: display name (if available).             |
| board post  | After `community_board.add_post` succeeds/fails.             | `param1`: post ID (db row or Firestore doc ID), `param2`: display name.      |

## Error Handling & Result Field
- `result` should be `success` when the action completes, `fail` on caught exceptions. Catch points:
  - Wrap around Gemini/story generation handlers for save events.
  - User auth/board posting already raise; capture exceptions at call sites to log `fail` before surfacing errors.
- Include human-readable failure summaries in `param5` when available (예: trimmed exception message).

## Testing Strategy
- `tests/test_activity_log.py` monkeypatches Firestore to verify toggles, payload normalization, and graceful disablement paths.
- Story flow tests mock `emit_log_event` to assert start/save/view hooks fire without hitting external services.
- Auth tests verify logging on signup/login/logout (mock logger to avoid external calls).
- Board tests assert `board read` and `board post` events using monkeypatched logger helpers.

## Follow-Up / Deferred Items
- Optional dual-write to SQLite for offline capture.
- Actual IP capture once infrastructure supports forwarding client addresses.
- Migration/retrofit path for legacy stories if ID coverage becomes necessary.
- Firestore log sink and downstream analytics integration.
- Optional UI feedback (예: admin viewer) remains out of scope for this pass.
