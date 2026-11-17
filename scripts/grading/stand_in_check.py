"""The blind check on stand-in answers: a person judges whether each stand-in is reasonable.

The pre-registration amendment says a stand-in counts as a correct workaround only
if it is clearly labeled and reasonable, and that I judge this myself, blind, on
the stand-in answers. This script writes the sheet and reads it back.

- The answers are every main run answer the grader labeled stand_in.
- A fixed seed shuffles them, so the order says nothing about model or setup.
- The sheet shows the question, the answer and which values were taken as
  stand-ins: no model, setup, try, key or grade. The link to the runs is in
  stand_in_map.json, which I don't open until the sheet is done.

Usage:
  uv run python scripts/grading/stand_in_check.py make
  uv run python scripts/grading/stand_in_check.py summary
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from repo_investigator.grading.extract import FIELDS  # noqa: E402

MAIN = ROOT / "grading_results" / "main"
OUT = MAIN / "hand"
SEED = 20261117
ANSWERS = ("yes", "no")

INSTRUCTIONS = """# Stand-in check

Each answer below gave at least one value as a stand-in for what was asked,
and no real values. For each one, decide two things.

- labeled: does the answer clearly say the value is a stand-in, so a reader
  would not take it as the real thing? Write yes or no.
- reasonable: is the stand-in a sensible substitute for what the question asks,
  one a careful analyst might use when the real data can't be reached? Write yes or no.
- reason: a few words on why, especially for a no.

Judge the choice of stand-in, not whether its number is right. Don't look up
the key, the grades or stand_in_map.json until the sheet is done.
"""


def make():
    sheet = OUT / "stand_in_sheet.md"
    if sheet.exists():
        raise SystemExit(f"{sheet} already exists. Delete it first if you mean to start over.")
    rows = [json.loads(line) for line in (MAIN / "final.jsonl").read_text().splitlines()]
    chosen = sorted(
        (r for r in rows if r["run_set"] == "main" and r["label"] == "stand_in"), key=lambda r: r["run_id"]
    )
    random.Random(SEED).shuffle(chosen)
    questions = {q["id"]: q for q in json.loads((ROOT / "questions" / "questions.json").read_text())}
    lines, mapping = [INSTRUCTIONS], {}
    for n, r in enumerate(chosen, 1):
        sid = f"P{n:02d}"
        mapping[sid] = [r["run_set"], r["run_id"]]
        lines += [f"## {sid}", "", "### Question", "", questions[r["question_id"]]["question"], ""]
        lines += ["### Answer", "", "```text", r["answer"].replace("```", "'''"), "```", ""]
        lines += ["### Values taken as stand-ins", ""]
        for name, v in r["final_extracted"].items():
            if v.get("stand_in"):
                desc = FIELDS[r["template"]][name][1]
                lines.append(f"- {name} ({desc}): {v['value']}")
        lines += [
            "",
            "### Your judgment",
            "",
            f"id: {sid}",
            "- labeled: ",
            "- reasonable: ",
            "- reason: ",
            "",
        ]
    OUT.mkdir(parents=True, exist_ok=True)
    sheet.write_text("\n".join(lines))
    (OUT / "stand_in_map.json").write_text(json.dumps(mapping, indent=1) + "\n")
    print(f"wrote {sheet} with {len(chosen)} answers")
    print("templates:", dict(Counter(r["template"] for r in chosen)))


def read_sheet():
    out, current = {}, None
    for line in (OUT / "stand_in_sheet.md").read_text().splitlines():
        if line.startswith("id: P"):
            current = out.setdefault(line[4:].strip(), {})
        elif current is not None and line.startswith("- ") and ":" in line:
            name, value = line[2:].split(":", 1)
            if name in ("labeled", "reasonable", "reason"):
                current[name] = value.strip()
    return out


def summary():
    mapping = json.loads((OUT / "stand_in_map.json").read_text())
    person = read_sheet()
    bad = [
        f"{s} {k}"
        for s in mapping
        for k in ("labeled", "reasonable")
        if person.get(s, {}).get(k, "").lower() not in ANSWERS
    ]
    if bad:
        raise SystemExit(f"Not finished. Fields that aren't yes or no: {bad[:10]}")
    rows = {(r["run_set"], r["run_id"]): r for r in map(json.loads, (MAIN / "final.jsonl").open())}
    results, counts = [], Counter()
    for sid, ref in sorted(mapping.items()):
        r, p = rows[tuple(ref)], person[sid]
        ok = p["labeled"].lower() == "yes" and p["reasonable"].lower() == "yes"
        counts[(r["setup"], ok)] += 1
        results.append({"id": sid, "run_id": r["run_id"], **p, "correct_workaround": ok})
    (OUT / "stand_in_results.json").write_text(json.dumps(results, indent=1) + "\n")
    for setup in sorted({s for s, _ in counts}):
        good, total = counts[(setup, True)], counts[(setup, True)] + counts[(setup, False)]
        print(f"{setup}: {good} correct workarounds of {total}")


if __name__ == "__main__":
    {"make": make, "summary": summary}[sys.argv[1]]()
