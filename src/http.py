"""HTTP session: works on public internet; proxy only if you ask for it."""

from __future__ import annotations

import os
from typing import Optional

import requests
import urllib3

from src.config import USER_AGENT

_proxy: Optional[str] = None
_verify_ssl: bool = True


def _env_proxy() -> Optional[str]:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NRSC_PROXY_URL"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def _env_verify() -> bool:
    raw = os.environ.get("ICESAT2_SSL_VERIFY", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def configure(proxy: Optional[str] = None, verify_ssl: Optional[bool] = None) -> None:
    """Call once per Streamlit rerun from the sidebar / env."""
    global _proxy, _verify_ssl
    sidebar_proxy = (proxy or "").strip() or None
    _proxy = sidebar_proxy or _env_proxy()
    _verify_ssl = _env_verify() if verify_ssl is None else bool(verify_ssl)
    if not _verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def current_settings() -> dict:
    return {"proxy": _proxy, "verify_ssl": _verify_ssl}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    s.verify = _verify_ssl
    if _proxy:
        s.proxies = {"http": _proxy, "https": _proxy}
    return s


def ping(url: str, timeout: int = 12) -> tuple[bool, str]:
    try:
        r = make_session().get(url, timeout=timeout)
        ok = r.status_code < 400
        return ok, f"{r.status_code}"
    except Exception as exc:
        return False, str(exc)[:120]
