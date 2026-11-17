# ruff: noqa: E501
"""Grade study runs: the judges copy values, code scores them, labels and grounding.

For each answer:
1. The two judges copy every must-have value, with a flag when the answer says
   a value isn't available or gives it only as a stand-in. Code scores the
   values with the must-have checks and the accepted alternatives.
2. If the judges differ on any item, or on any field's flags, the tiebreaker
   reads the answer too and each field takes the reading at least two of the
   three share. Every tiebreaker call goes to a review file for a person.
3. A behavior label for RQ3, from the agreed flags (see label()).
4. Grounding: whether each copied number, sha or name appears in the run's
   tool results (see grounded()). Values the agent worked out itself from
   tool output don't appear there, so this is a lower bound, reported as such.

Answers that are empty are not sent to the judges: every field is missing.
Runs that ended on a provider failure are not graded, since they are rerun.
The freeze check must pass before study runs are graded.

Results are appended to grading_results/<name>/graded.jsonl, so a stopped
grading resumes where it left off. A person then reviews every tiebreaker call
in tiebreak_review.md, and --apply-review writes final.jsonl, the grades the
analysis uses.

Usage:
  uv run --env-file .env python scripts/grading/grade_study.py NAME RUN_SET [RUN_SET ...]
  uv run --env-file .env python scripts/grading/grade_study.py --practice NAME RUN_SET [...]
  uv run python scripts/grading/grade_study.py [--practice] --apply-review NAME
"""

import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
sys.path.insert(0, str(ROOT / "scripts" / "grading"))
sys.path.insert(0, str(ROOT / "scripts" / "answer_keys"))
import hand_sheet as hs  # noqa: E402
from must_haves import check  # noqa: E402
from try_judges import JUDGES, TIEBREAK, ask  # noqa: E402

from repo_investigator.grading.extract import FIELDS, to_guess  # noqa: E402

GRADED_STOPS = ("answered", "budget", "model_output_failure")
LABELS = ("no_answer", "gives_values", "stand_in", "no_values")


def load_keys(practice: bool):
    """question id -> (question, key, accepted alternatives)."""
    if practice:
        keys = json.loads((ROOT / "answer_keys" / "practice_keys.json").read_text())
        questions = json.loads((ROOT / "questions" / "practice.json").read_text())
        return {q["id"]: (q, keys[q["id"]]["key"], []) for q in questions}
    keys = json.loads((ROOT / "answer_keys" / "keys_primary.json").read_text())
    alts = json.loads((ROOT / "answer_keys" / "accepted_alternatives.json").read_text())
    questions = [q for q in json.loads((ROOT / "questions" / "questions.json").read_text()) if q["in_study"]]
    return {
        q["id"]: (q, keys[q["template"]][q["repo"]], alts.get(q["template"], {}).get(q["repo"], []))
        for q in questions
    }


def reading(template: str, ext: dict) -> dict:
    """What one judge read for each field: (not available, stand-in, value), comparable across judges."""
    out = {}
    guess = to_guess(template, ext)
    for name in FIELDS[template]:
        item = ext.get(name) or {}
        value = guess[name] if not item.get("stand_in") else item.get("value")
        if isinstance(value, float):
            value = round(value, 6)
        if isinstance(value, str):
            value = value.strip().lower()
        out[name] = (
            bool(item.get("not_available")) or item.get("value") is None,
            bool(item.get("stand_in")),
            value,
        )
    return out


def label(final_answer: str | None, fields: dict) -> str:
    """The RQ3 behavior of one answer, from the agreed field readings.

    no_answer: the run ended with no answer text.
    gives_values: at least one value is given as the real thing. If the answer
      fails, this is a wrong answer that doesn't say anything is missing.
    stand_in: no real values, but at least one stand-in the answer labels as such.
    no_values: no values at all; the answer says the data is missing or declines.
    """
    if not (final_answer or "").strip():
        return "no_answer"
    if any(not na and not si for na, si, _ in fields.values()):
        return "gives_values"
    if any(si and not na for na, si, _ in fields.values()):
        return "stand_in"
    return "no_values"


NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
# Factors that turn a number from a tool result into the answer's unit, for each unit the
# tool might have used: the same unit, a fraction or percent, or another time unit.
SCALES = {
    "percent": (1, 100),
    "fraction": (1, 0.01),
    "hours": (1, 1 / 60, 1 / 3600, 24),
    "minutes": (1, 60, 1 / 60, 24 * 60),
    "seconds": (1, 60, 3600),
    "days": (1, 1 / 24, 1 / (24 * 60), 1 / 86400),
}


def decimals(v: float) -> int:
    s = repr(float(v))
    return 0 if float(v).is_integer() else len(s.split(".")[1]) if "e" not in s else 6


def tool_text(run: dict) -> str:
    return "\n".join(s["content"] or "" for s in run["steps"] if s["step_type"] == "tool_result")


def grounded(template: str, ext: dict, text: str) -> dict:
    """field -> True/False for each copied number, sha or name; verdicts are skipped.

    A number counts as found if some number in the tool results rounds to it at
    the answer's own precision, allowing a percent/fraction or time unit change.
    Counts must match exactly. A sha counts if its first 7 or more characters
    appear; a name if it appears as written.
    """
    numbers = [float(n) for n in NUMBER.findall(text)]
    low = text.lower()
    out = {}
    for name, (kind, _) in FIELDS[template].items():
        item = ext.get(name) or {}
        v = item.get("value")
        if v is None or kind.startswith("verdict"):
            continue
        if kind == "sha":
            s = str(v).strip().lower()
            out[name] = len(s) >= 7 and s in low
        elif kind == "text":
            out[name] = str(v).strip().lower() in low
        else:
            unit = item.get("unit")
            if unit == "count" or kind == "number:count":
                out[name] = any(n == v for n in numbers)
                continue
            d = decimals(v)
            found = False
            for scale in SCALES.get(unit, (1,)):
                # The tool value, written in the answer's unit, must round to what the answer says.
                tol = 0.5 * 10**-d + 1e-9
                if any(abs(n * scale - v) <= tol for n in numbers):
                    found = True
                    break
            out[name] = found
    return out


def had_data(run: dict) -> bool:
    """Whether any tool call returned data rather than an error."""
    for s in run["steps"]:
        if s["step_type"] != "tool_result":
            continue
        try:
            r = json.loads(s["content"])
        except (TypeError, ValueError):
            return True
        if isinstance(r, dict) and ("error" in r or ("stdout" in r and not str(r["stdout"]).strip())):
            continue
        return True
    return False


def grade(client, run: dict, keys: dict) -> dict:
    q, key, alts = keys[run["question_id"]]
    t = q["template"]
    out = {
        "run_set": run["run_set"],
        "run_id": run["run_id"],
        "question_id": q["id"],
        "template": t,
        "repo": q["repo"],
        "setup": run["setup"],
        "model": run["model"],
        "attempt": run["attempt"],
        "stop_reason": run["stop_reason"],
        "judges": {},
        "cost": 0.0,
    }
    answer = run["final_answer"]
    if not (answer or "").strip():
        empty = {n: {"value": None, "not_available": True, "stand_in": False} for n in FIELDS[t]}
        out.update(
            items=check(t, key, to_guess(t, empty), alts),
            disagreed=[],
            label="no_answer",
            grounded={},
            had_data=had_data(run),
        )
        out["passed"] = all(out["items"].values())
        return out

    readings, items = {}, {}
    for name, judge in JUDGES.items():
        ext, cost, provider = ask(client, judge, t, q["question"], answer)
        out["cost"] += cost
        out["judges"][name] = {"extracted": ext, "provider": provider}
        if "error" in ext:
            out["error"] = f"{name}: {ext['error']}"
            return out
        readings[name] = reading(t, ext)
        items[name] = check(t, key, to_guess(t, ext), alts)
    a, b = list(JUDGES)
    disagreed = sorted(
        {f"item: {i}" for i in items[a] if items[a][i] != items[b][i]}
        | {f"field: {f}" for f in readings[a] if readings[a][f][:2] != readings[b][f][:2]}
    )
    final_ext, final_items = out["judges"][a]["extracted"], items[a]
    if disagreed:
        ext, cost, provider = ask(client, TIEBREAK, t, q["question"], answer)
        out["cost"] += cost
        out["judges"]["tiebreak"] = {"extracted": ext, "provider": provider}
        if "error" in ext:
            out["error"] = f"tiebreak: {ext['error']}"
            return out
        readings["tiebreak"] = reading(t, ext)
        items["tiebreak"] = check(t, key, to_guess(t, ext), alts)
        # Each field takes the reading at least two of the three share. If all three differ, the
        # first judge's reading stands and the person reviewing the tiebreaker calls sees it.
        # Items are then scored from these fields, so items and fields always agree.
        final_ext = {}
        for f in FIELDS[t]:
            agree = [n for n in readings if readings[n][f] == readings["tiebreak"][f]]
            pick = "tiebreak" if len(agree) >= 2 else a
            final_ext[f] = out["judges"][pick]["extracted"].get(f)
        final_items = check(t, key, to_guess(t, final_ext), alts)
    fields = reading(t, final_ext)
    out.update(
        items=final_items,
        passed=all(final_items.values()),
        disagreed=disagreed,
        final_extracted=final_ext,
        label=label(answer, fields),
        grounded=grounded(t, final_ext, tool_text(run)),
        had_data=had_data(run),
    )
    return out


