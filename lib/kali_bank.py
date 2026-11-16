#!/usr/bin/env python3
"""kali_bank — read-only query tool over the Kali playbook command bank.

Source of truth: ~/Desktop/kaliplaybook/cortexagent-commands.json
(847 Kali tools / 2,078 documented lab-only command forms, every form a
{cmd, vars, source, risk} record with {{VAR}} slip-in slots; the kaliplaybook
build_site.py script maintains the file).

Answers lookups by tool name / slug / purpose / command text / phase / slot
token and returns exact preconfigured command forms the agent can slip
variables into. Lab-only content: the bank itself carries the framing.

Path can be overridden with the KALI_BANK_FILE environment variable.
Registration happens in lib/tool_registry.py (registered_tool, trust=high).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_BANK = Path.home() / "Desktop" / "kaliplaybook" / "cortexagent-commands.json"

_CACHE = {"loaded": None}


def _bank():
    """Load and cache the bank JSON (re-reads only if the file changed)."""
    path = Path(os.environ.get("KALI_BANK_FILE", str(DEFAULT_BANK)))
    if not path.exists():
        raise FileNotFoundError(
            "cortexagent-commands.json not found — "
            "run the kaliplaybook bank build step first")
    stamp = (str(path), path.stat().st_mtime, path.stat().st_size)
    if _CACHE["loaded"] and _CACHE["loaded"][0] == stamp:
        return _CACHE["loaded"][1]
    data = json.loads(path.read_text())
    tools = data.get("tools", [])
    grammar = data.get("placeholder_grammar", {})
    index = {"path": path, "generated": data.get("generated", ""),
             "lab_only": data.get("lab_only", ""),
             "usage": data.get("usage_for_cortexagent", ""),
             "tools": tools, "grammar": grammar,
             "phases": {}, "slots": {}}
    for t in tools:
        ph = str(t.get("phase", "?"))
        index["phases"].setdefault(ph, []).append(t)
        for c in t.get("commands", []):
            for v in c.get("vars", []) or []:
                index["slots"].setdefault(v, 0)
                index["slots"][v] += 1
    _CACHE["loaded"] = (stamp, index)
    return index


def _matches(tool, text):
    """Case-insensitive substring hit anywhere in a record's text."""
    return bool(re.search(re.escape(text), tool, re.I))


