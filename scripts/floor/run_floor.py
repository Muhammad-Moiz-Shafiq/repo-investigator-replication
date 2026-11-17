"""No-tool floor: ask every question to models that have no data and no tools.

If a model can meet every must-have item of a question by guessing or from
memory, that question can't tell us anything about tool use. The rule for what
gets dropped is in docs/question_templates_draft.md and was committed before
this script was first run.

Each model answers each question TRIES times. Raw replies are saved to
floor_results/raw/<model>.json as they arrive, so a rerun skips what is done.

Usage:
  uv run --env-file .env python scripts/floor/run_floor.py
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent))
from must_haves import FIELDS, VERDICTS  # noqa: E402

ROOT = Path(__file__).parent.parent.parent
QUESTIONS = ROOT / "questions" / "questions.json"
RAW = ROOT / "floor_results" / "raw"
MODELS = ["openai/gpt-5-mini", "deepseek/deepseek-v4-flash", "google/gemini-3.6-flash"]
TRIES = 3
MAX_TOKENS = 6000

SYSTEM = (
    "You are answering a question about a GitHub repository. You have no tools and no access to the "
    "repository's data. Answer from what you know about the project and your best estimate. Give a "
    "concrete best guess for every field, even when you are unsure. Never leave a field empty."
)


def prompt(q):
    fields = FIELDS[q["template"]]
    lines = [q["question"], "", "Reply with only a JSON object with these fields:"]
    for f in fields:
        if f.endswith("verdict") or f == "verdict":
            options = VERDICTS[q["template"]]
            lines.append(f"- {f}: one of {', '.join(repr(o) for o in options)}")
        elif f.endswith("_pct"):
            lines.append(f"- {f}: a number in percent (0 to 100)")
        elif f.endswith("_sha"):
            lines.append(f"- {f}: the commit sha (at least 7 hex characters)")
        elif f.endswith("_module"):
            lines.append(f"- {f}: the module path")
        else:
            lines.append(f"- {f}: a number")
    return "\n".join(lines)


def parse(text):
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def ask(client, model, q, attempt):
    for retry in range(4):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(q)}],
                max_tokens=MAX_TOKENS,
                extra_body={"usage": {"include": True}},
            )
            text = r.choices[0].message.content
            usage = r.usage.model_dump() if r.usage else {}
            return {
                "id": q["id"],
                "try": attempt,
                "model": model,
                "provider_model": r.model,
                "text": text,
                "guess": parse(text),
                "cost": usage.get("cost"),
                "usage": usage,
            }
        except Exception as e:  # noqa: BLE001
            err = repr(e)
            time.sleep(5 * (retry + 1))
    return {"id": q["id"], "try": attempt, "model": model, "text": None, "guess": None, "error": err}


def main():
    questions = json.loads(QUESTIONS.read_text())
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
    RAW.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        path = RAW / f"{model.replace('/', '__')}.json"
        done = json.loads(path.read_text()) if path.exists() else []
        have = {(d["id"], d["try"]) for d in done if d.get("guess") is not None}
        done = [d for d in done if (d["id"], d["try"]) in have]
        jobs = [(q, t) for q in questions for t in range(1, TRIES + 1) if (q["id"], t) not in have]
        print(f"{model}: {len(jobs)} calls to make", flush=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            for result in pool.map(lambda j, m=model: ask(client, m, *j), jobs):
                done.append(result)
                path.write_text(json.dumps(done, indent=1) + "\n")
        bad = sum(d.get("guess") is None for d in done)
        cost = sum(d.get("cost") or 0 for d in done)
        print(f"{model}: {len(done)} replies, {bad} unparsed, cost ${cost:.4f}", flush=True)


if __name__ == "__main__":
    main()