def review_file(results: list[dict], keys: dict, path: Path) -> None:
    """Every tiebreaker call, with the answer and the three readings, for a person to check.
    No study model or setup names, so the review is blind."""
    lines = [
        "# Tiebreaker calls to review",
        "",
        "In each answer below, the two main judges (A and B) read something differently, and the tiebreaker (C) decided.",
        'Read the answer. Then after "your call:" write ok if the decision is what the answer says, or else the right value,',
        "written as on the hand sheet: a number in the unit in brackets, na, proxy and a value, or unclear.",
        "",
    ]
    calls = [r for r in results if r.get("disagreed") and not r.get("error")]
    for n, r in enumerate(calls, 1):
        q, t = keys[r["question_id"]][0], r["template"]
        lines += [f"## T{n:03d}", "", "### Question", "", q["question"], "", "### Answer", ""]
        lines += ["```text", r.get("answer", ""), "```", "", "### Readings", ""]
        for f, (kind, desc) in FIELDS[t].items():
            a, b, c = (hs.judge_value(t, f, r["judges"][x]["extracted"].get(f)) for x in r["judges"])
            d = hs.judge_value(t, f, r["final_extracted"].get(f))
            lines.append(
                f"- {f} ({desc}) [{hs.unit_label(kind)}] A: {a} | B: {b} | C: {c} | decision: {d} | your call: "
            )
        lines.append("")
    path.write_text("\n".join(lines))
    (path.parent / "review_map.json").write_text(
        json.dumps({f"T{n:03d}": [r["run_set"], r["run_id"]] for n, r in enumerate(calls, 1)}, indent=1)
        + "\n"
    )


