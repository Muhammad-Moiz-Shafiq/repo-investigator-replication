# ruff: noqa: E501
"""Check the judges against a person: a blind hand-grading sheet of practice answers.

make: picks 20 answers from the judge trial (grading_results/trial_r2_smoke.json)
  and writes grading_results/hand/sheet.md. Every template appears, and every
  model appears at least 3 times. The one answer the two judges disagreed on is
  included. The sheet shows the question and the answer only, never the model,
  the setup, the key or what a judge said, so the person grading isn't steered.
  Which answer is which goes in grading_results/hand/map.json.

judge: runs both judges once on the same 20 answers with the current extractor
  (the R4 fields changed after the trial) and saves what they copied. For the
  answers left blank on the sheet, it writes verify.md, where the person marks
  the judges' values right or wrong instead of copying them. That is faster,
  but seeing a value first can pull a person toward agreeing, so the report
  keeps copied and marked answers apart.

compare: scores the person and the judges with the same must-have checks and
  reports every item where they differ.

Usage:
  uv run python scripts/grading/hand_sheet.py make
  uv run --env-file .env python scripts/grading/hand_sheet.py judge
  uv run python scripts/grading/hand_sheet.py compare
"""

import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
sys.path.insert(0, str(ROOT / "scripts" / "grading"))
from must_haves import check  # noqa: E402

from repo_investigator.grading.extract import FIELDS, VERDICT_WORDS  # noqa: E402

HAND = ROOT / "grading_results" / "hand"
TRIAL = ROOT / "grading_results" / "trial_r2_smoke.json"
SIZE = 20
SEED = 20261024
INSTRUCTIONS = """# Hand grading sheet

This checks the judge models against a person. For each answer, read the question and the answer, then fill in every field with the value the answer gives. You are copying, not checking: write what the answer says, even if you think it's wrong.

How to fill in a field:
- Write the value after the colon, in the unit shown in brackets. Convert if the answer uses another unit (90 minutes is 1.5 for a field in hours, 0.35 is 35 for a field in percent).
- If the answer doesn't give the value or says it isn't available, write na.
- If the answer gives it only as a stand-in for what was asked and says so, write proxy and then the value, like proxy 12.5.
- For a verdict, write one of the words listed. If the answer says it in other words, pick the matching one (for a duration, slower is up). If it's unclear, write unclear.
- Use the RESULTS block at the end if there is one. If it disagrees with the text, the RESULTS block wins.
- For a commit, copy the SHA as written. For a module, write only its name.

Leave the lines that start with "id:" as they are.
"""


def trial_runs():
    """The judged trial records, each with the run it graded (matched by run set and run id)."""
    trial = json.loads(TRIAL.read_text())
    runs = {}
    for p in (ROOT / "study_runs").glob("*/runs.jsonl"):
        for line in p.read_text().splitlines():
            r = json.loads(line)
            runs[(r["run_set"], r["run_id"])] = r
    if "run_set" not in trial[0]:
        # The trial predates run_set in grading records; it graded these sets in this order.
        sets = sorted(p.parent.name for p in (ROOT / "study_runs").glob("prompt_v2_r2_*/runs.jsonl")) + [
            "smoke_v2"
        ]
        ok = ("answered", "budget", "model_output_failure")
        ordered = [
            r
            for s in sets
            for line in (ROOT / "study_runs" / s / "runs.jsonl").read_text().splitlines()
            for r in [json.loads(line)]
            if r["question_id"].startswith("P-") and r["stop_reason"] in ok
        ]
        assert [r["run_id"] for r in ordered] == [t["run_id"] for t in trial], "trial order changed"
        return [(t, r) for t, r in zip(trial, ordered, strict=True) if t.get("final")]
    return [(t, runs[(t["run_set"], t["run_id"])]) for t in trial if t.get("final")]


def pick(pairs):
    rng = random.Random(SEED)
    pool = pairs[:]
    rng.shuffle(pool)
    chosen = [p for p in pool if p[0].get("disagreed_items")][:1]
    models = Counter(p[1]["model"] for p in chosen)
    # One per template first, preferring the model picked least so far.
    for template in sorted({p[1]["template"] for p in pool}, key=lambda t: int(t[1:])):
        if any(p[1]["template"] == template for p in chosen):
            continue
        options = [p for p in pool if p[1]["template"] == template and p not in chosen]
        best = min(options, key=lambda p: models[p[1]["model"]])
        chosen.append(best)
        models[best[1]["model"]] += 1
    # Then fill up, again balancing models, and setups second.
    setups = Counter(p[1]["setup"] for p in chosen)
    while len(chosen) < SIZE:
        options = [p for p in pool if p not in chosen]
        best = min(options, key=lambda p: (models[p[1]["model"]], setups[p[1]["setup"]]))
        chosen.append(best)
        models[best[1]["model"]] += 1
        setups[best[1]["setup"]] += 1
    rng.shuffle(chosen)
    return chosen


