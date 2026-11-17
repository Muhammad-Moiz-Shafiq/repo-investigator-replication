"""Add up the definition checks across templates, by kind of definition and by model.

Exploratory. Each run counts once per kind, however many of its definitions in
that kind were missed.

Usage:
  uv run python scripts/exploratory/definitions/summarize.py
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
DIR = ROOT / "analysis_results" / "exploratory" / "definitions"

# Each template's definitions, grouped into kinds that read the same across templates.
KINDS = {
    "dates and periods": {
        "R1": ["halves"],
        "R2": ["halves"],
        "R4": ["h2_merged"],
        "R6": ["window"],
        "R7": ["h2_start"],
        "R8": ["window"],
        "R9": ["h2_window"],
        "R10": ["window"],
        "R11": ["merge_halves"],
        "R12": ["window"],
    },
    "bots and automation": {
        "R3": ["bot_prs"],
        "R4": ["bot_prs"],
        "R8": ["bots", "automation"],
        "R9": ["bots"],
        "R12": ["bots"],
    },
    "merge commits": {"R8": ["merges"]},
    "author's own reviews": {"R3": ["not_author"], "R9": ["self_reviews"]},
    "which records count": {
        "R1": ["push_default", "excluded", "failing"],
        "R2": ["push_default", "success", "workflow"],
        "R3": ["before_merge", "no_review"],
        "R5": ["label", "open_bugs"],
        "R7": ["push_default", "excluded", "failing"],
    },
    "one per unit": {
        "R1": ["landing"],
        "R2": ["landing"],
        "R3": ["first_review"],
        "R7": ["landing"],
        "R9": ["one_per_pr"],
    },
    "text and file rules": {
        "R6": ["test_files", "doc_files"],
        "R10": ["fix_rule", "test_rule"],
        "R12": ["fix_rule"],
    },
    "picking and dividing": {
        "R5": ["opened", "closed"],
        "R6": ["ranking"],
        "R7": ["longest"],
        "R8": ["top_two", "denominator"],
        "R9": ["share_base"],
        "R12": ["other_group"],
    },
    "verdict test": {
        "R5": ["backlog_test"],
        "R8": ["verdict_test"],
        "R11": ["median_test"],
        "R12": ["verdict_test"],
    },
}


def main():
    rows = []
    for f in sorted(DIR.glob("r*.json")):
        res = json.loads(f.read_text())
        for r in res["rows"]:
            rows.append((res["template"], r))
    kinds, by_model, outcome = Counter(), defaultdict(Counter), Counter()
    unmapped = set()
    for template, r in rows:
        v = r["verdicts"]
        missed = {d for d in v if v[d]["verdict"] == "missed"}
        other = {d for d in v if v[d]["verdict"] == "other_reading"}
        mapped = set()
        for kind, per in KINDS.items():
            if missed & set(per.get(template, [])):
                kinds[kind] += 1
                by_model[r["model"]][kind] += 1
                mapped |= missed & set(per.get(template, []))
        unmapped |= {(template, d) for d in missed - mapped}
        o = (
            "missed a definition"
            if missed
            else ("only a reading the key rejects" if other else "nothing found")
        )
        outcome[o] += 1
        by_model[r["model"]][o] += 1
    out = {
        "runs": len(rows),
        "outcome": outcome,
        "runs_missing_each_kind": dict(kinds.most_common()),
        "by_model": by_model,
        "unmapped": sorted(unmapped),
    }
    (DIR.parent / "definitions_summary.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
