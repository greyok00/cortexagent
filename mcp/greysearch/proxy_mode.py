#!/usr/bin/env python3
"""proxy_mode.py - the manual search-proxy contract.

SEARCHES ride the proxy only when the mode says so; page scrapes never do,
in any mode. Credentials come ONLY from the operator-managed env file at
~/.config/greysearch/proxy.env (keys HTTP_PROXY/HTTPS_PROXY). Those values
stay in memory: they are never logged, echoed, printed, or written into run
records, ladders, or guides.

Modes: "off" (default: searches explicitly bypass ambient HTTP(S)_PROXY via
a per-call ProxyHandler({})), "on" (external search lanes ride the proxy).
An explicitly requested mode that cannot be honored is reported as a
structured error (ok is False with an error code), never silently re-routed
direct.
"""
from __future__ import annotations

import os
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

ENV_FILE = os.path.join(os.path.expanduser("~"),
                        ".config", "greysearch", "proxy.env")
ENV_OVERRIDE = "GREYSEARCH_SEARCH_PROXY"
ALIASES: dict = {}
VALID_MODES = ("off", "on")
DEFAULT_MODE = "off"
MISSING_ENVFILE = "MISSING_ENVFILE"
NO_PROXY_VALUES = "NO_PROXY_VALUES"
BAD_MODE = "BAD_MODE"
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY")
SCRAPE_GUARD = "scrape direct (no proxy)"
OFF_LADDER_NOTE = "proxy mode off: direct"
ON_LADDER_NOTE = ("search proxy: on "
                  "(external search lanes ride the proxy)")
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
_ENV_FILE_TILDE = "~/.config/greysearch/proxy.env"


