import json
import pathlib
import re
import subprocess
import sys

BANNED = ["cor" + "tex", "cor" + "texagent", "openai", "anthropic", "amazon",
          "microsoft", "apple", "gemini"]

ENDPOINTS = re.compile(r"api\.openai\.com|api\.anthropic\.com|amazonaws\.com|"
                       r"\.microsoft(online)?\.com|gemini\.google|"
                       r"generativelanguage\.googleapis|apple\.com/api|"
                       r"claude\.ai|chatgpt\.com|openrouter\.ai", re.I)

TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".cfg", ".yaml",
                 ".yml", ".sh", ".html", ".css", ".js"}

SKIP_FILES = {"audit.py", "manifest.md", "audit-last.json"}

SKIP_DIRS = {"build", "__pycache__", ".git", "state/audit",
             "slimtoken/tests", "slimtoken/bench",
             "slimtoken/src/slimtoken/mcp_server"}

FILTER_CONTEXT = re.compile(
    r"\.(com|net|io|microsoft|apple|amazon)\b|safari|macos|windows|"
    r"\bua\b|user-agent|domain|suffix|instance|searx|webgl|renderer|"
    r"angle|\||promo|threat", re.I)


def _skipped(p: pathlib.Path, root: pathlib.Path) -> bool:
    rel = str(p.relative_to(root))
    if any(rel.startswith(d) or ("/" + d + "/") in ("/" + rel) for d in SKIP_DIRS):
        return True
    if p.name in SKIP_FILES:
        return True
    return p.name.startswith("audit-")


def _scan_text(root):
    pattern = [re.compile(r"\b" + re.escape(b) + r"\b", re.I) for b in BANNED]
    hits, filters, endpoints = [], [], []
    for p in sorted(pathlib.Path(root).rglob("*")):
        if not p.is_file() or _skipped(p, pathlib.Path(root)):
            continue
        if p.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        content_mode = "assets" in p.parts
        for rex in pattern:
            for m in rex.finditer(text):
                word = m.group().lower()
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                line = text[line_start:line_end if line_end > -1 else len(text)]
                rec = "%s:%d: %s" % (p, text[:m.start()].count("\n") + 1, m.group())
                if "cor" in word:
                    hits.append(rec)
                elif content_mode or FILTER_CONTEXT.search(line):
                    filters.append(rec)
                else:
                    hits.append(rec)
        for m in ENDPOINTS.finditer(text):
            endpoints.append("%s:%d: %s" % (p, text[:m.start()].count("\n") + 1,
                                            m.group()))
    return hits, filters, endpoints


def _scan_binaries(root):
    hits = []
    words = "|".join(re.escape(b) for b in BANNED)
    rex = re.compile(r"\b(" + words + r")\b", re.I)
    for p in pathlib.Path(root).rglob("*.so"):
        try:
            out = subprocess.run(["strings", str(p)], capture_output=True,
                                 text=True, timeout=120).stdout
        except Exception:
            continue
        for m in rex.finditer(out):
            hits.append("%s(strings): %s" % (p, m.group()))
    return hits


def _scan_vendor_binaries(root):
    endpoints = []
    for p in pathlib.Path(root).rglob("*.so"):
        try:
            out = subprocess.run(["strings", str(p)], capture_output=True,
                                 text=True, timeout=120).stdout
        except Exception:
            continue
        for m in ENDPOINTS.finditer(out):
            endpoints.append("%s(strings): %s" % (p, m.group()))
    return endpoints


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    textmode = "--text-only" in sys.argv
    hits, filters, endpoints = _scan_text(root)
    if not textmode:
        hits += _scan_binaries(root)
        endpoints += _scan_vendor_binaries(root)
    report = {"fail": sorted(hits), "filter_strings": sorted(filters),
              "provider_endpoints": sorted(endpoints)}
    outp = pathlib.Path(root) / "state" / "audit" / "audit-last.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(report, indent=1))
    if hits or endpoints:
        print(json.dumps(report, indent=1))
        return 1
    print("CLEAN (%d functional filter strings documented)" % len(filters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
