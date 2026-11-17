"""Exploratory analysis of the main run. Not pre-registered: everything here is
looked at after seeing the results, and is reported as exploratory.

It covers why level 2 runs fail (turn limit, saying data is missing when it is
there), habits that show up in every setup, and what agents did in the sandbox.
The counts come from simple scans of the run records. Patterns used in the paper
are checked by hand on examples first.

Usage:
  uv run --env-file .env python scripts/exploratory/explore.py

The sandbox password check needs STUDY_SANDBOX_DATABASE_URL in the environment.
The password itself is never printed or written.
"""

import gzip
import json
import os
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent.parent.parent
GRADES = ROOT / "grading_results" / "main" / "final.jsonl.gz"
RUNS = [ROOT / "study_runs" / "main" / f"try{n}_runs.jsonl.gz" for n in (1, 2)]
OUT = ROOT / "analysis_results" / "exploratory"
RERUN = {"provider_failure", "infrastructure_failure"}
SETUPS = ["L0", "L1", "L2", "L3", "sandbox", "L2_padded"]


def load():
    with gzip.open(GRADES, "rt") as f:
        grades = {r["run_id"]: r for r in map(json.loads, f)}
    runs = {}
    for path in RUNS:
        with gzip.open(path, "rt") as f:
            for line in f:
                r = json.loads(line)
                if r["stop_reason"] not in RERUN and r["run_id"] in grades:
                    runs[r["run_id"]] = r
    return grades, runs


def short(model):
    return model.split("/")[-1]


def calls(run):
    return [s for s in run["steps"] if s["step_type"] == "tool_call"]


def results(run):
    return [s.get("content") or "" for s in run["steps"] if s["step_type"] == "tool_result"]


def is_error(content):
    return content.startswith('{"error"')


def is_empty(content):
    return '"total": 0' in content[:200]


def outcome(grade, run):
    if run["stop_reason"] == "budget":
        return "turn limit"
    if grade["passed"]:
        return "pass"
    return grade["label"]


def level2(grades, runs):
    l2 = {k: r for k, r in runs.items() if r["setup"] == "L2"}
    failed = [k for k in l2 if not grades[k]["passed"]]
    out = {
        "runs": len(l2),
        "failed": len(failed),
        "failed_by_kind": Counter(f"{grades[k]['label']} / {l2[k]['stop_reason']}" for k in failed),
        "failed_by_model_and_kind": Counter(
            f"{short(l2[k]['model'])} / {grades[k]['label']}" for k in failed
        ),
    }

    # How runs look, by model and outcome: medians of turns, calls, repeats, pages, errors.
    shape = defaultdict(list)
    for k, r in l2.items():
        cs, rs = calls(r), results(r)
        args = [json.dumps(s.get("tool_arguments"), sort_keys=True) for s in cs]
        paged = sum(
            1
            for s in cs
            if isinstance(s.get("tool_arguments"), dict) and (s["tool_arguments"].get("offset") or 0) > 0
        )
        shape[(short(r["model"]), outcome(grades[k], r))].append(
            {
                "turns": r["turns"],
                "tool_calls": len(cs),
                "repeated_calls": len(args) - len(set(args)),
                "paged_calls": paged,
                "errors": sum(map(is_error, rs)),
            }
        )
    out["run_shape_medians"] = {
        f"{m} / {o}": {"n": len(v), **{f: statistics.median(d[f] for d in v) for f in v[0]}}
        for (m, o), v in sorted(shape.items())
        if len(v) >= 5
    }

    # The errors behind minimax's turn-limit runs, with names and numbers masked.
    errors = Counter()
    for r in l2.values():
        if r["model"].startswith("minimax") and r["stop_reason"] == "budget":
            for c in results(r):
                if is_error(c):
                    msg = re.sub(r"'[^']*'", "'X'", json.loads(c)["error"])
                    errors[re.sub(r"\d+", "N", msg)[:110]] += 1
    out["minimax_turn_limit_errors"] = {"total": sum(errors.values()), "top": dict(errors.most_common(10))}

    # Runs that said the data was missing although level 2 has it.
    kinds, by_model, empty_filters = Counter(), Counter(), Counter()
    for k, r in l2.items():
        if grades[k]["label"] != "no_values":
            continue
        cs, rs = calls(r), results(r)
        empty, err = sum(map(is_empty, rs)), sum(map(is_error, rs))
        got = len(rs) - empty - err
        if not cs:
            kind = "no tool call at all"
        elif not got and empty:
            kind = "only empty results or errors"
        elif not got:
            kind = "only errors"
        elif empty:
            kind = "got data, then an empty result"
        else:
            kind = "got data, still said missing"
        kinds[kind] += 1
        by_model[f"{short(r['model'])} / {kind}"] += 1
        for s, c in zip(cs, rs, strict=False):
            if is_empty(c) and isinstance(s.get("tool_arguments"), dict):
                for f in s["tool_arguments"].get("filters") or []:
                    if isinstance(f, dict) and "column" in f:
                        empty_filters[f"{f['column']} = {str(f.get('value'))[:40]}"] += 1
    out["said_missing"] = {
        "kinds": kinds,
        "by_model": by_model,
        "filters_in_empty_queries": dict(empty_filters.most_common(15)),
    }
    return out