def bank_query(query: str = "", tool: str = "", phase: str = "", slot: str = "",
               limit: int = 6) -> dict:
    """Query the bank. Any of: free-text query, tool name/slug, phase, slot token."""
    try:
        idx = _bank()
    except Exception as e:
        return {"ok": False, "output": "", "error": f"kali_bank load failed: {e}"}

    limit = max(1, min(int(limit or 6), 12))
    out = []

    # slot token lookup: what does {{IP}} mean, and where does it appear?
    if slot or (query and re.fullmatch(r"\{\{\s*\w+\s*\}\}", query.strip())):
        tok = re.sub(r"[{} ]", "", slot or query).strip()
        g = idx["grammar"].get(tok, "")
        if not g:
            known = sorted(idx["grammar"])
            return {"ok": True, "output": (
                f"no slot named {tok!r}. Known slots: "
                + ", ".join("{{" + k + "}}" for k in known)
            ), "error": ""}
        uses = [t["name"] for t in idx["tools"]
                for c in t.get("commands", []) if tok in (c.get("vars", []) or [])]
        out.append(f"slot {{{{{tok}}}}} = {g}")
        out.append(f"appears in {len(uses)} command forms, e.g."
                   f" {' · '.join(sorted(set(uses))[:5]) or 'n/a'}")
        return {"ok": True, "output": "\n".join(out), "error": ""}

    # phase overview
    if phase != "":
        ph = str(phase)
        tools = idx["phases"].get(ph)
        if not tools:
            return {"ok": False, "output": "",
                    "error": f"no phase {ph!r} (phases 0-9)"}
        forms = sum(len(t.get("commands", [])) for t in tools)
        out.append(f"phase {ph}: {len(tools)} tools · {forms} command forms")
        for t in tools[:limit]:
            out.append(f"  {t['name']} (slug {t['slug']}) · {t.get('install','?')} · "
                       f"{len(t.get('commands', []))} forms")
        out.append("→ kali_bank(tool='<name>') pulls a tool's exact forms")
        return {"ok": True, "output": "\n".join(out), "error": ""}

    # tool-directed lookup
    if tool:
        hits = [t for t in idx["tools"] if _matches(t["name"], tool)
                or _matches(t["slug"], tool)]
        if not hits:
            return {"ok": False, "output": "",
                    "error": f"no bank tool matches {tool!r}"}
        rank = sorted(hits, key=lambda t: (
            t["name"].lower() != tool.lower() and t["slug"] != tool.lower(),
            t["name"].lower().find(tool.lower()) if t["name"].lower().find(tool.lower()) >= 0 else 99,
            len(t["name"])))
        for t in rank[:1]:
            out.append(_render_tool(t, limit))
        if len(rank) > 1:
            out.append(f"also matches: {' · '.join(t['name'] for t in rank[1:6])}")
        return {"ok": True, "output": "\n".join(out), "error": ""}

    # free-text query over names, purposes, commands, slugs
    q = (query or "").strip()
    if not q:
        nt, nc = len(idx["tools"]), sum(len(t.get("commands", [])) for t in idx["tools"])
        slots_note = ("{len} slip-in slots: ".format(len=len(idx["grammar"]))
                      + ", ".join("{{" + k + "}}" for k in sorted(idx["grammar"])))
        return {"ok": True, "output": (
            f"Kali command bank · generated {idx['generated'] or 'unknown'} · LAB-ONLY\n"
            f"{nt} tools · {nc} documented command forms · {slots_note}\n"
            "Usage: kali_bank(query='handshake capture') · kali_bank(tool='airodump-ng') · "
            "kali_bank(phase='9') · kali_bank(slot='IP')"), "error": ""}

    scored = []
    for t in idx["tools"]:
        best = None
        if _matches(t["name"], q) or _matches(t["slug"], q):
            best = 0
        elif _matches(t.get("purpose", ""), q):
            best = 1
        else:
            for c in t.get("commands", []):
                if _matches(c["cmd"], q) or _matches(c.get("title", ""), q):
                    best = 2
                    break
        if best is not None:
            scored.append((best, t["name"].lower().count(q), len(scored), t))
    if not scored:
        return {"ok": False, "output": "",
                "error": (f"no bank match for {q!r} — try kali_bank(phase='0'..'9'), "
                          "kali_bank(tool='name'), or kali_bank(slot='TOKEN')")}
    scored.sort(key=lambda x: (x[0], -x[1]))
    out.append(f"matches for {q!r}: {len(scored)} (top {limit})")
    for _, _, _, t in scored[:limit]:
        n = len(t.get("commands", []))
        out.append(f"  {t['name']} (slug {t['slug']}) · phase {t['phase']} · "
                   f"{t.get('install','?')} · {n} form{'s' if n != 1 else ''}")
        out.append("    " + (t.get("purpose", "") or "")[:110])
    out.append("→ kali_bank(tool='<name>') returns each exact form + slots + source")
    return {"ok": True, "output": "\n".join(out), "error": ""}


def _tool_slots(tool):
    n = {}
    for c in tool.get("commands", []):
        for v in c.get("vars", []) or []:
            n[v] = n.get(v, 0) + 1
    return n


def _render_tool(t, limit):
    rows = [f"{t['name']} (slug: {t['slug']}) · phase {t['phase']} · "
            f"install: {t.get('install', '?')}",
            f"purpose: {t.get('purpose', '')}"]
    forms = t.get("commands", [])
    shown = forms[:limit]
    for i, c in enumerate(shown, 1):
        rows.append(f"[{i}] {c.get('title','')}")
        for ln in c["cmd"].split("\n"):
            rows.append(f"    $ {ln}")
        if c.get("vars"):
            rows.append("    slots: " + ", ".join("{{" + v + "}}" for v in c["vars"]))
        if c.get("source"):
            rows.append(f"    source: {c['source']}")
        if c.get("risk"):
            rows.append(f"    risk: {c['risk']}")
    if len(forms) > len(shown):
        rows.append(f"… {len(forms) - len(shown)} more forms — raise limit (max 12) "
                    f"or query the tool page in the playbook")
    return "\n".join(rows)