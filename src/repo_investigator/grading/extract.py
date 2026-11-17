# ruff: noqa: E501
"""Grading, step 1: a judge model copies the values out of an answer.

The judge never sees the answer key and never computes anything. For each
must-have field it copies the value and its unit exactly as the answer states
them, and flags values the answer gives only as a stand-in or says are not
available. Code then converts units and scores the values with the fixed
must-have checks (scripts/floor/must_haves.py), the same rule for every answer.
"""

import json
import re

UNITS = ["percent", "fraction", "seconds", "minutes", "hours", "days", "lines", "count", "none"]
VERDICT_WORDS = {
    "rate": ["up", "down", "no clear change"],
    "median": ["up", "down", "no clear change", "too few", "none"],
    "backlog": ["growing", "shrinking", "balanced"],
    "concentration": ["more concentrated", "less concentrated", "no clear change"],
}

# Per template: field -> (kind, description). kind is number:<unit>, verdict:<set>, sha or text.
FIELDS = {
    "R1": {
        "h1_failure_rate_pct": ("number:percent", "share of counted commits whose landing run failed, in H1"),
        "h2_failure_rate_pct": ("number:percent", "the same share in H2"),
        "verdict": ("verdict:rate", "verdict on whether that share changed from H1 to H2"),
    },
    "R2": {
        "main_h1_minutes": (
            "number:minutes",
            "median duration of successful landing (push, default branch) runs in H1",
        ),
        "main_h2_minutes": ("number:minutes", "the same median in H2"),
        "main_verdict": ("verdict:median", "verdict on whether that median changed from H1 to H2"),
    },
    "R3": {
        "wait_h1_hours": ("number:hours", "median time from PR opening to first review, H1"),
        "wait_h2_hours": ("number:hours", "median time from PR opening to first review, H2"),
        "wait_verdict": ("verdict:median", "verdict on the change in time to first review"),
        "after_h1_hours": ("number:hours", "median time from first review to merge, H1"),
        "after_h2_hours": ("number:hours", "median time from first review to merge, H2"),
        "after_verdict": ("verdict:median", "verdict on the change in time from first review to merge"),
    },
    "R4": {
        "unapproved": (
            "number:count",
            "number of PRs merged in H2 without an approval from someone other than the author",
        ),
        "unapproved_bot_prs": (
            "number:count",
            "how many of those unapproved PRs were opened by bots",
        ),
    },
    "R5": {
        "opened": ("number:count", "issues with the bug label opened in the window"),
        "closed": ("number:count", "issues with the bug label closed in the window"),
        "verdict": ("verdict:backlog", "whether the bug backlog is growing, shrinking or balanced"),
        "median_days_to_close": ("number:days", "median time to close for bugs opened in H1"),
    },
    "R6": {
        "most_fixes_module": ("text", "the module with the most fix commits"),
        "top_share_module": (
            "text",
            "the module with the highest share of fix commits among modules with at least 20 commits",
        ),
    },
    "R7": {
        "first_failing_sha": ("sha", "the commit the longest red stretch first failed on"),
        "next_passing_sha": ("sha", "the commit it next passed on"),
        "hours_red": ("number:hours", "how long it was red"),
    },
    "R8": {
        "h1_top2_pct": ("number:percent", "share of human commits by the two most active people in H1"),
        "h2_top2_pct": ("number:percent", "the same share in H2"),
        "verdict": ("verdict:concentration", "whether work became more or less concentrated"),
    },
    "R9": {
        "reviewers": ("number:count", "number of people who reviewed PRs in H2"),
        "top2_pct": ("number:percent", "share of the review work done by the two busiest reviewers"),
    },
    "R10": {
        "fix_commits": ("number:count", "number of fix commits in the window"),
        "changed_test_pct": ("number:percent", "share of fix commits that also changed a test file"),
    },
    "R11": {
        "opened": ("number:count", "PRs opened by renovate and dependabot in the window"),
        "merged_pct": ("number:percent", "share of those that were merged"),
        "closed_unmerged_pct": ("number:percent", "share of those closed without being merged"),
        "merge_h1_hours": ("number:hours", "median time from opening to merge for bot PRs merged in H1"),
        "merge_h2_hours": ("number:hours", "the same median for H2"),
        "merge_verdict": ("verdict:median", "verdict on whether that median changed"),
    },
    "R12": {
        "h1_median_lines": ("number:lines", "median commit size in H1"),
        "h2_median_lines": ("number:lines", "median commit size in H2"),
        "verdict": ("verdict:median", "verdict on whether the median size changed"),
        "fix_median_lines": ("number:lines", "median size of fix commits in the window"),
        "other_median_lines": ("number:lines", "median size of all other commits in the window"),
    },
}

