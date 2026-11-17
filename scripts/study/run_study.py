# ruff: noqa: E501
"""Run study or practice questions through the harness.

Results go to study_runs/<run_set>/runs.jsonl, one line per run, written as
each run finishes. A rerun skips finished runs and retries provider failures.
--max-cost stops before a run would start once the set has spent that much.

Examples:
  # practice runs while developing the prompt (any prompt, unpinned allowed)
  uv run --env-file .env python scripts/study/run_study.py --set practice --prompt v1 \
      --models z-ai/glm-5.3-flash --setups L0 L2 --run-set prompt_v1_round1 --max-cost 1

  # study runs (prompt must be frozen, providers pinned, freeze check passes)
  uv run --env-file .env python scripts/study/run_study.py --set study --prompt v3 \
      --setups L0 L1 L2 L3 sandbox --tries 3 --run-set main
"""

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from langfuse import Langfuse
from openai import OpenAI

from repo_investigator.study import harness as h


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--set", choices=["practice", "study"], required=True)
    p.add_argument("--prompt", required=True, help="prompt version: prompts/study_<version>.md")
    p.add_argument("--run-set", required=True)
    p.add_argument("--models", nargs="+", default=h.STUDY_MODELS)
    p.add_argument("--setups", nargs="+", choices=h.SETUPS, default=["L0", "L1", "L2", "L3", "sandbox"])
    p.add_argument("--questions", nargs="*", help="question ids or templates (default: all)")
    p.add_argument("--tries", type=int, default=1)
    p.add_argument(
        "--max-cost", type=float, required=True, help="stop once the run set has spent this many dollars"
    )
    p.add_argument("--workers", type=int, default=1, help="runs in parallel")
    p.add_argument("--no-langfuse", action="store_true")
    a = p.parse_args()

    questions = h.load_questions(a.set)
    if a.questions:
        questions = [q for q in questions if q["id"] in a.questions or q["template"] in a.questions]
    providers = h.providers_config()
    h.preflight(a.set, a.prompt, a.models, a.setups, providers)

    out = h.RUNS / a.run_set / "runs.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = h.done_ids(out)
    spent = (
        sum(json.loads(line)["cost_usd"] for line in out.read_text().splitlines()) if out.exists() else 0.0
    )
    # An explicit timeout, and no hidden client retries: the loop's 3 attempts are the only retries, and they are logged.
    base = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=h.env("OPENROUTER_API_KEY"),
        timeout=120,
        max_retries=0,
    )
    langfuse = None if a.no_langfuse else Langfuse()
    # Every setup reads through the study role: the 7 data tables, read-only, nothing else.
    db_url = sandbox_db_url = h.env("STUDY_SANDBOX_DATABASE_URL")

    plan = [
        (q, s, m, t)
        for t in range(1, a.tries + 1)
        for m in a.models
        for s in a.setups
        for q in questions
        if h.run_id(q, s, m, t) not in done
    ]
    print(f"{len(plan)} runs to do, {len(done)} already done, ${spent:.4f} spent so far", flush=True)
    lock = threading.Lock()
    state = {"spent": spent, "stop": None, "failed_in_a_row": 0}

    def one(item):
        q, setup, model, attempt = item
        with lock:
            if state["stop"]:
                return
            if state["spent"] >= a.max_cost:
                state["stop"] = f"Stopping: ${state['spent']:.4f} spent, the limit is ${a.max_cost}."
                return
        llm = h.OpenRouter(base, providers.get(model))
        try:
            r = h.run_one(
                q, setup, model, attempt, a.prompt, a.run_set, llm, langfuse, db_url, sandbox_db_url
            )
        except Exception as e:  # noqa: BLE001
            # Our own failure (say a lost database connection): no record, so a rerun picks it up.
            print(
                f"ERROR in {h.run_id(q, setup, model, attempt)}, not recorded, will rerun: {e!r}", flush=True
            )
            return
        with lock:  # one writer at a time, so lines never interleave
            with out.open("a") as f:
                f.write(json.dumps(r, default=str) + "\n")
            state["spent"] += r["cost_usd"]
            if r["pin_held"] is False:
                print(
                    f"WARNING: {r['run_id']} was served by {r['providers']}, not the pinned {r['pinned_provider']}."
                )
            if r["stop_reason"] == "infrastructure_failure":
                # The database, Docker or the relay is down: every run would fail. Stop, fix, rerun.
                state["stop"] = (
                    f"Stopping: {r['infrastructure_problem']}. Fix it, then run the same command again."
                )
            state["failed_in_a_row"] = (
                state["failed_in_a_row"] + 1 if r["stop_reason"] in h.RERUN_STOPS else 0
            )
            if state["failed_in_a_row"] >= 8:
                # Likely the internet is down. These runs get redone on the next start.
                state["stop"] = (
                    "Stopping: 8 runs in a row failed to reach the provider. Check the connection, then run the same command again."
                )
            if r["stop_reason"] == "provider_failure":
                error = next((s["content"] for s in r["steps"] if s["step_type"] == "error"), "")
                if any(code in error for code in ("401", "402", "403", "API key", "credits")):
                    # A bad key or no credits fails every run the same way; stop instead of trying them all.
                    state["stop"] = f"Stopping: an account problem, not a model problem.\n{error[:300]}"
            print(
                f"{r['run_id']}: {r['stop_reason']}, {r['turns']} turns, {r['tool_calls']} calls, ${r['cost_usd']:.4f} (total ${state['spent']:.4f})",
                flush=True,
            )

    # Runs in parallel threads. Each run has its own model client and database
    # connection. A run already started finishes even after a stop; at most
    # `workers` runs can be in flight past the cost limit.
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in [pool.submit(one, item) for item in plan]:
            f.result()
    if state["stop"]:
        print(state["stop"])
    if langfuse:
        langfuse.flush()
    if state["stop"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
