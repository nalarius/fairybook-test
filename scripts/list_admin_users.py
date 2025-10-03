#!/usr/bin/env python
"""List Firebase users who carry the admin custom claim."""
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
        "Firebase service account file not found. Set GOOGLE_APPLICATION_CREDENTIALS or FIREBASE_SERVICE_ACCOUNT."
    )


def resolve_project_id() -> str:
    project_id = (os.getenv("GCP_PROJECT_ID") or os.getenv("GCP_PROJECT") or "").strip()
    if not project_id:
        raise SystemExit("GCP_PROJECT_ID must be set (check .env).")
    return project_id


def initialize_admin() -> None:
    if firebase_admin._apps:  # type: ignore[attr-defined]
        return
    cred_path = resolve_credentials_path()
    project_id = resolve_project_id()
    cred = credentials.Certificate(str(cred_path))
    firebase_admin.initialize_app(cred, {"projectId": project_id})


def list_admins() -> None:
    initialize_admin()
    print("Fetching users with role=admin…")
    page = auth.list_users()
    found = 0
    while page:
        for user in page.users:
            claims = user.custom_claims or {}
            if claims.get("role") == "admin":
                found += 1
                print(f"UID={user.uid} | email={user.email} | display_name={user.display_name}")
        page = page.get_next_page()
    if found == 0:
        print("No admin users found.")
    else:
        print(f"Total admins: {found}")


def main() -> None:
    load_env()
    list_admins()


if __name__ == "__main__":
    main()
