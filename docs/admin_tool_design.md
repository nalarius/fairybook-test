# Admin Tool Design Brief

## Context
- Builds on the activity telemetry captured per `docs/activity_logging_implementation_plan.md` (`activity_logs` collection in Firestore, five param slots, KST timestamps, `ACTIVITY_LOG_ENABLED` toggle).
- Runs as a separate Streamlit application (e.g., `admin_app.py`) that imports shared modules (`activity_log`, auth helpers) but is deployed independently from `app.py` to preserve reader UI isolation.
- Serves operations staff who monitor community health, moderate users, and investigate story/board issues without altering the Streamlit reader UI.

## Goals & Non-Goals
- **Goals**
  - Provide a dedicated Streamlit-based console (deployed separately from the main `app.py`) gated behind admin auth.
  - Centralize user management controls (role assignment, account status, reset links) backed by Firebase Auth.
  - Deliver log analytics focused on the existing logging schema: filtering, aggregation, and exports.
- **Non-Goals**
  - Real-time dashboards or alerting (deferred).
  - Modifying the public story-generation experience.
  - Adding new capabilities to the story generator app during the first admin-tool release.
  - Scheduled report emails or automated distribution workflows.
  - Formal export retention/expiration handling (defer until requirements emerge).
  - Bulk destructive operations without confirmation safeguards.

## Target Personas & Permissions
- **Admin**: Every admin-tool user receives the full capability set (user management, analytics, exports).
- Gate access via Firebase custom claims (`role=admin`) or a Firestore-backed ACL collection. `ensure_state` wiring in `app.py` must keep admin state siloed from reader sessions even though the app runs separately.
- Document the onboarding flow: how to assign/remove the admin claim and how auditing is handled via `type="admin"` log events.
- Admins own DSAR/개인정보 요청 대응: tool must surface per-user activity exports so they can fulfill data subject requests without engineering support.

## Information Architecture
1. **Navigation Shell**
   - Sidebar: `Dashboard (lite)`, `User Directory`, `Activity Explorer`, `Exports`.
   - Persistent header exposing active project, last sync, and quick filters (date range, action type).
2. **Primary Views**
   - `Dashboard (Usage Overview)`
     - Surface key indicators: daily/weekly log volume, active user counts (unique `user_id` in `activity_logs`), top actions by frequency, failure rate trendlines, and quick filters for action type/date.
     - Provide context cards (e.g., "지난 7일 story start: 1,245", "실패율 2.1%") with comparative deltas against the prior period.
     - Allow drill-through links into the Activity Explorer with the relevant filters pre-applied.
   - `User Directory`
     - Search by email, UID, display name.
     - Table columns: UID, email, display name, creation date, last sign-in, status (enabled/disabled), roles.
     - Row-level actions: toggle enabled flag, initiate password reset email, promote/demote role, apply sanctions (mute/ban/unban) with reason selection from the approved set (`spam`, `abuse`, `safety`, `copyright`, `user_request`, `other`) and duration presets (`permanent`, `24h`, `7d`, `30d`).
     - Audit log: admin action events should log to `activity_logs` (`type="admin"` for account changes, `type="moderation"` for sanctions).
   - `Activity Explorer`
     - Filter chips: `type` (`story`, `user`, `board`, `moderation`, `admin`), `action`, date range (preset + custom), result (`success`/`fail`), free-text search across params.
     - Aggregation widgets: daily counts, action-by-result heatmap, top N failing actions.
     - Detail table driven by Firestore query or cached BigQuery export (future). Use pagination with server-side fetch to avoid large payloads.
     - Drill-in modal shows raw payload (params, metadata ISO timestamp, client IP placeholder).
   - `Exports`
     - Date-range selector (UTC & KST validation) + action filter.
     - Output options: `Download CSV` (Streamlit download button) and `Export to Google Sheet` (service account with Sheets API scoped credentials).
     - Background job queue optional; MVP can run synchronously with progress indicator.

## Functional Requirements
- **Authentication & Access**
  - Admin login shares Firebase Auth backend; only users with admin claim can reach the tool.
  - Session separation: admin session state uses unique Streamlit keys (`admin_session_*`).
- **User Management**
  - Read users via Firebase Admin SDK (`list_users` pagination) with caching.
  - Update operations call Admin SDK: `update_user` for disabled flag, `generate_password_reset_link`, `set_custom_user_claims`.
  - All user-management mutations emit `type="admin"` log entries (`action`: `user disable`, `user enable`, `role promote`, etc.) using existing `log_event` helper to retain schema consistency.
