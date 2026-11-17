# ruff: noqa: E501
"""Screen candidate study models for basic tool calling before choosing them.

Uses the pilot harness (Variant A, its 6 tools, prompt v2_grounded) on the 5
pilot questions, one try each. The 63 study questions are never used here, so
no model is picked by how it does on the real test. The pass rule is in
docs/decisions.md (2026-10-23) and was written before the first run.

Raw results go to screening_results/<model>.json, saved after every question,
and a rerun skips questions that already finished.

Usage:
  uv run --env-file .env python scripts/screening/screen_models.py            # round 1 models
  uv run --env-file .env python scripts/screening/screen_models.py MODEL ...  # other models
"""

import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from run_evaluation import TEST_QUESTIONS, compute_objective_metrics  # noqa: E402

from repo_investigator.agent.react_loop import run_react_loop  # noqa: E402
from repo_investigator.agent.tool_dispatch import dispatch_tool_call  # noqa: E402
from repo_investigator.agent.tool_schemas import TOOL_SCHEMAS  # noqa: E402
from repo_investigator.db.connection import get_psycopg_connection  # noqa: E402

ROOT = Path(__file__).parent.parent.parent
OUT = ROOT / "screening_results"
# Round 1. Round 2 passes its models on the command line.
MODELS = [
    "mistralai/mistral-small-3.2-24b-instruct",
    "qwen/qwen3-235b-a22b-2507",
    "z-ai/glm-5.3-flash",
    "minimax/minimax-m3.1-flash",
]


class UsageRecorder:
    """Wraps the OpenAI client so every call asks OpenRouter for its real cost
    and records which provider served it. The ReAct loop itself is unchanged."""

    def __init__(self, client):
        self._client = client
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        response = self._client.chat.completions.create(**kwargs, extra_body={"usage": {"include": True}})
        usage = response.usage.model_dump() if response.usage else {}
        self.calls.append(
            {
                "provider": getattr(response, "provider", None),
                "served_model": response.model,
                "cost": usage.get("cost"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            }
        )
        return response


def tool_problems(steps):
    bad_json = unknown = other = 0
    for s in steps:
        if s.step_type != "tool_result":
            continue
        if "invalid JSON arguments" in s.content:
            bad_json += 1
        elif "Unknown tool" in s.content:
            unknown += 1
        elif '"error"' in s.content:
            other += 1
    return bad_json, unknown, other


def main():
    OUT.mkdir(exist_ok=True)
    base = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
    for model in sys.argv[1:] or MODELS:
        path = OUT / f"{model.replace('/', '__')}.json"
        done = json.loads(path.read_text()) if path.exists() else []
        have = {d["id"] for d in done if "metrics" in d}
        done = [d for d in done if d["id"] in have]
        for item in TEST_QUESTIONS:
            if item["id"] in have:
                continue
            llm = UsageRecorder(base)
            conn = get_psycopg_connection(os.environ["DATABASE_URL"])
            start = time.time()
            try:
                result = run_react_loop(
                    conn,
                    llm,
                    model,
                    item["question"],
                    tool_schemas=TOOL_SCHEMAS,
                    dispatch_fn=dispatch_tool_call,
                    prompt_version="v2_grounded",
                )
            except Exception as e:  # noqa: BLE001
                done.append({"id": item["id"], "model": model, "harness_error": repr(e), "calls": llm.calls})
                path.write_text(json.dumps(done, indent=1) + "\n")
                print(f"{model} {item['id']}: HARNESS ERROR {e}", flush=True)
                continue
            finally:
                conn.close()
            bad_json, unknown, other = tool_problems(result.steps)
            metrics = compute_objective_metrics(result) | {
                "bad_json_calls": bad_json,
                "unknown_tool_calls": unknown,
                "other_tool_errors": other,
                "provider_failure": any(
                    s.step_type == "error" and "LLM call failed" in s.content for s in result.steps
                ),
                "llm_calls": len(llm.calls),
                "cost_usd": sum(c["cost"] or 0 for c in llm.calls),
                "seconds": round(time.time() - start, 1),
            }
            done.append(
                {
                    "id": item["id"],
                    "model": model,
                    "metrics": metrics,
                    "final_answer": result.final_answer,
                    "steps": [s.model_dump() for s in result.steps],
                    "calls": llm.calls,
                }
            )
            path.write_text(json.dumps(done, indent=1) + "\n")
            m = metrics
            print(
                f"{model} {item['id']}: converged={m['converged']} tools={m['num_tool_calls']} "
                f"bad_json={bad_json} unknown={unknown} other_err={other} cost=${m['cost_usd']:.4f} {m['seconds']}s",
                flush=True,
            )


if __name__ == "__main__":
    main()
