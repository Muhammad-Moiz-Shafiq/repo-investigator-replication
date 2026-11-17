"""Compare the primary keys with the independent pandas keys, field by field.

Counts, shas, module names and verdicts must match exactly. Numbers must match
to 1e-6, since both sides compute the same thing from the same rows. Bootstrap
verdicts (R2, R3, R11 and R12) can honestly differ near the edge because the random
draws differ, so those mismatches are flagged separately for a closer look.

Writes answer_keys/comparison.md and exits with 1 if anything differs.

Usage:
  uv run python scripts/answer_keys/compare_keys.py
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
PRIMARY = ROOT / "answer_keys" / "keys_primary.json"
INDEPENDENT = ROOT / "independent_check" / "keys_pandas.json"
REPORT = ROOT / "answer_keys" / "comparison.md"
BOOTSTRAP_FIELDS = {
    ("R2", "main_verdict"),
    ("R2", "pr_verdict"),
    ("R3", "wait_verdict"),
    ("R3", "after_verdict"),
    ("R11", "merge_verdict"),
    ("R12", "verdict"),
}


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)


def main():
    primary = json.loads(PRIMARY.read_text())
    independent = json.loads(INDEPENDENT.read_text())
    hard, soft, checked = [], [], 0
    for q, repos in primary.items():
        for repo, fields in repos.items():
            other = independent.get(q, {}).get(repo)
            if other is None:
                hard.append(f"{q} {repo}: missing in independent keys")
                continue
            for field, value in fields.items():
                checked += 1
                if field not in other:
                    hard.append(f"{q} {repo} {field}: missing in independent keys")
                elif not same(value, other[field]):
                    line = f"{q} {repo} {field}: primary {value!r}, independent {other[field]!r}"
                    (soft if (q, field) in BOOTSTRAP_FIELDS else hard).append(line)
        extra = set(independent.get(q, {})) - set(repos)
        hard += [f"{q} {repo}: only in independent keys" for repo in sorted(extra)]

    lines = ["# Answer key comparison", "", f"Fields checked: {checked}.", ""]
    lines += ["## Mismatches", ""] + ([f"- {m}" for m in hard] or ["None."]) + [""]
    lines += ["## Bootstrap verdicts that differ (check if near the edge)", ""]
    lines += [f"- {m}" for m in soft] or ["None."]
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