- **Moderation Controls**
  - Admins can hide/restore community board posts and apply user sanctions (mute/ban/unban) from the admin tool.
  - Hide/restore dialogs expose the standardized reason list (`spam`, `abuse`, `safety`, `copyright`, `user_request`, `other`) and require moderator notes (≤280 chars) when `other` is chosen.
  - Sanction workflows limit duration choices to `permanent`, `24h`, `7d`, `30d`; timed sanctions compute an ISO8601 expiry and persist it in log metadata.
  - Target selectors default to the supported entity catalog (`board_post`, `board_comment`, `story`, `user_submission`); expanding the catalog requires updating both UI enums and analytics filters.
  - Every moderation action must call `log_event` with `type="moderation"` and populate params per `docs/activity_logging_implementation_plan.md` (target type, target ID, reason key, moderator note, previous status).
- **Usage Dashboard & Log Analytics**
  - Moderation widgets track action counts by reason code, sanction duration, and target type to surface repeat issues.
  - Respect `ACTIVITY_LOG_ENABLED`; if logging is disabled, surface warning banner.
  - Dashboard metrics derive from `ActivityLogEntry` aggregations: compute daily counts, distinct user IDs, action-by-result breakdowns, and rolling failure rate summaries.
  - Filters translate to Firestore queries (date range uses `timestamp` field; action/type filter uses indexed fields). For complex search, hydrate locally after initial query.
  - Aggregations computed in-memory for short ranges; display prompt to narrow dates when the query approaches Firestore limits.
  - Charting via Streamlit `altair` components; all charts must work headlessly when `--server.headless true`.
- **CSV / Sheets Export**
  - Leverage Pandas to materialize query results and stream to CSV.
  - Set `MAX_EXPORT_ROWS = 100_000` for the first release (configurable constant) so analysts can retrieve sizable datasets while staying within Firestore quotas.
  - For Google Sheets, use service account credentials stored with other secrets; write to a timestamped worksheet (`activity_logs_YYYYMMDD_HHMM`). Provide link after success.
  - Compress CSV if >10MB before download to reduce bandwidth.

## Data Flow Overview
1. User selects filters → Streamlit form submission.
2. Backend calls `activity_log.fetch_entries(...)` (new helper) that encapsulates Firestore pagination, returns list of `ActivityLogEntry` + metadata.
3. View layer renders tables/charts, merges user lookups (UID → email) for readability.
4. Export options reuse the same fetch results; large exports chunk requests by week to avoid Firestore limits.
5. Administrative actions on Firebase emit `log_event` with `type="admin"`, while moderation workflows invoke `type="moderation"`, ensuring governance and enforcement both surface in daily reports.

## Technical Notes
- Introduce a standalone entrypoint (e.g., `admin_app.py`) that composes admin pages from `admin_tool` modules; share data-access helpers via reusable packages without coupling to `app.py`.
- Keep admin components in an `admin_tool/` package so shared queries/auth adapters can be reused by other tooling without leaking board/story UI state.
- Shared constants for date formats, export limits (`MAX_EXPORT_ROWS`), and default ranges (last 7 days).
- Google Sheets setup: enable the Sheets API for the service account, grant it domain-wide delegation if required, and share any managed spreadsheet (or drive folder) with the service-account email so exports can append worksheets without manual intervention.
- Encode moderation enums (reason codes, target types, sanction durations) in a shared constants module so Sheets exports and analytics stay aligned with the UI.
- Implement caching layer (e.g., `functools.lru_cache` or `st.cache_data`) keyed by filter tuple with TTL to avoid repetitive Firestore reads.
- Localization: maintain existing Korean copy; add admin-specific strings to a dedicated constants module for easier review.
- Accessibility: ensure tables and buttons have clear labels; support keyboard navigation.

## Risks & Mitigations
- **Firestore Query Limits**: apply range + action filters, paginate using document snapshots, instruct analysts to limit exports.
- **Credential Leakage**: admin tool loads service-account creds; guard with `.env` variables and avoid logging sensitive info.
- **State Bleed**: isolate admin Streamlit session state keys, separate modules to keep community board unaffected.
- **Sheets API Quota**: throttle exports, store per-admin usage metrics in `activity_logs` to monitor.

## Open Questions & Follow-Up
- None for v1; revisit moderation taxonomy and DSAR workflow after rollout metrics are reviewed.

