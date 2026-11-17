"""Fairness test 5: only the tools differ between setups.

For one question of every template, the same model is run in all six setups
with a fake model that answers at once. Everything sent to the model except
the tool list must be the same: system prompt, question, model name, provider
pin and every other request field. The run records must agree on the prompt
hash, turn limit, fixed date and pin. And no setup can reach a tool that is
not on its menu, even if the model names one.
"""

import json
import os
from types import SimpleNamespace as NS

import pytest

from repo_investigator.levels.tools import ALL_SCHEMAS
from repo_investigator.study import harness as h

MODEL = "fake/model"
PIN = "fake-provider"


class AnswersAtOnce:
    """Records every request and answers without calling a tool."""

    def __init__(self):
        self.sent = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.sent.append(kw)
        usage = NS(model_dump=lambda: {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0})
        return NS(
            choices=[NS(message=NS(content="Final answer: x", tool_calls=None), finish_reason="stop")],
            usage=usage,
            provider=PIN,
            model=MODEL,
            error=None,
        )


def one_per_template():
    seen = {}
    for q in h.load_questions("study"):
        seen.setdefault(q["template"], q)
    return list(seen.values())


@pytest.fixture(scope="module")
def runs():
    url = os.environ.get("STUDY_SANDBOX_DATABASE_URL")
    if not url:
        pytest.skip("STUDY_SANDBOX_DATABASE_URL not set")
    out = {}
    for q in one_per_template():
        for setup in h.SETUPS:
            fake = AnswersAtOnce()
            record = h.run_one(q, setup, MODEL, 1, "v3", "test", h.OpenRouter(fake, PIN), None, url, url)
            out[(q["id"], setup)] = (fake.sent, record)
    return out


def test_requests_differ_only_in_tools(runs):
    for qid in {k[0] for k in runs}:
        requests = {s: runs[(qid, s)][0] for s in h.SETUPS}
        assert all(len(r) == 1 for r in requests.values())
        without_tools = {
            s: json.dumps({k: v for k, v in r[0].items() if k != "tools"}, sort_keys=True)
            for s, r in requests.items()
        }
        assert len(set(without_tools.values())) == 1, qid
        tool_lists = {s: json.dumps(r[0]["tools"], sort_keys=True) for s, r in requests.items()}
        assert len(set(tool_lists.values())) == len(h.SETUPS), f"{qid}: two setups got the same tools"


def test_the_question_and_prompt_are_sent_unchanged(runs):
    prompt = h.load_prompt("v3")[0]
    questions = {q["id"]: q["question"] for q in one_per_template()}
    for (qid, _), (sent, _) in runs.items():
        messages = sent[0]["messages"]
        assert messages[0] == {"role": "system", "content": prompt}
        assert messages[1] == {"role": "user", "content": questions[qid]}
        assert len(messages) == 2


def test_records_agree_on_everything_but_the_tools(runs):
    fields = (
        "prompt_sha256",
        "prompt_version",
        "prompt_frozen",
        "max_turns",
        "today",
        "pinned_provider",
        "model",
    )
    values = {json.dumps({f: r[f] for f in fields}) for _, r in runs.values()}
    assert len(values) == 1
    assert all(r["pin_held"] for _, r in runs.values())


def test_no_setup_reaches_a_tool_off_its_menu():
    every_tool = set(ALL_SCHEMAS) | {"execute_python"}
    for q in one_per_template():
        for setup in h.SETUPS:
            _, dispatch, names = h.tools_for(q["template"], setup, "unused")
            for name in sorted(every_tool - set(names)):
                result = dispatch(None, name, {})
                assert "error" in result and "Unknown tool" in result["error"], (q["id"], setup, name)