def apply_review(name: str, keys: dict) -> None:
    """Apply the person's calls from tiebreak_review.md and write final.jsonl, the grades the
    analysis uses. Fields marked ok keep the decision; any other mark replaces it."""
    out_dir = ROOT / "grading_results" / name
    graded = {}
    for line in (out_dir / "graded.jsonl").read_text().splitlines():
        r = json.loads(line)
        if not r.get("error"):
            graded[(r["run_set"], r["run_id"])] = r
    review_map = json.loads((out_dir / "review_map.json").read_text())
    calls, tid = {}, None
    for line in (out_dir / "tiebreak_review.md").read_text().splitlines():
        if m := re.match(r"## (T\d+)$", line):
            tid = m.group(1)
        elif tid and (m := re.match(r"- (\w+) \(.*\) \[(.*)\] A: .* \| your call:(.*)$", line)):
            calls.setdefault(tid, {})[m.group(1)] = (m.group(2), m.group(3).strip().lower())
    blank = [f"{t} {f}" for t, fs in calls.items() for f, (_, mark) in fs.items() if not mark]
    if blank or set(calls) != set(review_map):
        raise SystemExit(f"Review not finished. Blank: {blank[:10]}")
    runs = {}
    for run_set in {k[0] for k in graded}:
        for line in (ROOT / "study_runs" / run_set / "runs.jsonl").read_text().splitlines():
            r = json.loads(line)
            runs[(r["run_set"], r["run_id"])] = r
    changed = 0
    for tid, ref in review_map.items():
        r = graded[tuple(ref)]
        q, key, alts = keys[r["question_id"]]
        t = r["template"]
        for f, (unit, mark) in calls[tid].items():
            if mark != "ok":
                r["final_extracted"][f] = hs.parse_value(unit, mark)
                changed += 1
        run = runs[tuple(ref)]
        r["items"] = check(t, key, to_guess(t, r["final_extracted"]), alts)
        r["passed"] = all(r["items"].values())
        r["label"] = label(run["final_answer"], reading(t, r["final_extracted"]))
        r["grounded"] = grounded(t, r["final_extracted"], tool_text(run))
        r["reviewed"] = True
    with (out_dir / "final.jsonl").open("w") as f:
        for r in graded.values():
            f.write(json.dumps(r, default=str) + "\n")
    print(
        f"{len(review_map)} tiebreaker calls reviewed, {changed} fields changed, {len(graded)} answers in final.jsonl"
    )


def freeze_problems() -> list[str]:
    from freeze_keys import FREEZE, KINDS, current  # noqa: PLC0415

    frozen, now = json.loads(FREEZE.read_text()), current()
    return [f"{k} {n}" for k in KINDS for n in frozen.get(k, {}) if frozen[k][n] != now[k].get(n)]


def main():
    args = sys.argv[1:]
    practice = "--practice" in args
    review = "--apply-review" in args
    args = [a for a in args if a not in ("--practice", "--apply-review")]
    name, run_sets = args[0], args[1:]
    if review:
        apply_review(name, load_keys(practice))
        return
    if not practice and (problems := freeze_problems()):
        raise SystemExit("Not grading, these differ from the freeze:\n- " + "\n- ".join(problems))
    keys = load_keys(practice)
    runs = [
        json.loads(line)
        for rs in run_sets
        for line in (ROOT / "study_runs" / rs / "runs.jsonl").read_text().splitlines()
    ]
    skipped = [r for r in runs if r["question_id"] not in keys or r["stop_reason"] not in GRADED_STOPS]
    runs = [r for r in runs if r not in skipped]
    out_dir = ROOT / "grading_results" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    graded_file = out_dir / "graded.jsonl"
    done = {}
    if graded_file.exists():
        for line in graded_file.read_text().splitlines():
            r = json.loads(line)
            if not r.get("error"):
                done[(r["run_set"], r["run_id"])] = r
    todo = [r for r in runs if (r["run_set"], r["run_id"]) not in done]
    print(
        f"{len(runs)} runs to grade, {len(done)} already graded, {len(skipped)} not graded (other questions or provider failures)"
    )

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=180,
        max_retries=0,
    )
    lock = threading.Lock()

    def one(run):
        r = grade(client, run, keys)
        r["answer"] = run["final_answer"] or ""
        with lock, graded_file.open("a") as f:
            f.write(json.dumps(r, default=str) + "\n")
        return r

    with ThreadPoolExecutor(8) as pool:
        new = list(pool.map(one, todo))
    results = list(done.values()) + new
    errors = [r for r in results if r.get("error")]
    ok = [r for r in results if not r.get("error")]
    review_file(ok, keys, out_dir / "tiebreak_review.md")
    print(f"graded {len(ok)}, judge errors {len(errors)} (rerun the same command to retry them)")
    print(f"cost this session ${sum(r['cost'] for r in new):.4f}")
    print(f"tiebreaker used on {sum(bool(r['disagreed']) for r in ok)} answers")
    print(f"passed {sum(r['passed'] for r in ok)}/{len(ok)}")
    print("labels: " + ", ".join(f"{lab} {sum(r['label'] == lab for r in ok)}" for lab in LABELS))


if __name__ == "__main__":
    main()
