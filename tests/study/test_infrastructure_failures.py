"""Outages on our side are marked as infrastructure failures, so they get rerun.

The model sees a tool error whether the outage was ours or the mistake was
its own. Only ours may be rerun; the model's mistakes must stay in the data.
The live tests run real sandbox runs: one switches off the database relay in
the middle, one connects to the wrong place on purpose.
"""

import json
import os
import subprocess
from types import SimpleNamespace as NS

import pytest

from repo_investigator.sandbox.docker_runner import RELAY_NAME
from repo_investigator.study import harness as h


def test_a_broken_connection_or_a_found_outage_is_ours():
    assert "broke" in h.infrastructure_problem(True, [])
    assert (
        h.infrastructure_problem(False, ["the database can't be reached"]) == "the database can't be reached"
    )
    assert h.infrastructure_problem(False, []) is None


def raising_tools(monkeypatch, probe_says):
    def boom(*_):
        raise TypeError("unhashable type: 'dict'")

    monkeypatch.setattr(h, "make_dispatch", lambda names: (boom, None))
    monkeypatch.setattr(h, "probe", lambda *_: probe_says)
    return h.tools_for("R1", "L2", "unused")[1]


def test_a_level_tool_error_during_an_outage_is_ours(monkeypatch):
    dispatch = raising_tools(monkeypatch, "the database can't be reached")
    with pytest.raises(TypeError):
        dispatch(None, "query_ci_runs", {})
    assert dispatch.problems == ["the database can't be reached"]


def test_a_level_tool_error_with_the_database_up_is_the_models(monkeypatch):
    dispatch = raising_tools(monkeypatch, None)
    with pytest.raises(TypeError):
        dispatch(None, "query_ci_runs", {})
    assert dispatch.problems == []


def sandbox_returning(monkeypatch, result, probe_says=None):
    monkeypatch.setattr(h, "isolated_network", lambda url: ["--network", "x"])
    monkeypatch.setattr(h, "run_python_in_sandbox", lambda *a, **k: result)
    monkeypatch.setattr(h, "probe", lambda *_: probe_says)
    dispatch = h.tools_for("R1", "sandbox", "unused")[1]
    dispatch(None, "execute_python", {"code": "x"})
    return dispatch.problems


def test_sandbox_docker_failing_is_ours(monkeypatch):
    result = {"stdout": "", "stderr": "docker: Error response from daemon: x", "exit_code": 125}
    assert "Docker failed" in sandbox_returning(monkeypatch, result)[0]


def test_sandbox_script_errors_are_checked(monkeypatch):
    result = {"stdout": "", "stderr": "Traceback ...", "exit_code": 1}
    assert sandbox_returning(monkeypatch, result, probe_says=None) == []
    assert sandbox_returning(monkeypatch, result, probe_says="down") == ["down"]


def test_sandbox_success_is_not_checked(monkeypatch):
    result = {"stdout": "42", "stderr": "", "exit_code": 0}
    assert sandbox_returning(monkeypatch, result, probe_says="never asked") == []


def test_reruns_skip_finished_runs_only(tmp_path):
    path = tmp_path / "runs.jsonl"
    stops = ["answered", "budget", "model_output_failure", "provider_failure", "infrastructure_failure"]
    path.write_text("".join(json.dumps({"run_id": s, "stop_reason": s}) + "\n" for s in stops))
    assert h.done_ids(path) == {"answered", "budget", "model_output_failure"}


def test_the_probe_reports_an_unreachable_database():
    assert "can't be reached" in h.probe("postgresql://user:pw@127.0.0.1:1/postgres")


class FakeModel:
    """Runs one script twice, then answers. Optionally the relay is stopped before the second run."""

    def __init__(self, code, stop_relay=False):
        self.chat = self
        self.completions = self
        self.turn = 0
        self.code = code
        self.stop_relay = stop_relay

    def create(self, **_):
        self.turn += 1
        if self.turn == 2 and self.stop_relay:
            subprocess.run(["docker", "stop", RELAY_NAME], capture_output=True, check=True)
        call = NS(
            id=f"c{self.turn}", function=NS(name="execute_python", arguments=json.dumps({"code": self.code}))
        )
        message = (
            NS(content=None, tool_calls=[call])
            if self.turn <= 2
            else NS(content="The data isn't available.", tool_calls=None)
        )
        usage = NS(model_dump=lambda: {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0})
        return NS(
            choices=[NS(message=message, finish_reason="stop")],
            usage=usage,
            provider="p",
            model="m",
            error=None,
        )


READ = "import os, pandas as pd\nprint(pd.read_sql('select count(*) from repos', os.environ['DATABASE_URL']))"
LOCAL = "import psycopg\npsycopg.connect('dbname=postgres')"


def live_run(model):
    url = os.environ.get("STUDY_SANDBOX_DATABASE_URL")
    if not url:
        pytest.skip("STUDY_SANDBOX_DATABASE_URL not set")
    q = h.load_questions("practice")[0]
    try:
        return h.run_one(
            q, "sandbox", "fake/model", 1, "v3", "test", h.OpenRouter(model, "p"), None, url, url
        )
    finally:
        subprocess.run(["docker", "start", RELAY_NAME], capture_output=True, check=False)


def test_a_relay_outage_mid_run_is_rerun():
    r = live_run(FakeModel(READ, stop_relay=True))
    first = json.loads(next(s["content"] for s in r["steps"] if s["step_type"] == "tool_result"))
    assert first["exit_code"] == 0, first
    assert r["stop_reason"] == "infrastructure_failure", r["infrastructure_problem"]


def test_a_model_connecting_elsewhere_stays_its_own_mistake():
    r = live_run(FakeModel(LOCAL))
    assert r["stop_reason"] == "answered", r["infrastructure_problem"]
    assert r["infrastructure_problem"] is None
