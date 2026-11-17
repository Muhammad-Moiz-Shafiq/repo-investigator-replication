"""The blind hand check on the main run: a person copies values from 20 answers.

The pre-registration amendment says I label a blind sample of 20 main run answers
myself and report how often the grader matches me. This script draws the sample,
writes the sheet, and compares my values with the final grades.

How the sample is drawn, fixed before drawing:
- The pool is every graded main run answer that has answer text, minus the 73
  answers I already saw in the tiebreaker review.
- A fixed seed shuffles the pool. One answer per template first (12), choosing
  the model picked least so far, then 8 more, balancing models and then setups.
- The sheet shows only the question and the answer: no model, setup, try,
  judge reading or grade. The link to the runs is in sample_map.json, which I
  don't open until the sheet is done.

Usage:
  uv run python scripts/grading/main_sample.py make
  uv run python scripts/grading/main_sample.py compare
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "grading"))
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
sys.path.insert(0, str(ROOT / "scripts" / "answer_keys"))
import grade_study as g  # noqa: E402
import hand_sheet as hs  # noqa: E402
from must_haves import check  # noqa: E402

from repo_investigator.grading.extract import FIELDS, to_guess  # noqa: E402

MAIN = ROOT / "grading_results" / "main"
OUT = MAIN / "hand"
SIZE = 20
SEED = 20261116


def graded():
    return [json.loads(line) for line in (MAIN / "final.jsonl").read_text().splitlines()]


def pick(pool):
    rng = random.Random(SEED)
    pool = sorted(pool, key=lambda r: r["run_id"])
    rng.shuffle(pool)
    chosen, models = [], Counter()
    for template in sorted({r["template"] for r in pool}, key=lambda t: int(t[1:])):
        options = [r for r in pool if r["template"] == template]
        best = min(options, key=lambda r: models[r["model"]])
        chosen.append(best)
        models[best["model"]] += 1
    setups = Counter(r["setup"] for r in chosen)
    while len(chosen) < SIZE:
        options = [r for r in pool if r not in chosen]
        best = min(options, key=lambda r: (models[r["model"]], setups[r["setup"]]))
        chosen.append(best)
        models[best["model"]] += 1
        setups[best["setup"]] += 1
    rng.shuffle(chosen)
    return chosen


def make():
    sheet = OUT / "sample_sheet.md"
    if sheet.exists():
        raise SystemExit(f"{sheet} already exists. Delete it first if you mean to start over.")
    reviewed = {tuple(v) for v in json.loads((MAIN / "review_map.json").read_text()).values()}
    pool = [r for r in graded() if r["answer"].strip() and (r["run_set"], r["run_id"]) not in reviewed]
    chosen = pick(pool)
    questions = {q["id"]: q for q in json.loads((ROOT / "questions" / "questions.json").read_text())}
    lines, mapping = [hs.INSTRUCTIONS], {}
    for n, r in enumerate(chosen, 1):
        sid = f"S{n:02d}"
        mapping[sid] = [r["run_set"], r["run_id"]]
        lines += [f"## {sid}", "", "### Question", "", questions[r["question_id"]]["question"], ""]
        lines += ["### Answer", "", "```text", r["answer"].replace("```", "'''"), "```", ""]
        lines += ["### Your values", "", f"id: {sid}"]
        lines += [
            f"- {name} ({desc}) [{hs.unit_label(kind)}]: "
            for name, (kind, desc) in FIELDS[r["template"]].items()
        ]
        lines.append("")
    OUT.mkdir(parents=True, exist_ok=True)
    sheet.write_text("\n".join(lines))
    (OUT / "sample_map.json").write_text(json.dumps(mapping, indent=1) + "\n")
    print(f"wrote {sheet} with {len(chosen)} answers from a pool of {len(pool)}")
    print("templates:", len({r["template"] for r in chosen}))
    print("models:", dict(Counter(r["model"].split("/")[-1] for r in chosen)))
    print("setups:", dict(Counter(r["setup"] for r in chosen)))


def read_sheet():
    out, current = {}, None
    for line in (OUT / "sample_sheet.md").read_text().splitlines():
        if line.startswith("id: S"):
            current = out.setdefault(line[4:].strip(), {})
        elif current is not None and line.startswith("- ") and "]:" in line:
            name = line[2:].split(" ", 1)[0]
            unit = line[line.rindex("[") + 1 : line.rindex("]:")]
            current[name] = hs.parse_value(unit, line.rsplit("]:", 1)[1].strip().lower())
    return out


def compare():
    mapping = json.loads((OUT / "sample_map.json").read_text())
    person = read_sheet()
    blank = [f"{s} {n}" for s, items in person.items() for n, i in items.items() if i.get("missing")]
    if blank or set(person) != set(mapping):
        raise SystemExit(f"Not finished. Blank fields: {blank[:10]}")
    keys = g.load_keys(practice=False)
    grades = {(r["run_set"], r["run_id"]): r for r in graded()}
    totals, rows = Counter(), []
    for sid, ref in sorted(mapping.items()):
        r = grades[tuple(ref)]
        t = r["template"]
        _, key, alts = keys[r["question_id"]]
        mine = check(t, key, to_guess(t, person[sid]), alts)
        my_label = g.label(r["answer"], g.reading(t, person[sid]))
        totals["answers"] += 1
        totals["grader passes the same as me"] += all(mine.values()) == r["passed"]
        totals["grader gives the same label as me"] += my_label == r["label"]
        for item, ok in mine.items():
            totals["items"] += 1
            totals["grader scores the item the same as me"] += ok == r["items"][item]
            if ok != r["items"][item]:
                rows.append(f"  {sid} {r['run_id']} '{item}': me={ok} grader={r['items'][item]}")
        if my_label != r["label"]:
            rows.append(f"  {sid} {r['run_id']} label: me={my_label} grader={r['label']}")
    (OUT / "sample_comparison.json").write_text(
        json.dumps({"totals": dict(totals), "differences": rows}, indent=1) + "\n"
    )
    for k, v in totals.items():
        base = "" if k in ("answers", "items") else "/" + str(totals["items" if "item" in k else "answers"])
        print(f"{k}: {v}{base}")
    print("\n".join(rows) or "No differences.")


if __name__ == "__main__":
    {"make": make, "compare": compare}[sys.argv[1]]()
