"""Shared helpers for the definition checks on wrong level 2 answers.

Exploratory, not pre-registered. For each level 2 run that gave values and failed,
a template module (r1.py, r10.py, ...) decides, for each definition the question
uses, whether the agent applied it. It uses two kinds of evidence:

- Values. The agent's copied values are compared with the key and with
  "alternative keys": the same number computed with one definition switched off
  or read another way. If the agent's number equals an alternative key exactly,
  that is strong evidence for which definition went wrong.
- Queries. The filters the agent sent to the query tools, read from the run record.

Every definition gets one verdict:
- applied: the agent's values or queries show it was applied as the question says.
- missed: the evidence shows it was left out or applied wrongly.
- other_reading: the agent followed a reasonable reading of the question that the
  frozen key doesn't accept. These go in docs/exploratory/key_issues.md. The keys
  and grades stay as they are.
- unclear: the evidence doesn't decide it.

A template module exports:
  TEMPLATE = "R10"
  DEFINITIONS = ["window", ...]       # in a fixed order
  def prepare(conn, repos) -> dict     # alternative keys per repo, computed once
  def check(t: Target, alt: dict) -> dict[str, Verdict]
"""

import contextlib
import gzip
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "answer_keys"))
import compute_keys as ck  # noqa: E402

GRADES = ROOT / "grading_results" / "main" / "final.jsonl.gz"
RUNS = [ROOT / "study_runs" / "main" / f"try{n}_runs.jsonl.gz" for n in (1, 2)]
KEYS = ROOT / "answer_keys" / "keys_primary.json"
RERUN = {"provider_failure", "infrastructure_failure"}

APPLIED, MISSED, OTHER_READING, UNCLEAR = "applied", "missed", "other_reading", "unclear"

# The window as the questions state it, and the ways agents write its ends.
W0, H2_0, W1 = ck.W0, ck.H2_0, ck.W1  # W1 is the day after the window ends
WINDOW_STARTS = {"2025-10-01", "2025-10-01T00:00:00Z", "2025-10-01T00:00:00"}
WINDOW_ENDS_EXCLUSIVE = {"2026-09-21", "2026-09-21T00:00:00Z", "2026-09-21T00:00:00"}
WINDOW_END_DAY = "2026-09-20"  # with lte, a date alone means 00:00 and misses the last day


@dataclass
class Verdict:
    verdict: str
    evidence: str = ""


@dataclass
class Target:
    run_id: str
    template: str
    repo: str
    model: str
    attempt: int
    run: dict
    grade: dict
    key: dict
    calls: list = field(default_factory=list)  # (tool_name, args) in order

    def value(self, name):
        """The value the judges copied from the answer, or None."""
        v = (self.grade.get("final_extracted") or {}).get(name) or {}
        return None if v.get("not_available") else v.get("value")


def load_targets(template, setup="L2"):
    """Every run of this template and setup that gave values and failed."""
    with gzip.open(GRADES, "rt") as f:
        grades = {
            r["run_id"]: r
            for r in map(json.loads, f)
            if r["template"] == template
            and r["setup"] == setup
            and r["label"] == "gives_values"
            and not r["passed"]
        }
    keys = json.loads(KEYS.read_text())[template]
    targets = []
    for path in RUNS:
        with gzip.open(path, "rt") as f:
            for line in f:
                run = json.loads(line)
                if run["run_id"] not in grades or run["stop_reason"] in RERUN:
                    continue
                g = grades[run["run_id"]]
                targets.append(
                    Target(
                        run_id=run["run_id"],
                        template=template,
                        repo=g["repo"],
                        model=run["model"].split("/")[-1],
                        attempt=run["attempt"],
                        run=run,
                        grade=g,
                        key=keys[g["repo"]],
                        calls=[
                            (s.get("tool_name"), parse_args(s.get("tool_arguments")))
                            for s in run["steps"]
                            if s["step_type"] == "tool_call"
                        ],
                    )
                )
    return sorted(targets, key=lambda t: t.run_id)


