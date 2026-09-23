#!/usr/bin/env python3
"""research/keys.py — local-only API key loader.

Keys live in ~/.cortexagent/research/.env (chmod 600). They are read ONCE at
import into a module-private dict and are NEVER returned to callers as raw
values except via get(name) for use in outbound HTTP headers inside this
package. No tool result, log line, or error message may include a key.
"""
import os
import pathlib
import stat

_ENV_FILE = os.path.join(os.path.expanduser("~"), ".cortexagent", "research", ".env")
_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    out: dict[str, str] = {}
    # environment first (explicit), file second
    for name in ("FIRECRAWL_API_KEY",):
        v = os.environ.get(name)
        if v:
            out[name] = v
    p = pathlib.Path(_ENV_FILE)
    try:
        if p.exists():
            mode = stat.S_IMODE(p.stat().st_mode)
            if mode & 0o077:
                # world/group readable key file is a misconfiguration — refuse
                # to use it rather than silently treat secrets as unprotected.
                raise PermissionError(f"{p} must be chmod 600 (is {oct(mode)})")
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                out.setdefault(k.strip(), v.strip())
    except PermissionError:
        raise
    except OSError:
        pass
    _cache = out
    return out


def get(name: str) -> str:
    """Return the key value for outbound use inside this package only."""
    return _load().get(name, "")


def has(name: str) -> bool:
    """Boolean availability — safe to expose in tool results."""
    return bool(_load().get(name))


def redact(text: str) -> str:
    """Scrub every known key value out of arbitrary text (defense in depth)."""
    out = text
    for k, v in _load().items():
        if v and v in out:
            out = out.replace(v, f"[{k.lower()}-redacted]")
    return out