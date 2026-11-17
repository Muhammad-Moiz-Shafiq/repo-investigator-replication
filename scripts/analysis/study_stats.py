"""The pre-registered statistics for the main run.

This follows the analysis plan in PRE_REGISTRATION_AMENDMENT_1.md. The plan left a
few details open, and they are fixed here before the script is run on the real grades:

- The bootstrap resamples whole templates with replacement, 10,000 times, with a
  fixed seed. Each drawn template brings all of its questions.
- The 95% interval is the 2.5th to 97.5th percentile of the resampled differences.
- The p-value is two-sided. The resampled differences are shifted so their mean is
  zero, and p is the share of them at least as far from zero as the observed one.
  The smallest possible p is therefore 1 in 10,000, reported as p < 0.0001.
- Holm's method adjusts the three RQ2 steps together and the four RQ1 comparisons
  together.
- RQ3 shares and their intervals use the same template bootstrap, on the share of
  runs per question.

The score of a question in a setup is the share of its runs that pass, over the
5 models and 2 tries. A run with no answer counts as a failure.

Usage:
  uv run python scripts/analysis/study_stats.py            # real grades
  uv run python scripts/analysis/study_stats.py --shuffled # test on shuffled setups
"""

import argparse
import gzip
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent.parent
GRADES = ROOT / "grading_results" / "main" / "final.jsonl.gz"
STAND_INS = ROOT / "grading_results" / "main" / "hand" / "stand_in_results.json"
RUNS = [ROOT / "study_runs" / "main" / f"try{n}_runs.jsonl.gz" for n in (1, 2)]
OUT = ROOT / "analysis_results" / "main"
SEED = 20261117
REPS = 10_000
LEVELS = ["L0", "L1", "L2", "L3"]
RERUN = {"provider_failure", "infrastructure_failure"}


def load_grades():
    with gzip.open(GRADES, "rt") as f:
        return [json.loads(line) for line in f]


def load_runs():
    """The final record of every run, without the older records of redone runs."""
    final = {}
    for path in RUNS:
        with gzip.open(path, "rt") as f:
            for line in f:
                r = json.loads(line)
                if r["stop_reason"] not in RERUN:
                    final[r["run_id"]] = r
    return final


def per_question(rows, setup, value):
    """For one setup: {question: (template, mean of value over its runs)}."""
    by_q = defaultdict(list)
    template = {}
    for r in rows:
        if r["setup"] == setup:
            by_q[r["question_id"]].append(value(r))
            template[r["question_id"]] = r["template"]
    return {q: (template[q], float(np.mean(v))) for q, v in by_q.items()}


def by_template(scores):
    groups = defaultdict(list)
    for t, s in scores.values():
        groups[t].append(s)
    return [np.array(v) for v in groups.values()]


def boot_mean(groups, rng):
    """Observed mean over questions, and REPS means from resampled templates."""
    sums = np.array([g.sum() for g in groups])
    counts = np.array([len(g) for g in groups])
    observed = sums.sum() / counts.sum()
    draws = rng.integers(0, len(groups), size=(REPS, len(groups)))
    resampled = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return observed, resampled


def describe(observed, resampled, test=True):
    lo, hi = np.percentile(resampled, [2.5, 97.5])
    out = {"estimate": round(observed, 4), "ci95": [round(lo, 4), round(hi, 4)]}
    if test:
        shifted = resampled - resampled.mean()
        out["p"] = max(float(np.mean(np.abs(shifted) >= abs(observed))), 1 / REPS)
    return out


def compare(rows, a, b, value, rng):
    """Mean over shared questions of score(a) minus score(b)."""
    sa, sb = per_question(rows, a, value), per_question(rows, b, value)
    diff = {q: (sa[q][0], sa[q][1] - sb[q][1]) for q in sa.keys() & sb.keys()}
    observed, resampled = boot_mean(by_template(diff), rng)
    out = describe(observed, resampled)
    out.update({"setups": f"{a} minus {b}", "questions": len(diff)})
    return out


def holm(results):
    order = sorted(range(len(results)), key=lambda i: results[i]["p"])
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(results) - rank) * results[i]["p"]))
        results[i]["p_holm"] = running
    return results


def share(rows, setup, value, rng):
    observed, resampled = boot_mean(by_template(per_question(rows, setup, value)), rng)
    return describe(observed, resampled, test=False)


def passed(r):
    return float(r["passed"])


def item_share(r):
    return float(np.mean(list(r["items"].values()))) if r["items"] else 0.0


