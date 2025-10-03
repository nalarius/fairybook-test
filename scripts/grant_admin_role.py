#!/usr/bin/env python
"""Assign or remove the Firebase admin role (role=admin custom claim)."""
from __future__ import annotations

import argparse
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


def set_role(uid: str, make_admin: bool) -> None:
    initialize_admin()
    user = auth.get_user(uid)
    claims = dict(user.custom_claims or {})
    if make_admin:
        claims["role"] = "admin"
    else:
        claims.pop("role", None)
    auth.set_custom_user_claims(uid, claims or None)
    status = "granted" if make_admin else "removed"
    print(f"Admin role {status} for UID={uid}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grant or revoke the Firebase admin role.")
    parser.add_argument("uid", help="Firebase Authentication UID")
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove the admin role instead of granting it.",
    )
    return parser.parse_args()


def main() -> None:
    load_env()
    args = parse_args()
    set_role(args.uid, make_admin=not args.remove)


if __name__ == "__main__":
    main()
