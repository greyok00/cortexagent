import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_files_roundtrip(tmp_path):
    from tools.files import write_file, read_file, edit_file, list_dir
    f = tmp_path / "x.txt"
    w = write_file(str(f), "alpha beta")
    assert w["ok"]
    r = read_file(str(f))
    assert r["ok"] and r["output"] == "alpha beta"
    e = edit_file(str(f), "beta", "gamma")
    assert e["ok"]
    assert read_file(str(f))["output"] == "alpha gamma"
    assert list_dir(str(tmp_path))["ok"]


def test_files_rejects_missing():
    from tools.files import read_file
    assert not read_file("/no/such/file/here")["ok"]


def test_search_glob_and_grep(tmp_path):
    from tools.search import glob, grep
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
    (tmp_path / "b.txt").write_text("beta line\n")
    g = glob("*.py", base=str(tmp_path))
    assert g["ok"] and "a.py" in g["output"]
    gr = grep("beta", base=str(tmp_path))
    assert gr["ok"] and "b.txt" in gr["output"]


def test_shell_runs():
    from core.registry import _run_command
    r = _run_command("echo hi")
    assert r["ok"] and "hi" in r["output"]


def test_shell_timeout():
    from core.registry import _run_command
    r = _run_command("sleep 5", timeout=1)
    assert not r["ok"] and "timed out" in r["error"]


def test_wiring_all_registered():
    import core.wiring as w
    w._state["done"] = False
    n = w.register_all()
    assert n >= 25
    from core.registry import execute_tool, TOOLS
    assert execute_tool("files_list", {"path": "."})["ok"]
    assert "web_search" in TOOLS and "vision" in TOOLS and "kali_bank" in TOOLS


def test_parse_document_smoke():
    from tools.document_adapter import parse_document
    r = parse_document("/no/such/doc.pdf")
    assert isinstance(r, dict) and "ok" in r


def test_system_status_tool():
    import core.wiring as w
    w._state["done"] = False
    w.register_all()
    from core.registry import execute_tool
    r = execute_tool("system", {})
    assert r["ok"]