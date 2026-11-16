#!/usr/bin/env python3

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

    for name in ("FIRECRAWL_API_KEY",):
        v = os.environ.get(name)
        if v:
            out[name] = v
    p = pathlib.Path(_ENV_FILE)
    try:
        if p.exists():
            mode = stat.S_IMODE(p.stat().st_mode)
            if mode & 0o077:


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

    return _load().get(name, "")


def has(name: str) -> bool:

    return bool(_load().get(name))


def redact(text: str) -> str:

    out = text
    for k, v in _load().items():
        if v and v in out:
            out = out.replace(v, f"[{k.lower()}-redacted]")
    return out