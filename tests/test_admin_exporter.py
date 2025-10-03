from __future__ import annotations

import sys
import types

import pytest

from types import SimpleNamespace

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


def test_export_rows_stringifies_complex_values(monkeypatch):
    rows = [
        {
            "id": "1",
            "metadata": {
                "type": "ban",
                "applied_by": "test@test.com",
                "expires_at": "2025-10-01T17:34:33.708149+00:00",
            },
            "flags": ["a", "b"],
            "active": True,
            "count": 3,
        }
    ]

    class FakeCred:
        def with_scopes(self, scopes):  # noqa: ARG002
            return self

    monkeypatch.setattr(exporter, "get_service_account_credentials", lambda: FakeCred())

    class FakeValues:
        def __init__(self, calls):
            self._calls = calls

        def update(self, **kwargs):  # noqa: D401
            self._calls.append(kwargs)
            return SimpleNamespace(execute=lambda: None)

        def clear(self, **kwargs):  # noqa: ARG002, D401
            return SimpleNamespace(execute=lambda: None)

    class FakeSheetService:
        def __init__(self):
            self.values_calls: list[dict[str, object]] = []
            self._values = FakeValues(self.values_calls)

        def get(self, **kwargs):  # noqa: ARG002, D401
            return SimpleNamespace(execute=lambda: {"sheets": []})

        def batchUpdate(self, **kwargs):  # noqa: ARG002, D401
            return SimpleNamespace(
                execute=lambda: {"replies": [{"addSheet": {"properties": {"sheetId": 123}}}]}
            )

        def values(self):
            return self._values

    class FakeService:
        def __init__(self):
            self.sheet_service = FakeSheetService()

        def spreadsheets(self):
            return self.sheet_service

    fake_service = FakeService()

    fake_googleapi = types.ModuleType("googleapiclient")
    fake_discovery = types.ModuleType("googleapiclient.discovery")
    fake_discovery.build = lambda *args, **kwargs: fake_service
    fake_googleapi.discovery = fake_discovery
    monkeypatch.setitem(sys.modules, "googleapiclient", fake_googleapi)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", fake_discovery)

    sheet_url = exporter.export_rows_to_google_sheet(
        rows,
        spreadsheet_id="sheet-id",
        worksheet_title="activity_logs_test",
    )

    assert sheet_url.endswith("gid=123")
    assert fake_service.sheet_service.values_calls, "update() should have been invoked"
    update_kwargs = fake_service.sheet_service.values_calls[0]
    values = update_kwargs["body"]["values"]
    # Header row + data row expected
    assert values[0] == ["id", "metadata", "flags", "active", "count"]
    assert values[1][values[0].index("metadata")].startswith("{")
    assert values[1][values[0].index("flags")] == "[\"a\", \"b\"]"
    assert values[1][values[0].index("active")] == "TRUE"
    assert values[1][values[0].index("count")] == "3"