def unit_label(kind):
    if kind.startswith("number"):
        return kind.split(":")[1]
    if kind.startswith("verdict"):
        return " / ".join(VERDICT_WORDS[kind.split(":")[1]])
    return {"sha": "commit SHA", "text": "name"}[kind]


def make():
    chosen = pick(trial_runs())
    HAND.mkdir(parents=True, exist_ok=True)
    sheet = Path(HAND / "sheet.md")
    if sheet.exists():
        raise SystemExit(f"{sheet} already exists. Delete it first if you mean to start over.")
    questions = {q["id"]: q for q in json.loads((ROOT / "questions" / "practice.json").read_text())}
    lines, mapping = [INSTRUCTIONS], {}
    for n, (_, run) in enumerate(chosen, 1):
        hid = f"H{n:02d}"
        mapping[hid] = {"run_set": run["run_set"], "run_id": run["run_id"]}
        lines += [
            f"## {hid}",
            "",
            "### Question",
            "",
            questions[run["question_id"]]["question"],
            "",
            "### Answer",
            "",
            "```text",
            (run["final_answer"] or "(no answer was given)").replace("```", "'''"),
            "```",
            "",
            "### Your values",
            "",
            f"id: {hid}",
        ]
        for name, (kind, desc) in FIELDS[run["template"]].items():
            lines.append(f"- {name} ({desc}) [{unit_label(kind)}]: ")
        lines.append("")
    sheet.write_text("\n".join(lines))
    (HAND / "map.json").write_text(json.dumps(mapping, indent=1) + "\n")
    print(f"wrote {sheet} with {len(chosen)} answers")
    print("models:", dict(Counter(r["model"].split("/")[-1] for _, r in chosen)))
    print("setups:", dict(Counter(r["setup"] for _, r in chosen)))
    print("templates:", len({r["template"] for _, r in chosen}))


def read_sheet():
    """The person's values as extractor output, so both go through the same conversion and checks."""
    out, current = {}, None
    for line in (HAND / "sheet.md").read_text().splitlines():
        if m := re.match(r"id: (H\d+)", line):
            current = out.setdefault(m.group(1), {})
        elif current is not None and (m := re.match(r"- (\w+) \(.*\) \[(.*)\]:(.*)$", line)):
            name, unit, raw = m.group(1), m.group(2), m.group(3).strip().lower()
            item = parse_value(unit, raw)
            current[name] = item
    return out


def judge_value(template, name, item):
    """One judge's extracted value, written the way the sheet asks a person to write it."""
    if not item or item.get("not_available"):
        return "na"
    if item.get("value") is None:
        return "unclear"
    from repo_investigator.grading.extract import to_guess  # noqa: PLC0415

    v = to_guess(template, {name: {**item, "stand_in": False}})[name]
    text = f"{v:g}" if isinstance(v, float) else str(v)
    return f"proxy {text}" if item.get("stand_in") else text


def judge():
    """Run both judges once on all 20 answers with the current extractor and save what they
    copied. Then write verify.md for the answers left blank on the sheet: the person marks the
    judges' values right or wrong instead of copying them."""
    import try_judges as tj  # noqa: PLC0415
    from openai import OpenAI  # noqa: PLC0415

    mapping = json.loads((HAND / "map.json").read_text())
    person = read_sheet()
    runs = {}
    for p in (ROOT / "study_runs").glob("*/runs.jsonl"):
        for line in p.read_text().splitlines():
            r = json.loads(line)
            runs[(r["run_set"], r["run_id"])] = r
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=180,
        max_retries=0,
    )
    judged, cost = {}, 0.0
    for hid, ref in sorted(mapping.items()):
        run = runs[(ref["run_set"], ref["run_id"])]
        q = tj.QUESTIONS[run["question_id"]]
        judged[hid] = {}
        for name, j in tj.JUDGES.items():
            ext, c, _ = tj.ask(client, j, q["template"], q["question"], run["final_answer"])
            judged[hid][name] = ext
            cost += c
    (HAND / "judged.json").write_text(json.dumps(judged, indent=1) + "\n")

    todo = [h for h in sorted(mapping) if any(i.get("missing") for i in person.get(h, {}).values())]
    sheet = (HAND / "sheet.md").read_text()
    lines = [VERIFY_INSTRUCTIONS]
    for hid in todo:
        run = runs[(mapping[hid]["run_set"], mapping[hid]["run_id"])]
        t = run["template"]
        block = sheet.split(f"## {hid}\n", 1)[1].split("### Your values", 1)[0]
        lines += [f"## {hid}", "", block.strip(), "", "### Check these", "", f"id: {hid}"]
        for name, (kind, desc) in FIELDS[t].items():
            values = [judge_value(t, name, judged[hid][j].get(name)) for j in tj.JUDGES]
            shown = values[0] if values[0] == values[1] else f"A = {values[0]}, B = {values[1]}"
            lines.append(f"- {name} ({desc}) [{unit_label(kind)}] judges say: {shown} | your mark: ")
        lines.append("")
    (HAND / "verify.md").write_text("\n".join(lines))
    print(
        f"judged 20 answers (${cost:.4f}); wrote verify.md with {len(todo)} answers to check: {', '.join(todo)}"
    )


