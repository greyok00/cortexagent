#!/usr/bin/env python3


from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRAPER = ROOT / "lib" / "scraper"
for p in (str(ROOT), str(SCRAPER)):
    if p not in sys.path:
        sys.path.insert(0, p)

pytest.importorskip("intern_model", reason="external intern_model module not installed")
import intern_model  # noqa: E402
import relevance  # noqa: E402
import guide_distill  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):

    monkeypatch.delenv("CORTEX_INTERN_MODEL", raising=False)
    monkeypatch.delenv("CORTEX_INTERN_PREFERENCE", raising=False)
    intern_model._clear_cache()
    yield
    intern_model._clear_cache()






def test_env_override_wins_even_when_models_exist(monkeypatch):
    monkeypatch.setenv("CORTEX_INTERN_MODEL", "operator-pick:cloud")

    def _must_not_be_called(*a, **k):
        raise AssertionError("endpoint must not be queried when override is set")

    monkeypatch.setattr(intern_model, "available_models", _must_not_be_called)
    assert intern_model.resolve_intern_model() == "operator-pick:cloud"


def test_chooses_an_available_cloud_model_not_a_hardcoded_one(monkeypatch):

    monkeypatch.setattr(intern_model, "available_models",
                        lambda *a, **k: ["tinyllama:latest", "acme-intern:cloud"])
    chosen = intern_model.resolve_intern_model()
    assert chosen == "acme-intern:cloud"

    assert chosen not in intern_model._DEFAULT_PREFERENCE


def test_falls_back_to_non_cloud_when_it_is_all_that_exists(monkeypatch):
    monkeypatch.setattr(intern_model, "available_models",
                        lambda *a, **k: ["llama3.1:8b"])
    assert intern_model.resolve_intern_model() == "llama3.1:8b"


def test_empty_model_list_raises_actionable_runtimeerror(monkeypatch):
    monkeypatch.setattr(intern_model, "available_models", lambda *a, **k: [])
    with pytest.raises(RuntimeError) as exc:
        intern_model.resolve_intern_model()
    msg = str(exc.value)
    assert "CORTEX_INTERN_MODEL" in msg
    assert "ollama" in msg or "11600" in msg


def test_result_is_cached_until_forced(monkeypatch):
    calls = []

    def _tags(*a, **k):
        calls.append(1)
        return ["acme-intern:cloud"]

    monkeypatch.setattr(intern_model, "available_models", _tags)
    assert intern_model.resolve_intern_model() == "acme-intern:cloud"
    assert intern_model.resolve_intern_model() == "acme-intern:cloud"
    assert len(calls) == 1
    assert intern_model.resolve_intern_model(force=True) == "acme-intern:cloud"
    assert len(calls) == 2


def test_available_models_parses_api_tags(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"models": [
                {"name": "acme-intern:cloud", "model": "acme-intern:cloud"},
                {"name": "llama3.1:8b"},
            ]}).encode()

    monkeypatch.setattr(intern_model.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp())
    assert intern_model.available_models("http://127.0.0.1:11600") == [
        "acme-intern:cloud", "llama3.1:8b"]






def test_judge_refreshes_and_retries_once_on_model_not_found(monkeypatch):
    resolves = []
    posts = []

    def _resolve(force=False):
        resolves.append(force)
        return "new-model:cloud" if force else "stale-model:cloud"

    def _post(payload, *a, **k):
        posts.append(json.loads(json.dumps(payload)))
        if len(posts) == 1:
            return ('{"error":"model \'stale-model:cloud\' not found"}', 404)
        return (json.dumps({"message": {"content": "judge-ok"}}), 200)

    monkeypatch.setattr(relevance, "resolve_intern_model", _resolve)
    monkeypatch.setattr(relevance, "post_chat", _post)

    assert relevance._call_intern("prompt") == "judge-ok"
    assert resolves == [False, True]
    assert len(posts) == 2
    assert posts[0]["model"] == "stale-model:cloud"
    assert posts[1]["model"] == "new-model:cloud"

    assert posts[0]["think"] is False
    assert posts[0]["stream"] is False
    assert posts[0]["options"]["temperature"] == relevance.JUDGE_TEMPERATURE


def test_judge_does_not_loop_when_retry_also_fails(monkeypatch):
    posts = []

    def _post(payload, *a, **k):
        posts.append(payload)
        return ('{"error":"model \'x\' not found"}', 404)

    monkeypatch.setattr(relevance, "resolve_intern_model",
                        lambda force=False: "x")
    monkeypatch.setattr(relevance, "post_chat", _post)

    assert relevance._call_intern("prompt") == ""
    assert len(posts) == 2






def test_intern_call_payload_uses_resolved_model(monkeypatch):
    captured = {}

    def _post(payload, *a, **k):
        captured["payload"] = json.loads(json.dumps(payload))
        return (json.dumps({"message": {"content": "ok"}}), 200)

    monkeypatch.setattr(guide_distill, "resolve_intern_model",
                        lambda force=False: "payload-probe:cloud")
    monkeypatch.setattr(guide_distill, "post_chat", _post)

    assert guide_distill.intern_call("hello") == "ok"
    assert captured["payload"]["model"] == "payload-probe:cloud"

    assert captured["payload"]["think"] is False


def test_distill_refreshes_and_retries_once_on_model_not_found(monkeypatch):
    resolves = []
    posts = []

    def _resolve(force=False):
        resolves.append(force)
        return "fresh:cloud"

    def _post(payload, *a, **k):
        posts.append(payload["model"])
        if len(posts) == 1:
            return ('{"error":"model unavailable"}', 200)
        return (json.dumps({"message": {"content": "distill-ok"}}), 200)

    monkeypatch.setattr(guide_distill, "resolve_intern_model", _resolve)
    monkeypatch.setattr(guide_distill, "post_chat", _post)

    assert guide_distill.intern_call("hello") == "distill-ok"
    assert resolves == [False, True]
    assert len(posts) == 2


def test_course_compose_inherits_guide_distill_intern_call():
    import course_compose



    assert course_compose.intern_call is guide_distill.intern_call








def test_post_chat_refuses_banned_endpoints():
    for url in ("http://127.0.0.1:13200/v1/chat/completions",
                "https://api.openai.com/v1/chat/completions",
                "http://127.0.0.1:13200/api/chat",
                "https://g4f.internal:13200/v1"):
        with pytest.raises(RuntimeError, match="banned"):
            intern_model.post_chat(
                {"model": "mistral-large-4:cloud", "messages": []}, url=url)


def test_post_chat_refuses_openai_models():
    for model in ("gpt-4o-mini", "chatgpt-4o", "o3-mini", "o1-preview",
                  "text-davinci-003"):
        with pytest.raises(RuntimeError, match="banned"):
            intern_model.post_chat({"model": model, "messages": []},
                                   url="http://127.0.0.1:11600/api/chat")


def test_resolve_intern_model_refuses_openai_override(monkeypatch):
    monkeypatch.setenv("CORTEX_INTERN_MODEL", "gpt-4o-mini")
    with pytest.raises(RuntimeError, match="banned"):
        intern_model.resolve_intern_model()


def test_approved_lane_shapes_still_allowed():


    intern_model._assert_not_openai("http://127.0.0.1:11600/api/chat",
                                    "mistral-large-4:cloud")
    intern_model._assert_not_openai("https://127.0.0.1:12999/v1/chat/completions",
                                    "some-approved-provider-model")
