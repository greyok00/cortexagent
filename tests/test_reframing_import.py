import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import prompt_reframe  # noqa: E402


def test_reframe_prompt_cleans_a_messy_prompt():
    cleaned = prompt_reframe.reframe_prompt("hey could you maybe summarize paragraph three of that report")
    assert "summarize paragraph three of that report" in cleaned
    assert cleaned.count("\n") <= 1


def test_reframe_prompt_keeps_the_action():
    cleaned = prompt_reframe.reframe_prompt("fix the bug in the auth flow")
    assert "Fix the bug in the auth flow." in cleaned


def test_classify_domain_maps_a_code_prompt():
    assert prompt_reframe.classify_domain("fix the bug in the auth flow") == "coding"


def test_source_has_no_runtime_imports():
    src = (Path(__file__).resolve().parents[1] / "lib" / "prompt_reframe.py").read_text()
    forbidden = (
        "import cortex", "from cortex",
        "import cortexllm", "from cortexllm",
        "import session_bridge", "import memory_thin",
    )
    assert not any(f in src for f in forbidden), "reframing engine must not import agent runtimes"