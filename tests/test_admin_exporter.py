from __future__ import annotations

import sys
import types

import pytest

from admin_tool import exporter


def test_rows_to_csv_bytes():
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    csv_bytes = exporter.rows_to_csv_bytes(data)
    assert csv_bytes.startswith(b"a,b")
    assert b"3,4" in csv_bytes


def test_export_rows_requires_dependency(monkeypatch):
    monkeypatch.setattr(exporter, "get_service_account_credentials", lambda: None)

    with pytest.raises(RuntimeError):
        exporter.export_rows_to_google_sheet([], spreadsheet_id="sheet", worksheet_title="demo")
