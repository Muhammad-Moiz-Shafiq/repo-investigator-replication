"""The harness end to end with a fake model, so no API call or cost."""

import json
import os
import sys
from types import SimpleNamespace as NS

import pytest

from repo_investigator.study import harness as h


class FakeModel:
    """Calls one tool, then answers. Records what it was sent."""

    def __init__(self, tool, args):
        self.tool, self.args, self.sent = tool, args, []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.sent.append(kw)
        if len(self.sent) == 1:
            call = NS(id="c1", type="function", function=NS(name=self.tool, arguments=json.dumps(self.args)))
            msg = NS(content="I'll call the tool.", tool_calls=[call])
        else:
            msg = NS(content="Final answer: done.", tool_calls=None)
        usage = NS(model_dump=lambda: {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.001})
        return NS(
            choices=[NS(message=msg, finish_reason="stop")],
            usage=usage,
            provider="FakeProvider",
            model="fake",
            error=None,
        )


@pytest.fixture
def prompt(tmp_path, monkeypatch):
    (tmp_path / "study_test.md").write_text(
        "<!--\nversion: test\nstatus: draft\n-->\nYou answer questions. Today is {today}."
    )
    monkeypatch.setattr(h, "PROMPTS", tmp_path)
    return "test"


def test_prompt_is_fixed_and_frozen_flag_read(prompt, tmp_path):
    text, sha, frozen = h.load_prompt(prompt)
    assert text == f"You answer questions. Today is {h.FIXED_TODAY}." and not frozen
    (tmp_path / "study_f.md").write_text("<!--\nstatus: frozen\n-->\nx")
    assert h.load_prompt("f")[2]


@pytest.fixture
def no_freeze(monkeypatch):
    """Skip the freeze comparison, which reads the database, so these checks also run in CI."""
    fake = NS(FREEZE=NS(read_text=lambda: "{}"), KINDS=[], current=dict)
    monkeypatch.setitem(sys.modules, "freeze_keys", fake)


def test_study_questions_need_a_frozen_prompt(prompt, no_freeze):
    with pytest.raises(SystemExit, match="frozen"):
        h.preflight("study", prompt, ["m"], ["L0"], {"m": "p"})


def test_study_questions_need_pinned_providers(tmp_path, monkeypatch, no_freeze):
    (tmp_path / "study_f.md").write_text("<!--\nstatus: frozen\n-->\nx")
    monkeypatch.setattr(h, "PROMPTS", tmp_path)
    with pytest.raises(SystemExit, match="pinned provider"):
        h.preflight("study", "f", ["m"], ["L0"], {})


def test_menus_per_setup():
    for setup, size in [("L0", 13), ("L1", 12), ("L2", 11), ("L3", 9), ("L2_padded", 13)]:
        schemas, _, names = h.tools_for("R1", setup, "unused")
        assert len(schemas) == len(names) == size
    assert h.tools_for("R1", "sandbox", "unused")[2] == ["execute_python"]


def test_one_run_end_to_end(prompt):
    url = os.environ.get("SANDBOX_DATABASE_URL")
    if not url:
        pytest.skip("SANDBOX_DATABASE_URL not set")
    q = next(q for q in h.load_questions("study") if q["id"] == "R10-tokio")
    fake = FakeModel(
        "fix_test_coverage", {"repo": "tokio-rs/tokio", "start": "2025-10-01", "end": "2026-09-20"}
    )
    llm = h.OpenRouter(fake, provider="FakeProvider")
    r = h.run_one(q, "L0", "fake/model", 1, prompt, "test", llm, None, url, url)
    assert r["stop_reason"] == "answered" and r["final_answer"] == "Final answer: done."
    assert (r["turns"], r["tool_calls"], r["tool_errors"], r["menu_size"]) == (2, 1, 0, 13)
    assert r["cost_usd"] == pytest.approx(0.002) and r["providers"] == ["FakeProvider"]
    sent = fake.sent[0]
    assert sent["messages"][0]["content"].endswith(h.FIXED_TODAY + ".")
    assert sent["extra_body"]["provider"] == {"order": ["FakeProvider"], "allow_fallbacks": False}
    assert len(sent["tools"]) == 13
    result = next(s for s in r["steps"] if s["step_type"] == "tool_result")
    assert '"fix_commits"' in result["content"]  # full tool result kept
    assert any(s["step_type"] == "reasoning" for s in r["steps"])
    assert len(r["prompt_sha256"]) == len(r["tools_sha256"]) == 64


def test_model_output_failures_are_not_rerun():
    empty = [
        {
            "step_type": "error",
            "content": "LLM call failed: Failed after 3 attempts, last error: Empty message: no tool_calls",
        }
    ]
    http = [
        {
            "step_type": "error",
            "content": "LLM call failed: Failed after 3 attempts, last error: Error code: 502",
        }
    ]
    assert h.classify("provider_failure", empty) == "model_output_failure"
    assert h.classify("provider_failure", http) == "provider_failure"
    assert h.classify("answered", []) == "answered"


def test_rate_limits_are_waited_out(monkeypatch):
    import httpx
    from openai import RateLimitError

    monkeypatch.setattr(h.time, "sleep", lambda s: None)
    err = RateLimitError(
        "429", response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None
    )

    class Flaky(FakeModel):
        def create(self, **kw):
            if len(self.sent) < 2:
                self.sent.append(kw)
                raise err
            return super().create(**kw)

    llm = h.OpenRouter(Flaky("t", {}), provider=None)
    llm.create(model="m", messages=[], tools=[])
    assert llm.rate_limit_waits == [10, 20]


def test_pin_check_matches_names_to_slugs():
    assert h.same_provider("Z.AI", "z-ai")
    assert h.same_provider("Google AI Studio", "google-ai-studio")
    assert h.same_provider("DeepInfra", "deepinfra/fp8")
    assert h.same_provider("Minimax", "minimax")
    assert not h.same_provider("CoreWeave", "z-ai")
    assert not h.same_provider("DeepInfra", "deepseek")
    assert not h.same_provider(None, "z-ai")
