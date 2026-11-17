# ruff: noqa: E501
"""Try the judges on practice answers: extraction, scoring and agreement.

Practice runs only (answer_keys/practice_keys.json). Each judge copies the
must-have values out of each answer (src/repo_investigator/grading/extract.py),
code scores them with the must-have checks, and the two judges' item results
are compared. Where they disagree, the tiebreaker decides. Results go to
grading_results/<name>.json for review and for the hand-grading comparison.

Usage:
  uv run --env-file .env python scripts/grading/try_judges.py NAME RUN_SET [RUN_SET ...]
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
from must_haves import check  # noqa: E402

from repo_investigator.grading.extract import SYSTEM, parse, schema_for, to_guess, user_message  # noqa: E402

KEYS = json.loads((ROOT / "answer_keys" / "practice_keys.json").read_text())
QUESTIONS = {q["id"]: q for q in json.loads((ROOT / "questions" / "practice.json").read_text())}
JUDGES = {
    "haiku": {"model": "anthropic/claude-haiku-5.5", "provider": "anthropic", "params": {"temperature": 0}},
    "gpt5mini": {
        "model": "openai/gpt-5-mini",
        "provider": "openai",
        "params": {"reasoning": {"effort": "low"}},
    },
}
# Same family as a study model (deepseek-v4-flash). Accepted because it only breaks ties,
# is checked first (scripts/grading/check_tiebreak.py), and a person reviews its calls.
TIEBREAK = {"model": "deepseek/deepseek-v4.1-flash", "provider": "parasail/fp8", "params": {"temperature": 0}}


def ask(client, judge, template, question, answer):
    extra = {"usage": {"include": True}, **judge["params"]}
    if judge["provider"]:
        extra["provider"] = {"order": [judge["provider"]], "allow_fallbacks": False}
    for attempt in range(4):
        try:
            r = client.chat.completions.create(
                model=judge["model"],
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user_message(question, answer, template)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "extraction", "strict": True, "schema": schema_for(template)},
                },
                extra_body=extra,
            )
            usage = r.usage.model_dump() if r.usage else {}
            return parse(r.choices[0].message.content), usage.get("cost") or 0, getattr(r, "provider", None)
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                return {"error": str(e)[:300]}, 0, None
            time.sleep(5 * (attempt + 1))


def grade(client, run):
    q, key = QUESTIONS[run["question_id"]], KEYS[run["question_id"]]
    t = q["template"]
    out = {
        "run_id": run["run_id"],
        # run_id repeats across practice run sets (the same question, setup, model and try was
        # rerun under each prompt version), so a record names both.
        "run_set": run["run_set"],
        "question_id": q["id"],
        "setup": run["setup"],
        "model": run["model"],
        "judges": {},
        "cost": 0.0,
    }
    for name, judge in JUDGES.items():
        ext, cost, provider = ask(client, judge, t, q["question"], run["final_answer"])
        out["cost"] += cost
        items = None if "error" in ext else check(t, key["key"], to_guess(t, ext), [])
        out["judges"][name] = {"extracted": ext, "items": items, "provider": provider}
    a, b = (out["judges"][n]["items"] for n in JUDGES)
    if a is None or b is None:
        out["final"] = None
        return out
    disagree = [i for i in a if a[i] != b[i]]
    final = dict(a)
    if disagree:
        ext, cost, provider = ask(client, TIEBREAK, t, q["question"], run["final_answer"])
        out["cost"] += cost
        c = None if "error" in ext else check(t, key["key"], to_guess(t, ext), [])
        out["judges"]["tiebreak"] = {"extracted": ext, "items": c, "provider": provider}
        for i in disagree:
            final[i] = c[i] if c else None
    out["disagreed_items"] = disagree
    out["final"] = final
    out["passed"] = None if None in final.values() else all(final.values())
    return out


def main():
    name, run_sets = sys.argv[1], sys.argv[2:]
    runs = [
        json.loads(line)
        for rs in run_sets
        for line in (ROOT / "study_runs" / rs / "runs.jsonl").read_text().splitlines()
    ]
    runs = [
        r
        for r in runs
        if r["question_id"].startswith("P-")
        and r["stop_reason"] in ("answered", "budget", "model_output_failure")
    ]
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=180,
        max_retries=0,
    )
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda r: grade(client, r), runs))
    out = ROOT / "grading_results" / f"{name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1, default=str) + "\n")
    items = [(r, i) for r in results if r.get("final") for i in r["final"]]
    agree = sum(r["judges"]["haiku"]["items"][i] == r["judges"]["gpt5mini"]["items"][i] for r, i in items)
    whole = sum(not r.get("disagreed_items") for r in results if r.get("final"))
    errors = sum(r.get("final") is None for r in results)
    print(
        f"{len(results)} answers graded, {errors} with a judge error, cost ${sum(r['cost'] for r in results):.4f}"
    )
    print(
        f"item agreement between the two judges: {agree}/{len(items)} ({100 * agree / max(1, len(items)):.1f}%)"
    )
    print(f"answers where they agreed on every item: {whole}/{len(results) - errors}")
    print(f"answers passing every must-have: {sum(bool(r.get('passed')) for r in results)}")
    for r in results:
        for i in r.get("disagreed_items", []):
            ex = {n: r["judges"][n]["extracted"] for n in r["judges"]}
            print(
                f"  DISAGREE {r['run_id']} item '{i}': "
                + "; ".join(f"{n}={json.dumps(e)[:160]}" for n, e in ex.items())
            )


if __name__ == "__main__":
    main()
