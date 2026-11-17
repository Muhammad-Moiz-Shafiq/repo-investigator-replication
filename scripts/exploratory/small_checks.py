"""Small exploratory checks on the main run. Not pre-registered.

1. The one level 3 run that passed: what it did.
2. Cost against accuracy, per model and setup.
3. Fan-out: do runs that make 20 or more tool calls in one turn do better?
4. The run that hit the model's context limit.
5. Stand-in answers whose values are right anyway: each stand-in answer scored
   as if its values were real answers, with the grader's own check.

Reads only committed files. Writes analysis_results/exploratory/small_checks.json.

Usage:
  uv run python scripts/exploratory/small_checks.py
"""

import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
sys.path.insert(0, str(ROOT / "src"))
from must_haves import check  # noqa: E402

from repo_investigator.grading.extract import to_guess  # noqa: E402

OUT = ROOT / "analysis_results" / "exploratory" / "small_checks.json"
MAIN = ["L0", "L1", "L2", "L3", "sandbox"]
FAN_OUT = 20  # tool calls in one turn
RERUN = ("provider_failure", "infrastructure_failure")


def load():
    with gzip.open(ROOT / "grading_results" / "main" / "final.jsonl.gz", "rt") as f:
        grades = {g["run_id"]: g for g in map(json.loads, f)}
    runs = {}
    for n in (1, 2):
        with gzip.open(ROOT / "study_runs" / "main" / f"try{n}_runs.jsonl.gz", "rt") as f:
            for line in f:
                r = json.loads(line)
                # A run redone after an outage appears twice; the grades name the one that counts.
                if r["run_id"] in grades and r["stop_reason"] not in RERUN:
                    runs[r["run_id"]] = r
    return grades, runs


def short(model):
    return model.split("/")[-1]


def max_calls_in_a_turn(run):
    per_turn = defaultdict(int)
    for s in run["steps"]:
        if s["step_type"] == "tool_call":
            per_turn[s["turn"]] += 1
    return max(per_turn.values(), default=0)


def level3_pass(grades, runs):
    out = []
    for rid, g in grades.items():
        if g["setup"] == "L3" and g["passed"]:
            r = runs[rid]
            out.append(
                {
                    "run_id": rid,
                    "answer": r["final_answer"],
                    "tools_called": sorted({s["tool_name"] for s in r["steps"] if s["tool_name"]}),
                    "menu": r["menu"],
                    "items": g["items"],
                }
            )
    return out


def cost(grades, runs):
    by = defaultdict(lambda: {"runs": 0, "passed": 0, "cost": 0.0})
    for rid, g in grades.items():
        for key in ((short(g["model"]), g["setup"]), ("all", g["setup"]), (short(g["model"]), "main")):
            if key[1] == "main" and g["setup"] not in MAIN:
                continue
            b = by[key]
            b["runs"] += 1
            b["passed"] += g["passed"]
            b["cost"] += runs[rid]["cost_usd"] or 0
    out = {}
    for (model, setup), b in sorted(by.items()):
        out[f"{model} / {setup}"] = {
            **b,
            "cost": round(b["cost"], 2),
            "pass_rate": round(b["passed"] / b["runs"], 4),
            "cost_per_run": round(b["cost"] / b["runs"], 4),
            "cost_per_pass": round(b["cost"] / b["passed"], 4) if b["passed"] else None,
        }
    return out


def fan_out(grades, runs):
    """Within each model and setup, pass rate of fan-out runs against the rest."""
    cells = defaultdict(lambda: {"fan_out": [0, 0], "rest": [0, 0]})
    for rid, g in grades.items():
        group = "fan_out" if max_calls_in_a_turn(runs[rid]) >= FAN_OUT else "rest"
        c = cells[f"{short(g['model'])} / {g['setup']}"][group]
        c[0] += 1
        c[1] += g["passed"]
    out = {}
    for cell, c in sorted(cells.items()):
        if c["fan_out"][0]:
            out[cell] = {
                "fan_out_runs": c["fan_out"][0],
                "fan_out_pass": c["fan_out"][1],
                "other_runs": c["rest"][0],
                "other_pass": c["rest"][1],
            }
    return out


def context_limit(grades, runs):
    """The run I marked by hand as hitting the model's context limit (study_log.md, try 2),
    next to the largest prompt sizes of other runs for scale."""
    rows = sorted(runs.values(), key=lambda r: r["prompt_tokens"] or 0, reverse=True)[:5]
    return [
        {
            "run_id": r["run_id"],
            "stop_reason": r["stop_reason"],
            "turns": r["turns"],
            "tool_calls": r["tool_calls"],
            "prompt_tokens_all_turns": r["prompt_tokens"],
            "passed": grades[r["run_id"]]["passed"],
        }
        for r in rows
    ]


def extracted(g):
    return g.get("final_extracted") or {}


def stand_ins_right_anyway():
    """Every failed answer with at least one stand-in value, scored as if the stand-ins were real."""
    keys = json.loads((ROOT / "answer_keys" / "keys_primary.json").read_text())
    alts = json.loads((ROOT / "answer_keys" / "accepted_alternatives.json").read_text())
    with gzip.open(ROOT / "grading_results" / "main" / "final.jsonl.gz", "rt") as f:
        stand = [
            g
            for g in map(json.loads, f)
            if not g["passed"] and any((v or {}).get("stand_in") for v in extracted(g).values())
        ]
    out = []
    for g in stand:
        t, repo = g["template"], g["repo"]
        as_real = {n: {**(v or {}), "stand_in": False} for n, v in extracted(g).items()}
        items = check(t, keys[t][repo], to_guess(t, as_real), alts.get(t, {}).get(repo, []))
        out.append(
            {
                "run_id": g["run_id"],
                "label": g["label"],
                "would_pass": all(items.values()),
                "stand_in_fields": [n for n, v in extracted(g).items() if (v or {}).get("stand_in")],
            }
        )
    return out


def median_cost(runs, grades, setup):
    return statistics.median(r["cost_usd"] or 0 for rid, r in runs.items() if grades[rid]["setup"] == setup)


def main():
    grades, runs = load()
    stand = stand_ins_right_anyway()
    res = {
        "note": "Exploratory, not pre-registered.",
        "runs": len(runs),
        "level3_pass": level3_pass(grades, runs),
        "cost": cost(grades, runs),
        "fan_out_threshold": FAN_OUT,
        "fan_out": fan_out(grades, runs),
        "context_limit": context_limit(grades, runs),
        "stand_ins_right_anyway": [s for s in stand if s["would_pass"]],
        "stand_ins_checked": len(stand),
        "median_cost_per_run_by_setup": {
            s: round(median_cost(runs, grades, s), 5)
            for s in (*MAIN, "L2_padded")
        },
    }
    OUT.write_text(json.dumps(res, indent=1, default=str) + "\n")
    shown = {k: v for k, v in res.items() if k not in ("cost", "fan_out", "level3_pass")}
    print(json.dumps(shown, indent=1, default=str))


if __name__ == "__main__":
    main()
