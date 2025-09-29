from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

import firebase_admin
from firebase_admin import auth, credentials


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"


def load_env() -> None:
    if ENV_PATH.is_file():
        load_dotenv(ENV_PATH, override=False)


def resolve_credentials_path() -> Path:
    candidates = (
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        os.getenv("FIREBASE_SERVICE_ACCOUNT"),
    )
    for raw_path in candidates:
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Unable to locate Firebase service account file. "
        "Set GOOGLE_APPLICATION_CREDENTIALS or FIREBASE_SERVICE_ACCOUNT."
    )


def resolve_project_id() -> str:
    project_id = (os.getenv("GCP_PROJECT_ID") or os.getenv("GCP_PROJECT") or "").strip()
    if not project_id:
        raise SystemExit("GCP_PROJECT_ID is required in .env before running this check.")
    return project_id


def main() -> None:
    load_env()

    cred_path = resolve_credentials_path()
    project_id = resolve_project_id()

    print(f"Using credentials: {cred_path}")
    print(f"Target project: {project_id}")

    if not firebase_admin._apps:  # type: ignore[attr-defined]
        cred = credentials.Certificate(str(cred_path))
        firebase_admin.initialize_app(cred, {"projectId": project_id})

    dummy_uid = "firebase-setup-check"
    custom_token = auth.create_custom_token(dummy_uid)
    preview = custom_token.decode("utf-8")[:40]
    print(f"Custom token created (preview): {preview}...")

    try:
        auth.get_user(dummy_uid)
        print("Firebase reachable: dummy user already exists.")
    except firebase_admin.auth.UserNotFoundError:
        print("Firebase reachable: dummy user does not exist (expected).")

    print("Firebase Admin SDK initialized successfully with .env configuration.")


if __name__ == "__main__":
    main()