VERIFY_INSTRUCTIONS = """# Check the judges' values

For each answer, read it, then look at what the judges copied from it. After "your mark:" write:
- ok, if the value is what the answer says (even if the answer itself is wrong),
- a or b, if the judges differ (A and B) and one of them is right,
- otherwise the right value, written as on the main sheet (a number in the unit in brackets, na, proxy and a value, or unclear).

na means the answer doesn't give that value. Use the RESULTS block at the end if there is one.
"""


def read_verify(judged):
    """The person's marks on verify.md, turned into values like read_sheet gives."""
    import try_judges as tj  # noqa: PLC0415

    out, current, hid = {}, None, None
    path = HAND / "verify.md"
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if m := re.match(r"id: (H\d+)", line):
            hid = m.group(1)
            current = out.setdefault(hid, {})
        elif current is not None and (
            m := re.match(r"- (\w+) \(.*\) \[(.*)\] judges say: (.*) \| your mark:(.*)$", line)
        ):
            name, unit, mark = m.group(1), m.group(2), m.group(4).strip().lower()
            names = list(tj.JUDGES)
            pick = {"ok": names[0], "a": names[0], "b": names[1]}.get(mark)
            if pick:
                item = dict(judged[hid][pick].get(name) or {"value": None, "not_available": True})
                item["unit"] = item.get("unit")
                current[name] = {**item, "marked": mark}
            else:
                current[name] = parse_value(unit, mark)
    return out


def parse_value(unit, raw):
    item = {"value": None, "unit": unit, "not_available": False, "stand_in": False}
    if raw in ("na", "n/a", ""):
        item["not_available"] = raw != ""
        item["missing"] = raw == ""
    elif raw != "unclear":
        if raw.startswith("proxy"):
            item["stand_in"], raw = True, raw[len("proxy") :].strip()
        if unit in ("percent", "minutes", "hours", "days", "lines", "count"):
            item["value"] = float(raw.replace("%", "").replace(",", ""))
        else:
            item["value"] = raw
    return item


def compare():
    """Score the person and both judges with the same checks and report every difference.
    Uses the judges' saved output from the judge step, so nothing is called again."""
    import try_judges as tj  # noqa: PLC0415

    from repo_investigator.grading.extract import to_guess  # noqa: PLC0415

    mapping = json.loads((HAND / "map.json").read_text())
    judged = json.loads((HAND / "judged.json").read_text())
    person = read_sheet()
    checked = read_verify(judged)
    for hid, items in checked.items():
        person[hid] = items
    blank = [f"{h} {n}" for h, items in person.items() for n, i in items.items() if i.get("missing")]
    if blank or set(person) != set(mapping):
        raise SystemExit(f"Not finished. Blank fields: {blank[:10]}")
    runs = {}
    for p in (ROOT / "study_runs").glob("*/runs.jsonl"):
        for line in p.read_text().splitlines():
            r = json.loads(line)
            runs[(r["run_set"], r["run_id"])] = r
    totals, rows = Counter(), []
    for hid, ref in sorted(mapping.items()):
        run = runs[(ref["run_set"], ref["run_id"])]
        t, key = run["template"], tj.KEYS[run["question_id"]]["key"]
        mine = check(t, key, to_guess(t, person[hid]), [])
        scored = {n: check(t, key, to_guess(t, judged[hid][n]), []) for n in tj.JUDGES}
        how = "marked" if hid in checked else "copied"
        for item, ok in mine.items():
            a, b = (scored[n][item] for n in tj.JUDGES)
            totals["items"] += 1
            totals[f"items the person {how}"] += 1
            totals["haiku agrees with the person"] += a == ok
            totals["gpt5mini agrees with the person"] += b == ok
            totals["judges agree with each other"] += a == b
            if a != ok or b != ok:
                rows.append(f"  {hid} ({how}) {run['run_id']} '{item}': person={ok} haiku={a} gpt5mini={b}")
    out = {"totals": dict(totals), "differences": rows}
    (HAND / "comparison.json").write_text(json.dumps(out, indent=1) + "\n")
    for k, v in totals.items():
        print(f"{k}: {v}" + ("" if k.startswith("items") else f"/{totals['items']}"))
    print("\n".join(rows) or "No differences.")


if __name__ == "__main__":
    {"make": make, "judge": judge, "compare": compare}[sys.argv[1]]()
