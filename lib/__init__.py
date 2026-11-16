"""lib package

The optional web-research integration (greysearch) lives in its own external
checkout. This module keeps the import path for its modules stable: the
checkout root is added to ``sys.path`` so its modules can be imported by
top-level name (research, browser_session, ...) when the checkout is present.
"""

import os as _os
import sys as _sys

def _greysearch_home() -> str:
    """Root of the external greysearch checkout, if one is configured."""
    root = _os.environ.get(
        "CORTEXAGENT_GREYSEARCH_MCP", _os.path.join("~", "greysearch"))
    return _os.path.expanduser(root.rstrip("/"))

_GREYSEARCH_HOME = _greysearch_home()
if _GREYSEARCH_HOME and _GREYSEARCH_HOME not in _sys.path:
    _sys.path.insert(0, _GREYSEARCH_HOME)


def slimtoken_module(name: str):
    """Import an optional submodule of the external slimtoken package.

    The slimtoken distribution registers its compiled ``memory.engine``
    extension under the bare top-level name ``engine``, which would shadow
    this project's ``engine`` package for every later import. Importing
    through this helper repairs the namespace after the fact.
    """
    import importlib
    import sys

    module = importlib.import_module(name)
    poisoned = sys.modules.get("engine")
    if poisoned is not None and not hasattr(poisoned, "__path__"):
        del sys.modules["engine"]
        for key in [k for k in sys.modules if k.startswith("engine.")]:
            victim = sys.modules[key]
            if "slimtoken" in str(getattr(victim, "__file__", "")):
                del sys.modules[key]
    return module