def parse_args(args):
    """Tool arguments as a dict. Some models send nested parts as JSON strings."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {}
    if not isinstance(args, dict):
        return {}
    out = dict(args)
    for k in ("filters", "post_filters", "aggregates", "first_per", "group_by"):
        if isinstance(out.get(k), str):
            with contextlib.suppress(json.JSONDecodeError):
                out[k] = json.loads(out[k])
    return out


def leaf_filters(obj):
    """Every {column, op, value} filter inside an argument, however it is nested
    (any_of lists, where clauses on aggregates, post_filters)."""
    if isinstance(obj, dict):
        if "column" in obj and "op" in obj:
            yield obj
        for v in obj.values():
            yield from leaf_filters(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from leaf_filters(v)


def filters(t, tools=None, column=None):
    """Leaf filters from the agent's calls, optionally only some tools or one column
    (a regex on the column name)."""
    out = []
    for name, args in t.calls:
        if tools and name not in tools:
            continue
        for f in leaf_filters(args):
            if column is None or re.fullmatch(column, str(f.get("column"))):
                out.append(f)
    return out


def used_tool(t, tool):
    return any(name == tool for name, _ in t.calls)


def window_check(t, tools, column):
    """Did the agent's date filters on this column cover the window as stated?"""
    fs = filters(t, tools, column)
    if not fs:
        return Verdict(UNCLEAR, f"no filter on {column}")
    starts = {str(f.get("value")) for f in fs if f.get("op") in ("gte", "gt")}
    ends = {(f.get("op"), str(f.get("value"))) for f in fs if f.get("op") in ("lt", "lte")}
    if WINDOW_STARTS & starts and any(v in WINDOW_ENDS_EXCLUSIVE for op, v in ends if op == "lt"):
        return Verdict(APPLIED, "window filter matches the question")
    if ("lte", WINDOW_END_DAY) in ends:
        return Verdict(MISSED, "lte 2026-09-20 means 00:00 on the last day, so it leaves out the last day")
    return Verdict(UNCLEAR, f"starts {sorted(starts)[:3]}, ends {sorted(ends)[:3]}")


BOT_WORDS = re.compile(r"bot|renovate|dependabot", re.I)


def bot_filter(t, tools, column):
    """Did the agent filter bots out on this column?"""
    for f in filters(t, tools, column):
        if f.get("op") in ("not_matches", "not_in", "ne") and BOT_WORDS.search(json.dumps(f.get("value"))):
            return Verdict(APPLIED, f"{f['op']} on {f['column']}")
    return Verdict(UNCLEAR, "no bot filter in the queries (it may have left bots out another way)")


def merge_filter(t, tools, column):
    for f in filters(t, tools, column):
        if (f.get("op") == "eq" and str(f.get("value")).lower() == "false") or (
            f.get("op") == "ne" and str(f.get("value")).lower() == "true"
        ):
            return Verdict(APPLIED, f"{column} is false")
    return Verdict(UNCLEAR, f"no filter on {column}")


FIX_WORDS = ("fix", "fixes", "fixed", "fixing", "bugfix")


def fix_filter(t, tools, column):
    """Did the agent's subject filter match the five fix words as whole words?"""
    pats = [str(f.get("value")) for f in filters(t, tools, column) if f.get("op") in ("matches", "contains")]
    if not pats:
        return Verdict(UNCLEAR, f"no filter on {column}")
    for p in pats:
        try:
            rx = re.compile(p.replace("\\m", r"\b").replace("\\M", r"\b"), re.I)
        except re.error:
            continue
        words_ok = all(rx.search(f"x {w} y") for w in FIX_WORDS)
        whole = not rx.search("prefix suffix") and not rx.search("fixture")
        if words_ok and whole:
            return Verdict(APPLIED, f"pattern {p[:60]}")
        if words_ok:
            return Verdict(MISSED, f"pattern {p[:60]} also matches words like prefix or fixture")
        if all(rx.search(f"{w} y") for w in FIX_WORDS):
            return Verdict(MISSED, f"pattern {p[:60]} only matches a fix word at the start of the line")
    return Verdict(MISSED, f"pattern {pats[0][:60]} misses some of the five fix words")


def close(a, b, tol):
    return isinstance(a, (int, float)) and b is not None and abs(a - b) <= tol


def pct(x):
    return None if x is None else 100 * x


def fetch(conn, sql):
    return ck.fetch(conn, sql)