SYSTEM = """You extract values from an analyst's answer to a question about a software repository. You are a careful copier, not a checker.

Rules:
- Copy each value exactly as the answer states it, with the unit the answer uses. Never calculate, convert, round, correct or check anything, and never use outside knowledge.
- Prefer the RESULTS block at the end of the answer. If the RESULTS block and the text disagree, use the RESULTS block. If there is no RESULTS block, use the text.
- If the answer does not give a value, or says it is not available, set value to null and not_available to true.
- If the answer gives a value only as a stand-in or proxy for what was asked (it says so), copy it and set stand_in to true.
- For a verdict, pick one of the allowed words. If the answer states the verdict in other words with the same meaning, pick the matching word (for a duration, slower means up and faster means down). If it is unclear, use null.
- For a commit, copy the full SHA as written. For a name, such as a module, copy only the name itself, without counts or notes.
- For a percentage written as a fraction (like 0.35), use the unit fraction. For a count, use count."""


def schema_for(template: str) -> dict:
    props = {}
    for name, (kind, desc) in FIELDS[template].items():
        flags = {"not_available": {"type": "boolean"}, "stand_in": {"type": "boolean"}}
        if kind.startswith("number"):
            props[name] = {
                "type": "object",
                "description": desc,
                "properties": {
                    "value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "unit": {"anyOf": [{"type": "string", "enum": UNITS}, {"type": "null"}]},
                    **flags,
                },
                "required": ["value", "unit", "not_available", "stand_in"],
                "additionalProperties": False,
            }
        else:
            words = VERDICT_WORDS[kind.split(":")[1]] if kind.startswith("verdict") else None
            text = {"type": "string", "enum": words} if words else {"type": "string"}
            value = {"anyOf": [text, {"type": "null"}]}
            props[name] = {
                "type": "object",
                "description": desc,
                "properties": {"value": value, **flags},
                "required": ["value", "not_available", "stand_in"],
                "additionalProperties": False,
            }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def user_message(question: str, answer: str | None, template: str) -> str:
    fields = "\n".join(f"- {n}: {d}" for n, (_, d) in FIELDS[template].items())
    return (
        f"QUESTION:\n{question}\n\nANSWER:\n{answer or '(no answer was given)'}\n\nFields to copy:\n{fields}"
    )


TO_BASE = {"seconds": 1 / 3600, "minutes": 1 / 60, "hours": 1, "days": 24}  # to hours


def to_guess(template: str, extracted: dict) -> dict:
    """Convert extracted values to the units the must-have checks expect. Stand-ins don't count."""
    guess = {}
    for name, (kind, _) in FIELDS[template].items():
        item = extracted.get(name) or {}
        v = item.get("value")
        if v is None or item.get("stand_in"):
            guess[name] = None
            continue
        if kind.startswith("number"):
            want, unit = kind.split(":")[1], item.get("unit")
            if want == "percent":
                v = v * 100 if unit == "fraction" else v
            elif want in TO_BASE and unit in TO_BASE:
                v = v * TO_BASE[unit] / TO_BASE[want]
            guess[name] = v
        else:
            guess[name] = v
    return guess


def parse(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0) if m else text)
