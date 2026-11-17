# ruff: noqa: E501
"""The study harness: one run = one question, one setup, one model, one try.

Every setup goes through the pilot's ReAct loop (agent/react_loop.py). Only
the tools change: the coverage level menus (levels/menus.py), the padded
level 2 menu for the menu size side check, or the open sandbox. The question,
system prompt, budget (25 model turns) and model settings are the same.

Safeguards, each against a real way the study could go wrong:
- Study questions only run with a prompt file marked "status: frozen", so the
  prompt can't be tuned on them by accident. Practice questions run anytime.
- Study runs refuse to start if the keys, questions, data, prompt, tools,
  judges, packages or sandbox images differ from the freeze, or if a model has
  no pinned provider.
- Every run records the prompt hash and the tool schema hash, so any later
  change shows up in the data.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from langfuse import propagate_attributes
from openai import RateLimitError

from repo_investigator.agent.react_loop import MAX_ITERATIONS, run_react_loop
from repo_investigator.levels.menus import menu, padded_level2
from repo_investigator.levels.tools import ALL_SCHEMAS, make_dispatch
from repo_investigator.sandbox.docker_runner import (
    RELAY_IMAGE,
    STUDY_SANDBOX_IMAGE,
    isolated_network,
    run_python_in_sandbox,
)

ROOT = Path(__file__).parent.parent.parent.parent
PROMPTS = ROOT / "prompts"
RUNS = ROOT / "study_runs"
PROVIDERS_FILE = ROOT / "study_config" / "providers.json"
WORKFLOWS_FILE = ROOT / "tool_data" / "workflows.json"
QUESTION_FILES = {
    "study": ROOT / "questions" / "questions.json",
    "practice": ROOT / "questions" / "practice.json",
}

STUDY_MODELS = [
    "deepseek/deepseek-v4-flash",
    "google/gemini-2.5-flash-lite",
    "z-ai/glm-5.3-flash",
    "minimax/minimax-m3.1-flash",
    "mistralai/ministral-14b-2512",
]
# The date the prompt gives as today. Fixed, so the prompt text is the same
# in every run. It is after the data window ends (2026-09-20).
FIXED_TODAY = "2026-10-01"
SETUPS = ("L0", "L1", "L2", "L3", "L2_padded", "sandbox")

SANDBOX_SCHEMA = {
    "type": "function",
    "function": {
        "name": "execute_python",
        "description": (
            "Runs Python code in a sandboxed container and returns its stdout and stderr (each cut at 5,000 "
            "characters; 30 second limit; 256 MB of memory). Installed: Python 3.12 with pandas, numpy, scipy, "
            "SQLAlchemy, psycopg (version 3) and psycopg2, nothing else, and nothing can be installed. There is "
            "no internet access: the only thing the code can reach is the database. A read-only Postgres "
            "connection string is in the DATABASE_URL environment variable (pandas.read_sql works with it "
            "through SQLAlchemy). Print anything you want to see. Tables, each "
            "scoped by repo_id (join repos on id and filter by owner and name):\n"
            "- repos(id, owner, name)\n"
            "- commits(sha, repo_id, author_login, author_email, committed_at, message, additions, deletions, changed_files, is_merge, is_bugfix): commits on the default branch\n"
            "- commit_files(id, commit_sha, filename, status, additions, deletions, patch)\n"
            "- pull_requests(id, repo_id, number, title, author_login, state, created_at, merged_at, closed_at, review_comment_count, approval_count, time_to_merge_seconds)\n"
            "- pr_reviews(id, repo_id, pr_number, reviewer_login, state, submitted_at)\n"
            "- issues(id, repo_id, number, title, author_login, state, created_at, closed_at, labels (text array), comment_count, is_bug)\n"
            "- ci_runs(id, repo_id, commit_sha, workflow_id, workflow_name, status, conclusion, event, run_attempt, started_at, completed_at, duration_seconds): GitHub Actions runs, latest attempt\n"
            "Each repository's CI workflows (id, name and file path) are in /data/workflows.json, as "
            '{"repos": {name: {"workflows": [{"id", "name", "path", ...}]}}}. Timestamps are UTC.'
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source code to run as a standalone script."}
            },
            "required": ["code"],
        },
    },
}


class OpenRouter:
    """Wraps the OpenAI client for OpenRouter. Every call asks for its real cost,
    records the provider that served it, and, when one is given, pins the
    provider with no fallback."""

    def __init__(self, client, provider: str | None):
        self._client = client
        self.provider = provider
        self.calls: list[dict] = []
        self.rate_limit_waits: list[int] = []
        self.chat = self
        self.completions = self

    RATE_LIMIT_WAITS = (10, 20, 40, 60, 60)

    def create(self, **kwargs):
        extra = {"usage": {"include": True}}
        if self.provider:
            extra["provider"] = {"order": [self.provider], "allow_fallbacks": False}
        start = time.time()
        waited = []
        # A rate limit (429) says nothing about the model, and the loop's short
        # retry delay can't outlast one. Back off here, log every wait, then give up.
        for wait in (*self.RATE_LIMIT_WAITS, None):
            try:
                response = self._client.chat.completions.create(**kwargs, extra_body=extra)
                break
            except RateLimitError:
                if wait is None:
                    self.rate_limit_waits += waited
                    raise
                waited.append(wait)
                time.sleep(wait)
        self.rate_limit_waits += waited
        usage = response.usage.model_dump() if getattr(response, "usage", None) else {}
        details = usage.get("completion_tokens_details") or {}
        self.calls.append(
            {
                "provider": getattr(response, "provider", None),
                "served_model": getattr(response, "model", None),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens"),
                "cost": usage.get("cost"),
                "seconds": round(time.time() - start, 2),
            }
        )
        return response


def load_questions(which: str) -> list[dict]:
    path = QUESTION_FILES[which]
    if not path.exists():
        raise SystemExit(f"{path} doesn't exist yet.")
    return [q for q in json.loads(path.read_text()) if q.get("in_study", True)]


def load_prompt(version: str) -> tuple[str, str, bool]:
    """The system prompt text (with today filled in), its sha256, and whether it is frozen."""
    path = PROMPTS / f"study_{version}.md"
    raw = path.read_text()
    header, text = ("", raw)
    if raw.startswith("<!--"):
        header, text = raw[4:].split("-->", 1)
    text = text.strip().replace("{today}", FIXED_TODAY)
    frozen = re.search(r"^status:\s*frozen\s*$", header, re.MULTILINE) is not None
    return text, hashlib.sha256(text.encode()).hexdigest(), frozen


def tools_for(template: str, setup: str, database_url: str):
    """Tool schemas, dispatch function and menu for one setup.

    When a tool fails, the database (and for the sandbox, the path through the
    relay) is checked at that moment, as it is, without repairing anything.
    Outages found this way are kept in dispatch.problems for the run record.
    """
    problems: list[str] = []
    if setup == "sandbox":
        # Set up on the first call, so building a menu (as tests do) never touches Docker.
        cache: list[list[str]] = []

        def network() -> list[str]:
            if not cache:
                cache.append(isolated_network(database_url))
            return cache[0]

        def dispatch(conn, name, arguments):
            if name != "execute_python":
                return {"error": f"Unknown tool {name!r}. Tools: execute_python."}
            if not isinstance(arguments.get("code"), str):
                return {"error": "'code' must be a string of Python code."}
            result = run_python_in_sandbox(
                arguments["code"],
                database_url,
                read_only_files={str(WORKFLOWS_FILE): "/data/workflows.json"},
                image=STUDY_SANDBOX_IMAGE,
                docker_args=network(),
            )
            if result["exit_code"] != 0:
                err = str(result.get("stderr") or "")
                if result["exit_code"] == 125 or any(x in err for x in DOCKER_FAILURES):
                    problems.append(f"Docker failed: {err[-200:]}")
                elif problem := probe(database_url, network()):
                    problems.append(problem)
            return result

        dispatch.problems = problems
        return [SANDBOX_SCHEMA], dispatch, ["execute_python"]
    names = {
        "L0": lambda: menu(template, 0),
        "L1": lambda: menu(template, 1),
        "L2": lambda: menu(template, 2),
        "L3": lambda: menu(template, 3),
        "L2_padded": lambda: padded_level2(template),
    }[setup]()
    inner, _ = make_dispatch(names)

    def dispatch(conn, name, arguments):
        # Errors from a model's bad request come back as results. Anything raised is either
        # a model input our code didn't expect or an outage; the check tells them apart.
        try:
            return inner(conn, name, arguments)
        except Exception:
            if problem := probe(database_url):
                problems.append(problem)
            raise

    dispatch.problems = problems
    return [ALL_SCHEMAS[n] for n in names], dispatch, names


def schema_hash(schemas: list[dict]) -> str:
    return hashlib.sha256(json.dumps(schemas, sort_keys=True).encode()).hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def run_id(q: dict, setup: str, model: str, attempt: int) -> str:
    return f"{q['id']}__{setup}__{model.replace('/', '_')}__t{attempt}"


def preflight(which: str, prompt_version: str, models: list[str], setups: list[str], providers: dict) -> None:
    """Refuse to start a study run that could produce invalid data."""
    problems = []
    _, _, frozen = load_prompt(prompt_version)
    if which == "study":
        if not frozen:
            problems.append(f"prompts/study_{prompt_version}.md is not marked 'status: frozen'.")
        problems += [
            f"{m} has no pinned provider in {PROVIDERS_FILE.name}." for m in models if not providers.get(m)
        ]
        sys.path.insert(0, str(ROOT / "scripts" / "answer_keys"))
        from freeze_keys import FREEZE, KINDS, current  # noqa: PLC0415

        frozen_state, now = json.loads(FREEZE.read_text()), current()
        problems += [
            f"{kind} {name} differs from the freeze."
            for kind in KINDS
            for name in frozen_state.get(kind, {})
            if frozen_state[kind][name] != now[kind].get(name)
        ]
    if "sandbox" in setups:
        if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
            problems.append("Docker is not running, and the sandbox needs it.")
        else:
            problems += [
                f"The image {image} is missing. Run scripts/study/build_sandbox.sh."
                for image in (STUDY_SANDBOX_IMAGE, RELAY_IMAGE)
                if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode != 0
            ]
    if problems:
        raise SystemExit("Not starting:\n- " + "\n- ".join(problems))


# After the loop's retries, these errors are the model's own output (an empty
# reply, or a tool call its provider couldn't format), not the infrastructure.
# They end the run with no answer and are never rerun: rerunning them would
# give a flaky model extra chances and hide a real weakness.
MODEL_OUTPUT_ERRORS = ("Empty message", "finish_reason=error", "MALFORMED_FUNCTION_CALL")


def same_provider(served: str | None, pinned: str) -> bool:
    """Served names look like "Z.AI" or "Google AI Studio". Pins are slugs or endpoint
    tags like "z-ai" or "deepinfra/fp8"; only the provider part is compared."""
    norm = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower())  # noqa: E731
    return bool(served) and norm(served) == norm(pinned.split("/")[0])


def classify(stop_reason: str | None, steps: list[dict]) -> str | None:
    if stop_reason != "provider_failure":
        return stop_reason
    error = next((s["content"] for s in steps if s["step_type"] == "error"), "")
    return "model_output_failure" if any(e in error for e in MODEL_OUTPUT_ERRORS) else "provider_failure"


# Docker itself failing to run a container (exit code 125) is never the model's doing.
DOCKER_FAILURES = ("Cannot connect to the Docker daemon", "Error response from daemon")
PROBE_CODE = "import os, psycopg\npsycopg.connect(os.environ['DATABASE_URL'], connect_timeout=10).execute('select 1')\nprint('ok')"


def probe(db_url: str, docker_args: list[str] | None = None) -> str | None:
    """Check right now that the database can be reached, and with docker_args, that a
    sandbox container on the same network can reach it through the relay. Nothing is
    restarted first, so an outage shows up as it is."""
    try:
        with psycopg.connect(db_url, connect_timeout=10) as c:
            c.execute("select 1")
    except Exception as e:  # noqa: BLE001
        return f"the database can't be reached: {str(e)[:200]}"
    if docker_args is not None:
        r = run_python_in_sandbox(
            PROBE_CODE, db_url, image=STUDY_SANDBOX_IMAGE, docker_args=docker_args, timeout_seconds=30
        )
        if r["stdout"].strip() != "ok":
            return f"the sandbox can't reach the database: {str(r['stderr'])[-200:]}"
    return None


def infrastructure_problem(conn_broken: bool, problems: list[str]) -> str | None:
    """Why a finished run can't count because our side failed, or None if it can.

    The model sees a tool error either way, so a run that hit an outage looks like
    a normal answer (often "the data isn't available"). Such a run is an
    infrastructure failure under the failure rule and gets rerun.
    """
    if conn_broken:
        return "the database connection broke during the run"
    return problems[0] if problems else None


def run_one(
    q: dict,
    setup: str,
    model: str,
    attempt: int,
    prompt_version: str,
    run_set: str,
    llm,
    langfuse,
    db_url: str,
    sandbox_db_url: str,
) -> dict:
    prompt, prompt_sha, frozen = load_prompt(prompt_version)
    schemas, dispatch, names = tools_for(q["template"], setup, sandbox_db_url)
    rid = run_id(q, setup, model, attempt)
    meta = {
        "run_id": rid,
        "run_set": run_set,
        "question_id": q["id"],
        "template": q["template"],
        "repo": q["repo"],
        "setup": setup,
        "model": model,
        "attempt": attempt,
        "prompt_version": prompt_version,
        "prompt_frozen": frozen,
        "menu_size": len(names),
    }
    started = datetime.now(UTC).isoformat(timespec="seconds")
    # Autocommit, so the session never sits idle in a transaction while the model thinks.
    conn = psycopg.connect(db_url, autocommit=True)
    conn.read_only = True
    try:
        ctx = (
            propagate_attributes(
                session_id=run_set,
                trace_name=rid,
                tags=[setup, q["template"], model.split("/")[-1], f"prompt:{prompt_version}"],
                metadata={k: str(v) for k, v in meta.items()},
            )
            if langfuse
            else None
        )
        if ctx:
            ctx.__enter__()
        try:
            result = run_react_loop(
                conn,
                llm,
                model,
                q["question"],
                tool_schemas=schemas,
                dispatch_fn=dispatch,
                prompt_version=prompt_version,
                langfuse=langfuse,
                system_prompt=prompt,
                tool_result_chars=None,
            )
        finally:
            if ctx:
                ctx.__exit__(None, None, None)
    finally:
        conn_broken = conn.broken
        conn.close()
    calls = llm.calls
    steps = [s.model_dump() for s in result.steps]
    infra = infrastructure_problem(conn_broken, dispatch.problems)
    tool_results = [s for s in steps if s["step_type"] == "tool_result"]
    return {
        **meta,
        "menu": names,
        "prompt_sha256": prompt_sha,
        "tools_sha256": schema_hash(schemas),
        "max_turns": MAX_ITERATIONS,
        "sandbox_image": STUDY_SANDBOX_IMAGE if setup == "sandbox" else None,
        "today": FIXED_TODAY,
        "git_commit": git_commit(),
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "stop_reason": "infrastructure_failure" if infra else classify(result.stop_reason, steps),
        "infrastructure_problem": infra,
        "final_answer": result.final_answer,
        "turns": result.turns,
        "tool_calls": sum(s["step_type"] == "tool_call" for s in steps),
        "tool_errors": sum('"error"' in s["content"][:20] for s in tool_results),
        "llm_calls": len(calls),
        "providers": sorted({c["provider"] for c in calls if c["provider"]}),
        "pinned_provider": llm.provider,
        # False if any call was served by another provider than the pinned one.
        "pin_held": None
        if not llm.provider
        else all(same_provider(c["provider"], llm.provider) for c in calls),
        "rate_limit_waits_s": sum(llm.rate_limit_waits),
        "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in calls),
        "completion_tokens": sum(c["completion_tokens"] or 0 for c in calls),
        "reasoning_tokens": sum(c["reasoning_tokens"] or 0 for c in calls),
        "cost_usd": sum(c["cost"] or 0 for c in calls),
        "langfuse_trace_id": result.langfuse_trace_id,
        "calls": calls,
        "steps": steps,
    }


RERUN_STOPS = ("provider_failure", "infrastructure_failure")


def done_ids(path: Path) -> set[str]:
    """Runs already finished. A provider or infrastructure failure is not finished: it gets
    rerun. A model output failure is finished: that is how the model behaved."""
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if r["stop_reason"] not in RERUN_STOPS:
            out.add(r["run_id"])
    return out


def providers_config() -> dict:
    return json.loads(PROVIDERS_FILE.read_text()) if PROVIDERS_FILE.exists() else {}


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set.")
    return value