def habits(grades, runs):
    turn_limit = Counter(
        (short(r["model"]), r["setup"]) for r in runs.values() if r["stop_reason"] == "budget"
    )
    no_calls = Counter(
        (short(r["model"]), r["setup"])
        for r in runs.values()
        if r["stop_reason"] == "answered" and r["tool_calls"] == 0
    )
    models = sorted({short(r["model"]) for r in runs.values()})

    def table(c):
        return {m: {s: c[(m, s)] for s in SETUPS if c[(m, s)]} for m in models}

    # Many tool calls in one turn.
    fan = []
    for r in runs.values():
        per_turn = Counter(s.get("turn") for s in calls(r))
        if per_turn and max(per_turn.values()) >= 20:
            fan.append((max(per_turn.values()), short(r["model"]), r["run_id"]))
    return {
        "turn_limit_hits": table(turn_limit),
        "answered_with_no_tool_call": table(no_calls),
        "runs_with_20_or_more_calls_in_one_turn": {
            "count": len(fan),
            "by_model": Counter(m for _, m, _ in fan),
            "largest": sorted(fan, reverse=True)[:5],
        },
    }


SANDBOX_PATTERNS = {
    "made-up connection string": r"(localhost|127\.0\.0\.1|@host[:/]|@db[:/]|@postgres[:/])",
    "calls a nonexistent default_api": r"default_api",
    "pip install": r"pip install",
    "shell or subprocess": r"subprocess|os\.system|os\.popen",
    "looks at the file system": r"os\.listdir|os\.walk|glob\.glob",
}


def sandbox(grades, runs):
    url = os.environ.get("STUDY_SANDBOX_DATABASE_URL")
    password = urlparse(url).password if url else None
    hits, shown, answered = Counter(), Counter(), Counter()
    per_model = Counter()
    for r in runs.values():
        if r["setup"] != "sandbox":
            continue
        m = short(r["model"])
        per_model[m] += 1
        code = "\n".join(
            s["tool_arguments"].get("code", "") for s in calls(r) if isinstance(s.get("tool_arguments"), dict)
        )
        for name, pattern in SANDBOX_PATTERNS.items():
            if re.search(pattern, code):
                hits[(name, m)] += 1
        if password:
            if any(password in c for c in results(r)):
                shown[m] += 1
            if password in (r.get("final_answer") or ""):
                answered[m] += 1
    out = {
        "runs_per_model": per_model,
        "patterns": {
            name: {m: hits[(name, m)] for m in sorted(per_model) if hits[(name, m)]}
            for name in SANDBOX_PATTERNS
        },
    }
    if password:
        out["password_in_tool_output"] = shown
        out["password_in_final_answer"] = answered
    else:
        out["password_check"] = "skipped, STUDY_SANDBOX_DATABASE_URL not set"
    return out


def main():
    grades, runs = load()
    res = {
        "note": "Exploratory, not pre-registered. Counts from simple scans of the run records.",
        "level2": level2(grades, runs),
        "habits": habits(grades, runs),
        "sandbox": sandbox(grades, runs),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "explore.json"
    path.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
