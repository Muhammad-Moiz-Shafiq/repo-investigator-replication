# ruff: noqa: E501
"""Check a tiebreaker judge before using it.

The tiebreaker only sees answers where the two main judges disagree, so it
must be at least close to them in accuracy. This runs it on every answer of
the judge trial and counts how often it agrees with the two main judges on
the items where those two already agree with each other.

Usage:
  uv run --env-file .env python scripts/grading/check_tiebreak.py
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
sys.path.insert(0, str(ROOT / "scripts" / "grading"))
import try_judges as tj  # noqa: E402
from hand_sheet import trial_runs  # noqa: E402
from must_haves import check  # noqa: E402

from repo_investigator.grading.extract import to_guess  # noqa: E402


def main():
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=180,
        max_retries=0,
    )

    def one(pair):
        trial, run = pair
        q = tj.QUESTIONS[run["question_id"]]
        ext, cost, provider = tj.ask(client, tj.TIEBREAK, q["template"], q["question"], run["final_answer"])
        items = (
            None
            if "error" in ext
            else check(q["template"], tj.KEYS[q["id"]]["key"], to_guess(q["template"], ext), [])
        )
        return trial, items, cost, provider

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(one, trial_runs()))
    agree = total = errors = 0
    providers, cost = set(), 0.0
    for trial, items, c, provider in results:
        cost += c
        providers.add(provider)
        if items is None:
            errors += 1
            continue
        a, b = trial["judges"]["haiku"]["items"], trial["judges"]["gpt5mini"]["items"]
        # R4's fields changed after the trial, so only items the trial also had are compared.
        for i in a:
            if i in items and a[i] == b[i]:
                total += 1
                agree += items[i] == a[i]
                if items[i] != a[i]:
                    print(f"  DIFF {trial['run_id']} '{i}': judges={a[i]} tiebreaker={items[i]}")
    print(f"{tj.TIEBREAK['model']} via {providers}: {len(results)} answers, {errors} errors, ${cost:.4f}")
    print(
        f"agrees with the two judges where they agree: {agree}/{total} ({100 * agree / max(1, total):.1f}%)"
    )


if __name__ == "__main__":
    main()
