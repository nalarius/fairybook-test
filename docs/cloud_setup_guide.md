# Cloud Configuration Checklist

This guide consolidates the infrastructure steps needed to run both the reader app (`app.py`) and the admin console (`admin_app.py`). Use it as a quick audit when configuring new environments or rotating credentials.

## 1. Google Cloud Project
- Create (or reuse) a GCP project. Keep the **Project ID** handy (lowercase-with-hyphen format). Example: `level-works-472919-m6`.
- Enable the following APIs (via Google Cloud Console → APIs & Services):
  - Firestore API
  - Cloud Storage API
  - Identity Toolkit API (Firebase Auth)
  - Google Sheets API (required for the admin export button).
- For local development, set `.env` values:
  ```ini
  GCP_PROJECT_ID="your-project-id"
  GCP_PROJECT="your-project-id"  # optional; keep consistent with GCP_PROJECT_ID
  ```

## 2. Service Account & Credentials
- Create a service account with permissions for **Firestore**, **Cloud Storage**, and **Firebase Admin SDK**.
- Generate a JSON key (e.g., `google-credential.json`) and store it in the project root (never commit it).
- Update `.env` so both the main app and admin console can find the key:
  ```ini
  GOOGLE_APPLICATION_CREDENTIALS="google-credential.json"
  FIREBASE_SERVICE_ACCOUNT="google-credential.json"
  ```
- To verify the credentials without launching Streamlit, run:
  ```bash
  python scripts/verify_firebase_admin.py
  ```
  The script checks that the Admin SDK can create custom tokens with the supplied key and project ID.

## 3. Firebase Authentication
- In the Firebase Console (same project as above), enable Email/Password sign-in under **Authentication → Sign-in method**.
- Obtain the Web API key from **Project settings → General → Web API Key**.
- Populate `.env`:
  ```ini
  FIREBASE_WEB_API_KEY="your-web-api-key"
  AUTH_DOMAIN="your-app.firebaseapp.com"  # optional, used if you host custom auth widgets
  ```
- Grant admin access to specific accounts via the helper script:
  ```bash
  python scripts/grant_admin_role.py <UID>
  python scripts/list_admin_users.py
  ```
  Admin logins require a custom claim `role=admin`.

## 4. Firestore
- Select **Firestore in Native mode**. The apps expect a collection named `activity_logs`.
- `.env` defaults:
  ```ini
  FIRESTORE_ACTIVITY_COLLECTION="activity_logs"
  ACTIVITY_LOG_ENABLED="true"
  ```
- Create required composite indexes when prompted. Common example for the admin dashboard:
  - Collection: `activity_logs`
  - Fields: `result (ASC)`, `type (ASC)`, `timestamp (DESC)`
  Firestore will link directly to index creation if a new filter combination needs it.

## 5. Google Sheets Export
- Share any destination spreadsheet with the service account email so it has edit permission.
- The admin console expects the spreadsheet ID (the portion between `/d/` and `/edit` in the URL).
- When you click **Google Sheets로 내보내기**, the app will create or reset a worksheet named `activity_logs_YYYYMMDD_HHMM`. A success toast includes the sheet link.
- Example error to watch for:
  - `SERVICE_DISABLED`: enable the Google Sheets API for the project and retry.
  - `PERMISSION_DENIED`: ensure the service account is shared on the spreadsheet with at least editor access.

## 7. Cloud Storage Bucket (optional but recommended)
- Create a bucket to host exported stories (e.g., `fairybook-seoul`).
- Grant the service account `Storage Object Admin` or the minimum role needed to upload/download objects.
- `.env` values:
  ```ini
  STORY_STORAGE_MODE="remote"  # use "local" to skip Cloud Storage
  GCS_BUCKET_NAME="fairybook-seoul"
  GCS_PREFIX="fairybook/"        # folder/prefix inside the bucket
  ```

## 8. Environment File (`.env`) Recap
```
GEMINI_API_KEY="..."
GEMINI_TEXT_MODEL="models/gemini-2.5-flash"
GEMINI_IMAGE_MODEL="models/gemini-2.5-flash-image-preview"
GOOGLE_APPLICATION_CREDENTIALS="google-credential.json"
FIREBASE_SERVICE_ACCOUNT="google-credential.json"
FIREBASE_WEB_API_KEY="..."
GCP_PROJECT_ID="your-project-id"
GCP_PROJECT="your-project-id"
GCS_BUCKET_NAME="fairybook-seoul"
GCS_PREFIX="fairybook/"
FIRESTORE_ACTIVITY_COLLECTION="activity_logs"
ACTIVITY_LOG_ENABLED="true"
STORY_STORAGE_MODE="remote"
```
- Both Streamlit apps load `.env` automatically, so keep the file in the repository root.

## 9. Post-setup Testing
1. `python scripts/verify_firebase_admin.py` → Admin SDK check.
2. `streamlit run app.py --server.headless true` → Story generator sanity test.
3. `streamlit run admin_app.py --server.headless true` → Admin console; confirm dashboard loads (after index creation) and role-restricted login works.
4. Run the test suite for regression checks:
   ```bash
   PYTHONPATH=. pytest
   ```

Keep this checklist alongside `docs/admin_tool_design.md` and `docs/admin_tool_usage.md` so infra configuration remains consistent across environments.
