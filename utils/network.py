"""Network and request related helper functions."""
from __future__ import annotations

from typing import Optional


def get_client_ip() -> Optional[str]:
    """Best-effort extraction of the visitor's IP address from Streamlit context."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if not ctx:
            return None
        headers = getattr(ctx, "request_headers", None)
        if not headers:
            return None

        forwarded_for = headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        for header_key in ("X-Real-IP", "CF-Connecting-IP", "Remote-Addr"):
            candidate = headers.get(header_key)
            if candidate:
                return candidate.strip()
    except Exception:
        return None
    return None


def mask_client_ip(client_ip: Optional[str]) -> str:
    """Obscure parts of an IP address so it can be displayed safely."""
    if not client_ip:
        return "unknown"
    ip = client_ip.strip()
    if not ip:
        return "unknown"
    if ":" in ip:  # IPv6
        ip_no_scope = ip.split("%", 1)[0]
        groups = [group for group in ip_no_scope.split(":") if group]
        if len(groups) >= 3:
            return ":".join(groups[:3]) + ":*:*"
        return ip_no_scope
    parts = ip.split(".")
    if len(parts) >= 4:
        return ".".join(parts[:2]) + ".*.*"
    if len(parts) == 3:
        return ".".join(parts[:1]) + ".*.*.*"
    return ip


__all__ = ["get_client_ip", "mask_client_ip"]
