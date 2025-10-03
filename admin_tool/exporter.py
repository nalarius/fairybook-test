"""Export helpers for the admin console."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping as AbcMapping, Sequence as AbcSequence
from datetime import date, datetime
from typing import Iterable, Mapping, Sequence

from google_credentials import get_service_account_credentials

_SPREADSHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def rows_to_csv_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    """Serialize rows into UTF-8 CSV bytes with headers inferred from keys."""

    field_names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                field_names.append(key)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_names or ["value"])
    writer.writeheader()
    for row in rows:
        if field_names:
            writer.writerow({key: _stringify_cell(row.get(key, "")) for key in field_names})
        else:
            writer.writerow({"value": _stringify_cell(row)})
    return buffer.getvalue().encode("utf-8")


def _stringify_cell(value: object) -> str:
    """Convert complex values into a Sheets-friendly string representation."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, AbcMapping):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return str(value)
    if isinstance(value, AbcSequence) and not isinstance(value, (str, bytes, bytearray)):
        try:
            return json.dumps(list(value), ensure_ascii=False, default=str)
        except TypeError:
            return str(list(value))
    return str(value)


def export_rows_to_google_sheet(
    rows: Sequence[Mapping[str, object]],
    *,
    spreadsheet_id: str,
    worksheet_title: str | None = None,
) -> str:
    """Append rows to a dedicated worksheet inside a spreadsheet.

    Returns the URL to the populated worksheet.
    """

    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "google-api-python-client is required for Google Sheets export."
        ) from exc

    credentials = get_service_account_credentials()
    if credentials is None:
        raise RuntimeError("Service-account credentials are required for Sheets export.")

    scoped = credentials.with_scopes([_SPREADSHEETS_SCOPE])
    service = build("sheets", "v4", credentials=scoped, cache_discovery=False)

    sheet_title = worksheet_title or f"activity_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M')}"

    sheet_service = service.spreadsheets()
    spreadsheet = sheet_service.get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title))",
    ).execute()

    sheet_id = None
    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("title") == sheet_title:
            sheet_id = props.get("sheetId")
            # Clear previous contents when reusing the worksheet.
            sheet_service.values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"'{sheet_title}'",
            ).execute()
            break

    if sheet_id is None:
        response = sheet_service.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": sheet_title,
                            }
                        }
                    }
                ]
            },
        ).execute()
        sheet_id = (
            response.get("replies", [{}])[0]
            .get("addSheet", {})
            .get("properties", {})
            .get("sheetId")
        )

    header: list[str] = []
    seen_fields: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen_fields:
                seen_fields.add(key)
                header.append(key)

    values: list[list[object]] = []
    if header:
        values.append(header)
        for row in rows:
            values.append([_stringify_cell(row.get(field, "")) for field in header])
    else:
        values.append(["value"])
        for row in rows:
            values.append([_stringify_cell(row)])

    sheet_service.values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_title}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet_id}"


__all__ = ["rows_to_csv_bytes", "export_rows_to_google_sheet"]
