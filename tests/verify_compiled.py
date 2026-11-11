import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODULES = [
    "core.state", "core.llm", "core.registry", "core.subagent",
    "tools.adapters_base", "tools.adapters_searxng", "tools.adapters_registry",
    "tools.browser_control", "tools.browser_tools", "tools.browser_console",
    "tools.browser_session", "tools.browser_ports", "tools.browser_cdp_guard",
    "tools.patchright_scraper", "tools.searxng_integrated", "tools.searx_fallback",
    "tools.page_clean", "tools.relevance", "tools.guide_scrub",
    "tools.research_injection", "tools.kali_bank", "tools.charts",
    "tools.document_adapter", "tools.pdf_knowledge", "tools.fast_extract",
    "tools.popup_themes", "tools.stealth.profiles", "tools.stealth.init_script",
    "services.memory_thin", "services.memory_daemon",
    "services.scheduler_store", "services.scheduler_recovery",
    "services.scheduler_ui", "model.prompt", "model.server", "ui.splash",
    "tools.files", "tools.search",
]

bad = []
for m in MODULES:
    try:
        mod = importlib.import_module(m)
        file = getattr(mod, "__file__", "") or ""
        if file.endswith(".py"):
            bad.append((m, "loaded from .py: " + file))
    except Exception as e:
        bad.append((m, repr(e)[:100]))

print("compiled:", "PASS" if not bad else "FAIL")
for b in bad:
    print(" ", b)
sys.exit(0 if not bad else 1)