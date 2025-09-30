# Admin Tool Usage Guide

The admin console (`admin_app.py`) is a separate Streamlit entry point that ships alongside the story generator. It focuses on moderation, analytics, and log exports without touching the reader UI.

## Prerequisites
- Python 3.11+ with dependencies from `requirements.txt` (includes `pandas` and `google-api-python-client` for analytics/export).
- Firestore activity logging enabled (`ACTIVITY_LOG_ENABLED=true` in the environment) so dashboards have fresh data.
- Firebase Authentication configured with custom claims. Accounts that should access the console must carry `role=admin` (set via `firebase_admin.auth.set_custom_user_claims`).
- Optional: a Google Sheets spreadsheet shared with the service account if you plan to use Sheets exports. The service account needs edit permission on the target sheet.

## Launching the Console
```bash
streamlit run admin_app.py
# headless mode
streamlit run admin_app.py --server.headless true
```

Authenticate with an admin email/password account. Non-admin users are rejected after Firebase token verification. Successful logins write a `type="admin"` event (`action="login"`) so usage can be audited.

## Navigation Overview
- **📊 대시보드** – Rolling activity summary (daily counts, top actions, success/failure split). Filters support type/action/result combinations and arbitrary date ranges. Charts degrade gracefully when `altair`/`pandas` are unavailable.
- **👥 사용자 디렉터리** – Look up Firebase users, toggle the `disabled` flag, manage roles, generate password reset links, and apply sanctions (ban/mute/unban). Each mutation emits a `type="admin"` or `type="moderation"` log with the reason, duration, and optional context ID.
- **🔍 활동 탐색기** – Page through Firestore activity logs in descending timestamp order. Supports multi-select filters, free-form action tokens, and pagination for deeper investigations.
- **⬇️ 로그 내보내기** – Gather up to `MAX_EXPORT_ROWS` (100k) records into a CSV download or push them into a Google Sheet. CSV exports stream directly; Sheets exports create or clear a worksheet named `activity_logs_YYYYMMDD_HHMM`.

## Google Sheets export setup
1. Share the destination spreadsheet with the service account used for Firestore (`google_credentials`); it needs edit permission.
2. Verify dependencies: `google-api-python-client` must be installed and the admin app must have access to `.env` credentials.

### Export workflow
1. Apply the desired filters in **⬇️ 로그 내보내기** (type, result, action, date range).
2. Confirm the row count shown below the filters. Large exports stop at `MAX_EXPORT_ROWS` (100k).
3. Copy the spreadsheet ID (the portion between `/d/` and `/edit` in the Sheet URL) into the `Google Sheets 스프레드시트 ID` field.
4. Click **Google Sheets로 내보내기**. The tool creates (or clears) a worksheet named `activity_logs_YYYYMMDD_HHMM` and uploads the rows.
5. Success responses include a clickable link to the sheet. Failures appear inline and log a `type="admin"`, `action="export sheets"` event with the error message for follow-up.

## Moderation Sanctions
- Available sanction types: `ban`, `mute`, and `unban`. Duration presets cover `permanent`, `24h`, `7d`, and `30d`.
- Reason codes follow the design document (`spam`, `abuse`, `safety`, `copyright`, `user_request`, `other`).
- Sanction metadata is stored in the user's custom claims under `sanction` and logged via `type="moderation"` events so future tooling can inspect enforcement history.

## Troubleshooting
- **Activity data missing**: confirm the main app calls `init_activity_log()` at startup and that Firestore credentials are valid. Disabled logging triggers a warning in the sidebar.
- **Login loop**: verify the Firebase account carries `role=admin` and that Admin SDK credentials are available (`GOOGLE_APPLICATION_CREDENTIALS`/`FIREBASE_SERVICE_ACCOUNT`).
- **Sheets export errors**: check that `google-api-python-client` is installed, the service account has edit permission, and the spreadsheet ID is correct. Details appear in the UI and the activity log.
- **Sanction not reflected**: the user tool only writes custom claims today; enforcement inside the story app or board still requires additional wiring in a future release.
- **Firestore index required**: complex queries (예: `result` + `type` 필터에 `timestamp` 정렬) trigger a `The query requires an index` error. Follow the console link or create a composite index manually: collection `activity_logs`, fields `result (ASC)`, `type (ASC)`, `timestamp (DESC)`. Repeat for additional filter combinations as they appear.

For architectural background and backlog, see `docs/admin_tool_design.md`.
