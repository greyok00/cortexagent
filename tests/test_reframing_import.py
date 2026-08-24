
import importlib.util
import subprocess
import sys
from pathlib import Path

ENGINE = Path.home() / "reframing-engine" / "reframing_engine.py"


def _load_engine():
    if not ENGINE.is_file():
        import pytest
        pytest.skip("~/reframing-engine/reframing_engine.py not present")


    if str(ENGINE.parent) not in sys.path:
        sys.path.insert(0, str(ENGINE.parent))
    spec = importlib.util.spec_from_file_location("reframing_engine", ENGINE)
    mod = importlib.util.module_from_spec(spec)



    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_cortexagent_can_import_engine():
    mod = _load_engine()
    r = mod.reframe("fix the bug in the auth flow")
    assert r.domain == "code"
    assert "the bug in the auth flow" in r.cleaned
    assert r.sources == []


def test_engine_source_has_no_runtime_imports():

    src = ENGINE.read_text()
    forbidden = (
        "import cortex", "from cortex",
        "import cortexllm", "from cortexllm",
        "import session_bridge", "import memory_thin",
    )
    assert not any(f in src for f in forbidden), \
        "engine must not import agent runtimes"
