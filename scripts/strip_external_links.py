#!/usr/bin/env python3
"""strip_external_links.py — remove external-AI endpoints/links from text sources.

TWO MODES:
  * no --root (cortexagent's own tree): report/strip only the owner audit
    engine's ENDPOINTS regex (known AI vendors, telemetry collectors).
  * --root=<tree> (INGEST mode, used by convert_mcp_to_so.py): STRICT
    allowlist gate — every URL in the ingested tree that is not localhost/
    private-lan is commented out, vendor-known or not. An unknown domain is
    not "safe", it is unaudited; the pipeline refuses to ship unaudited
    outbound addresses inside a .so.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build" / "src"))

import audit as owner_audit  # noqa: E402  (ENDPOINTS is the law here)

APPLY = "--apply" in sys.argv
ROOT_OVERRIDE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--root=")), None)
# caller-declared legit domains for INGEST mode (--allow=arch.org,more.com):
# exact host or any subdomain-of match. Everything else still gets stripped.
_EXTRAS = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--allow=")), "")
_ALLOWED = tuple(h.strip().lower() for h in _EXTRAS.split(",") if h.strip())
SCAN_DIRS = ["build/src", "scripts", "core", "tools", "services", "tui/packages/coding-agent/dist"]

# Ingest allowlist: what an ingested tool is allowed to keep pointing at.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]")
_URL = __import__("re").compile(r"https?://[^\s'\"<>]+")


def _strict_hits(ln: str) -> bool:
    for m in _URL.finditer(ln):
        host = m.group(0).split("://", 1)[1].rstrip("/,;)]}'\"").split("/")[0].split(":")[0]
        if host in _LOCAL_HOSTS:
            continue
        hl = host.lower()
        if any(hl == a or (hl.endswith("." + a) and len(hl) > len(a)) for a in _ALLOWED):
            continue
        return True  # any non-local, non-declared host is unaudited → strip
    return False


def main() -> int:
    hits = []
    for d in (["."] if ROOT_OVERRIDE else SCAN_DIRS):
        base = Path(ROOT_OVERRIDE) if ROOT_OVERRIDE else (ROOT / d)
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if p.name in owner_audit.SKIP_FILES:
                continue
            try:
                rel = str(p.relative_to(ROOT))
                if any(rel.startswith(s) or ("/" + s + "/") in rel
                       for s in owner_audit.SKIP_DIRS):
                    continue
            except ValueError:
                rel = str(p.resolve())  # external --root tree: keep the full path
                if not rel:
                    continue
            try:
                lines = p.read_text(errors="ignore").splitlines(keepends=True)
            except OSError:
                continue
            joined = "".join(lines)
            if "strip_external_links" in joined and "ENDPOINTS" in joined:
                continue  # this script itself
            if ROOT_OVERRIDE:
                matcher = _strict_hits  # ingest: allowlist-only, unknown domains are guilty
            else:
                matcher = owner_audit.ENDPOINTS.search  # home tree: known-vendor engine
            out, changed = [], []
            for i, ln in enumerate(lines, 1):
                if matcher(ln):
                    changed.append(f"{rel}:{i}")
                    # ingest mode: replace with same-indent `pass` (deleting or
                    # commenting inside a block leaves an empty body SyntaxError)
                    if ROOT_OVERRIDE:
                        indent = ln[:len(ln) - len(ln.lstrip())]
                        out.append("# [stripped external endpoint] " + indent + "pass\n")
                    else:
                        out.append("# [stripped external endpoint] " + ln)
                    continue
                out.append(ln)
            if changed and not APPLY:
                print("EXTERNAL-ENDPOINT-HIT (report-only):", *changed, sep="\n  ")
            if changed and APPLY:
                p.with_suffix(p.suffix + ".orig").write_text("".join(lines))
                p.write_text("".join(out))
                hits += changed
    if APPLY:
        print(f"commented out {len(hits)} external-endpoint lines; .orig backups kept")
        return 0
    print("external-link scan done (report-only; rerun with --apply to strip)")
    return 0


if __name__ == "__main__":
    sys.exit(main())