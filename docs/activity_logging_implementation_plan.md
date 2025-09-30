# Activity Logging Implementation Plan

## Scope & Goals
- Capture the user activities defined in `docs/log_spec_detailed.md` without altering current UX flows.
- Lay groundwork for a centralized logging module that can emit structured rows to a log datastore (initially SQLite, optionally Firestore later).
- Preserve IP address slots in the schema while deferring actual IP collection until infrastructure support exists.

## Non-Goals
- No UI changes or new prompts for users.
- No immediate ingestion/analytics pipeline; the work focuses on structured persistence.
- Direct public URL tracking is intentionally out of scope.

## Target Storage Architecture
1. **SQLite Log DB (`activity_log.db`)**
   - Schema mirrors the spec’s common columns plus flexible `param1`~`param5` slots.
   - `id` auto-increment, `datetime` stored as UTC ISO timestamp, `year/month/day` derived on write.
2. **Optional Firestore Mirror (future)**
   - Abstracted behind the logging module so the same payload can be written to SQLite and, when configured, to a Firestore collection (e.g., `activity_logs`).
3. **Initialization**
   - Add `init_activity_log()` to run migrations at startup (called from `app.py` alongside existing init functions).
4. **Toggle**
   - Use `ACTIVITY_LOG_ENABLED` env var (default `true`) to allow disabling logging without code changes.

## Logging Module Outline
Create `activity_log.py` with:
- `ActivityLogEntry` dataclass capturing all columns.
- `init_activity_log(db_path: Path = ACTIVITY_LOG_DB_PATH)` to create tables and indices.
- `log_event(*, type: str, action: str, result: str, user_id: str | None, params: Sequence[str | None], metadata: dict | None = None)` that normalizes fields, fills `year/month/day`, and writes to SQLite (and future Firestore).
- All timestamp fields (`timestamp`, `timestamp_iso`, `year`, `month`, `day`) are recorded in KST (`Asia/Seoul`).
- Graceful no-op when module disabled or DB unavailable (log a warning via `logging.getLogger(__name__)`).
- Reserved IP slot: accept optional `client_ip` argument to populate `param1` when infrastructure later provides it. For now default to `None`.

## Event Mapping
### Story (`type="story"`)
| Action          | Trigger Point                                                                 | Param Mapping                                                                                                                     |
|-----------------|------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `story start`   | Step 2에서 `✨ 제목 만들기` 버튼을 눌러 통합 생성을 시작할 때.                  | `param1`: `story_id`, `param2`: age, `param3`: topic, `param4`: story type name, `param5`: unused.                                         |
| `story card`    | 각 단계의 카드 선택 또는 생성이 완료되었을 때.                               | `param1`: `story_id`, `param2`: 카드 이름, `param3`: 단계 이름, `param4`: unused, `param5`: 오류 메시지(실패 시) 또는 `None`.             |
| `story end`     | 마지막 단계(결말) 카드가 완료되었을 때.                                       | `param1`: `story_id`, `param2`: 카드 이름, `param3`: "결말", `param4`: unused, `param5`: 오류 메시지(실패 시) 또는 `None`.              |
| `story save`    | `export_story_to_html()`가 새로운 저장본을 작성했을 때.                         | `param1`: `story_id`, `param2`: 제목, `param3`: 로컬 경로 또는 GCS 객체, `param4`: 원격 URL, `param5`: 결과 메시지/에러.                |
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
- Include human-readable failure summaries in `param5` when available (e.g., exception message trimmed).

## Testing Strategy
- Unit tests for `activity_log.py` ensuring table creation, insert success, disabled mode, and error resilience when DB path is read-only.
- Story flow tests (`tests/test_app_storage_mode.py` variants) mocking `log_event` to assert calls occur at start/save/view.
- Auth tests verifying logging on signup/login/logout (mock logger to avoid DB dependency).
- Board tests verifying `board read` and `board post` events using monkeypatched logger.

## Follow-Up / Deferred Items
- Actual IP capture once infrastructure supports forwarding client IPs; until then, leave `param1` empty.
- Migration/retrofit path for legacy stories if ID coverage becomes necessary.
- Firestore log sink and downstream analytics integration.
- Optional UI feedback (e.g., admin viewer) is out of scope for current pass.