class ProxyModeError(RuntimeError):
    """Raised by search transports when a requested proxy mode cannot be
    honored (env file missing or unusable). The message is the error code
    only, never a credential value."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


def normalized_mode(mode: Any) -> Optional[str]:
    """Validate one mode candidate. Returns None for 'no preference'
    (unset/empty/whitespace), or "off"/"on". Raises ValueError for any
    other value, so callers cannot accept a typo silently."""
    if mode is None:
        return None
    name = str(mode).strip().lower()
    if not name:
        return None
    name = ALIASES.get(name, name)
    if name not in VALID_MODES:
        raise ValueError(
            "unknown search_proxy mode %r (accepted: off, on)"
            % str(name)[:20])
    return name


def resolve_proxy_mode(mode: Any = None,
                       env_file: Optional[str] = None) -> Dict[str, Any]:
    """Resolve the search-proxy mode into one structured record.

    {"ok": True, "mode": "off", "proxy": None, ...} for off,
    {"ok": True, "mode": "on", "proxy": {"http": ..., "https": ...},
     ...} when the env file carried credentials, or
    {"ok": False, "mode": "on", "proxy": None,
     "error": "MISSING_ENVFILE" | "NO_PROXY_VALUES", ...} when on was
    requested but the operator-managed env file cannot serve credentials.

    Precedence: the GREYSEARCH_SEARCH_PROXY environment variable wins when
    it is set; otherwise the explicit mode argument; otherwise "off".
    The env-file path is overridable for tests only."""
    env_val = (os.environ.get(ENV_OVERRIDE) or "").strip()
    if env_val:
        mode = env_val
    name = normalized_mode(mode)
    if name is None:
        name = DEFAULT_MODE
    path = env_file or ENV_FILE
    if name == "off":
        return {"ok": True, "mode": "off", "proxy": None,
                "error": "", "env_file": path}
    creds = _load_env_file(path)
    if creds:
        return {"ok": True, "mode": "on", "proxy": creds,
                "error": "", "env_file": path}
    code = MISSING_ENVFILE if not os.path.isfile(path) else NO_PROXY_VALUES
    return {"ok": False, "mode": "on", "proxy": None,
            "error": code, "env_file": path}


def _load_env_file(path: str) -> Optional[Dict[str, str]]:
    """HTTP_PROXY/HTTPS_PROXY values from the operator-managed env file, or
    None when
    the file is absent, unreadable, or carries no proxy values. Values are
    returned to the caller in memory only; this module has no logging."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except Exception:
        return None
    values: Dict[str, str] = {}
    for raw in lines:
        line = str(raw or "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    https = values.get("HTTPS_PROXY") or values.get("https_proxy") or ""
    http = values.get("HTTP_PROXY") or values.get("http_proxy") or ""
    if not (https or http):
        return None
    return {"http": http or https, "https": https or http}


def prepared(mode: Any = None) -> Dict[str, Any]:
    """Mode record for the transport paths: a mode string resolves through
    resolve_proxy_mode (unknown values land as BAD_MODE records instead of
    raising; the calling surfaces validate their own input), and a
    previously resolved record passes through unchanged so every lane of
    one search agrees on one resolution."""
    if isinstance(mode, dict):
        return dict(mode)
    try:
        return resolve_proxy_mode(mode)
    except ValueError as exc:
        return {"ok": False, "mode": "", "proxy": None,
                "error": BAD_MODE, "detail": str(exc)[:80]}


def ladder_note(res: Optional[Dict[str, Any]]) -> str:
    """The ladder line for one mode resolution. Never carries credential
    values, and never the absolute env-file path (the tilde form keeps the
    user name out of run records)."""
    if not res:
        return "search proxy: mode not resolved (searches run direct)"
    if res.get("ok"):
        if res.get("mode") == "on":
            return ON_LADDER_NOTE
        return OFF_LADDER_NOTE
    code = str(res.get("error") or "")
    if code == NO_PROXY_VALUES:
        return ("search proxy: on requested but no "
                "HTTP_PROXY/HTTPS_PROXY values in the env file "
                "(NO_PROXY_VALUES): external search lanes held back")
    if code == MISSING_ENVFILE:
        return ("search proxy: on requested but the env file is missing "
                "(MISSING_ENVFILE, %s): external search lanes held back"
                % _ENV_FILE_TILDE)
    return ("search proxy: unavailable (%s): external search lanes held back"
            % (code or "unknown"))


def scrape_guard_note() -> str:
    return SCRAPE_GUARD


def build_search_opener(mode: Any = None,
                        env_file: Optional[str] = None
                        ) -> urllib.request.OpenerDirector:
    """One fresh opener for ONE search call: ProxyHandler(creds) when the
    mode is on, ProxyHandler({}) when off (so ambient HTTP(S)_PROXY from a
    service environment is explicitly bypassed). Raises ProxyModeError when
    an on-mode request cannot be served, instead of falling back to direct."""
    res = prepared(mode)
    if not res.get("ok"):
        raise ProxyModeError(str(res.get("error") or BAD_MODE))
    if res.get("proxy"):
        return urllib.request.build_opener(
            urllib.request.ProxyHandler(res["proxy"]))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def is_loopback_url(url: Any) -> bool:
    """True for the loopback SearXNG lane (always direct, transport never
    changes, whatever the mode says)."""
    try:
        netloc = urllib.parse.urlsplit(str(url or "")).netloc.lower()
        host = netloc.rsplit("@", 1)[-1].split("]", 1)[0]
        host = host.strip("[").strip("]")
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        stripped = host.replace("]", "").replace("[", "")
        return stripped in _LOCAL_HOSTS or stripped.endswith(".localhost")
    except Exception:
        return False


def open_search(url: str, timeout: float = 15, mode: Any = None,
                env_file: Optional[str] = None,
                headers: Optional[Dict[str, str]] = None,
                data: Optional[bytes] = None) -> Any:
    """One SEARCH transport hop. Loopback URLs never change transport (the
    plain default opener, protected by NO_PROXY). External URLs build their
    own opener per call: ProxyHandler(creds) when on, ProxyHandler({}) when
    off. ProxyModeError escapes when an on-mode request cannot be served, so
    the surrounding lane can record the structured error instead of falling
    back to direct."""
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    if is_loopback_url(url):
        return urllib.request.urlopen(req, timeout=timeout)
    opener = build_search_opener(prepared(mode), env_file=env_file)
    return opener.open(req, timeout=timeout)
