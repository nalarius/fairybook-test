"""Session proxy for wrapping Streamlit's session state mapping."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Iterator


class StorySessionProxy:
    """Lightweight view over a Streamlit ``session_state`` mapping."""

    def __init__(self, backing: MutableMapping[str, Any]):
        self._backing = backing

    # Basic mapping compatibility -------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._backing[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._backing[key] = value

    def __contains__(self, key: object) -> bool:  # pragma: no cover - mapping helper
        return key in self._backing

    def get(self, key: str, default: Any = None) -> Any:
        return self._backing.get(key, default)

    def setdefault(self, key: str, default: Any) -> Any:
        return self._backing.setdefault(key, default)

    def update(self, values: MutableMapping[str, Any]) -> None:
        self._backing.update(values)

    def pop(self, key: str, default: Any | None = None) -> Any:
        return self._backing.pop(key, default)

    def keys(self) -> Iterator[str]:  # pragma: no cover - mapping helper
        return iter(self._backing.keys())

    def items(self) -> Iterator[tuple[str, Any]]:  # pragma: no cover - mapping helper
        return iter(self._backing.items())

    # Convenience accessors -------------------------------------------------------
    @property
    def step(self) -> int:
        return int(self._backing.get("step", 0) or 0)

    @step.setter
    def step(self, value: int) -> None:
        self._backing["step"] = int(value)

    @property
    def mode(self) -> str | None:
        mode = self._backing.get("mode")
        return str(mode) if mode is not None else None

    @mode.setter
    def mode(self, value: str | None) -> None:
        self._backing["mode"] = value

    def set_flag(self, name: str, active: bool) -> None:
        self._backing[name] = bool(active)

    def reset_keys(self, *keys: str) -> None:
        for key in keys:
            self._backing[key] = None

    def as_dict(self) -> dict[str, Any]:  # pragma: no cover - convenience helper
        return dict(self._backing)


__all__ = ["StorySessionProxy"]