def analyse(rows, runs, workarounds):
    rng = np.random.default_rng(SEED)
    main = [r for r in rows if r["setup"] != "L2_padded"]
    res = {"plan": "PRE_REGISTRATION_AMENDMENT_1.md", "seed": SEED, "reps": REPS}

    res["scores"] = {
        s: {
            "pass": share(main, s, passed, rng),
            "items": share(main, s, item_share, rng),
        }
        for s in LEVELS + ["sandbox"]
    }
    steps = list(zip(LEVELS, LEVELS[1:], strict=False))
    res["rq2"] = holm([compare(main, a, b, passed, rng) for a, b in steps])
    res["rq2_items"] = holm([compare(main, a, b, item_share, rng) for a, b in steps])
    res["rq1"] = holm([compare(main, "sandbox", lv, passed, rng) for lv in LEVELS])
    res["rq1_items"] = holm([compare(main, "sandbox", lv, item_share, rng) for lv in LEVELS])

    models = sorted({r["model"] for r in main})
    res["rq1_per_model"] = {}
    for m in models:
        mine = [r for r in main if r["model"] == m]
        res["rq1_per_model"][m] = [
            {k: v for k, v in compare(mine, "sandbox", lv, passed, rng).items() if k != "p"} for lv in LEVELS
        ]

    def silent_wrong(r):
        return float(r["label"] == "gives_values" and not r["passed"])

    def good_stand_in(r):
        return float(workarounds.get(r["run_id"], False))

    def bad_stand_in(r):
        return float(r["label"] == "stand_in" and not workarounds.get(r["run_id"], False))

    labels = ["no_answer", "gives_values", "stand_in", "no_values"]
    res["rq3"] = {}
    for s in ["L3", "sandbox"]:
        out = {lab: share(main, s, lambda r, lab=lab: float(r["label"] == lab), rng) for lab in labels}
        out["wrong_without_saying"] = share(main, s, silent_wrong, rng)
        out["stand_in_correct_workaround"] = share(main, s, good_stand_in, rng)
        out["stand_in_not_reasonable"] = share(main, s, bad_stand_in, rng)
        res["rq3"][s] = out
    res["rq3_wrong_without_saying_L3_minus_sandbox"] = compare(main, "L3", "sandbox", silent_wrong, rng)

    res["grounding"] = {}
    for s in LEVELS + ["sandbox", "L2_padded"]:
        mine = [r for r in rows if r["setup"] == s]
        values = [g for r in mine for g in (r.get("grounded") or {}).values()]
        res["grounding"][s] = {
            "values_copied": len(values),
            "share_found_in_tool_results": round(float(np.mean(values)), 4) if values else None,
            "share_of_runs_that_got_data": round(float(np.mean([bool(r["had_data"]) for r in mine])), 4),
        }

    # Agreement between tries: the same condition passing or failing both times.
    cond = {(r["question_id"], r["setup"], r["model"], r["attempt"]): r["passed"] for r in rows}
    same = [cond[k] == cond[k[:3] + (2,)] for k in cond if k[3] == 1 and k[:3] + (2,) in cond]
    res["tries"] = {
        "conditions": len(same),
        "same_result": round(float(np.mean(same)), 4),
        "pass_try1": round(float(np.mean([v for k, v in cond.items() if k[3] == 1])), 4),
        "pass_try2": round(float(np.mean([v for k, v in cond.items() if k[3] == 2])), 4),
    }

    side_models = sorted({r["model"] for r in rows if r["setup"] == "L2_padded"})
    side = [r for r in rows if r["model"] in side_models and r["setup"] in ("L2", "L2_padded")]
    res["side_check"] = compare(side, "L2_padded", "L2", passed, rng)
    res["side_check"]["models"] = side_models

    res["per_model"] = {}
    for m in models:
        mine = [runs[r["run_id"]] for r in rows if r["model"] == m and r["run_id"] in runs]
        stops = Counter(r["stop_reason"] for r in mine)
        res["per_model"][m] = {
            "runs": len(mine),
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in mine), 2),
            "median_tool_calls": float(np.median([r["tool_calls"] for r in mine])),
            "turn_budget_hits": stops["budget"],
            "model_output_failures": stops["model_output_failure"],
        }
    res["per_model_setup_pass"] = {
        m: {
            s: round(float(np.mean([r["passed"] for r in rows if r["model"] == m and r["setup"] == s])), 4)
            for s in LEVELS + ["sandbox", "L2_padded"]
            if any(r["model"] == m and r["setup"] == s for r in rows)
        }
        for m in models
    }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--shuffled", action="store_true", help="shuffle setups within each question, for a test run"
    )
    args = ap.parse_args()
    rows = load_grades()
    runs = load_runs()
    workarounds = {}
    if STAND_INS.exists():
        mapping = json.loads((STAND_INS.parent / "stand_in_map.json").read_text())
        for r in json.loads(STAND_INS.read_text()):
            workarounds[mapping[r["id"]][1]] = r["correct_workaround"]
    name = "stats.json"
    if args.shuffled:
        rng = random.Random(1)
        groups = defaultdict(list)
        for r in rows:
            if r["setup"] != "L2_padded":
                groups[(r["question_id"], r["model"])].append(r)
        for g in groups.values():
            setups = [r["setup"] for r in g]
            rng.shuffle(setups)
            for r, s in zip(g, setups, strict=True):
                r["setup"] = s
        name = "stats_shuffled_test.json"
        print("TEST RUN on shuffled setups. These numbers mean nothing.")
    res = analyse(rows, runs, workarounds)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(res, indent=1) + "\n")
    for key in ("rq2", "rq1"):
        for c in res[key]:
            print(key, c["setups"], c["estimate"], c["ci95"], "p", c["p"], "holm", round(c["p_holm"], 4))
    print("side", res["side_check"]["estimate"], res["side_check"]["ci95"], "p", res["side_check"]["p"])
    print("wrote", OUT / name)


if __name__ == "__main__":
    main()
