# ruff: noqa: E501
"""The must-have checklist items of each template, as code.

These follow the "Key. Must have" lines in docs/question_templates_draft.md.
A guess passes a question only if it meets every must-have item. Used by the
no-tool floor now, and by the main grader later for its numeric checks.

Units in the answer fields: rates and shares in percent, durations in the unit
named by the field. Keys store shares as fractions, so they are converted here.
"""

import re

VERDICTS = {
    "R1": ["up", "down", "no clear change"],
    "R2": ["up", "down", "no clear change"],
    "R3": ["up", "down", "no clear change"],
    "R5": ["growing", "shrinking", "balanced"],
    "R8": ["more concentrated", "less concentrated", "no clear change"],
    "R11": ["up", "down", "no clear change"],
    "R12": ["up", "down", "no clear change"],
}

# The JSON fields asked for in the floor, per template.
FIELDS = {
    "R1": ["h1_failure_rate_pct", "h2_failure_rate_pct", "verdict", "h1_rerun_pass_pct", "h2_rerun_pass_pct"],
    "R2": [
        "main_h1_minutes",
        "main_h2_minutes",
        "main_verdict",
        "pr_h1_minutes",
        "pr_h2_minutes",
        "pr_verdict",
    ],
    "R3": [
        "wait_h1_hours",
        "wait_h2_hours",
        "wait_verdict",
        "after_h1_hours",
        "after_h2_hours",
        "after_verdict",
        "h2_no_review_pct",
    ],  # fmt: skip
    "R4": ["merged_h2", "unapproved", "unapproved_pct", "unapproved_bot_prs"],
    "R5": ["opened", "closed", "verdict", "median_days_to_close", "still_open_pct"],
    "R6": ["most_fixes_module", "top_share_module"],
    "R7": ["first_failing_sha", "next_passing_sha", "hours_red"],
    "R8": ["h1_top2_pct", "h2_top2_pct", "verdict"],
    "R9": ["reviewers", "top2_pct"],
    "R10": ["fix_commits", "changed_test_pct"],
    "R11": [
        "opened",
        "merged_pct",
        "closed_unmerged_pct",
        "merge_h1_hours",
        "merge_h2_hours",
        "merge_verdict",
    ],
    "R12": ["h1_median_lines", "h2_median_lines", "verdict", "fix_median_lines", "other_median_lines"],
}


def num(x):
    try:
        return float(str(x).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def within_points(guess, key_fraction, points):
    g = num(guess)
    return g is not None and key_fraction is not None and abs(g - 100 * key_fraction) <= points


def within_rel(guess, key, rel):
    g = num(guess)
    return g is not None and key is not None and abs(g - key) <= rel * abs(key)


def within_abs(guess, key, diff):
    g = num(guess)
    return g is not None and abs(g - key) <= diff


def same_text(guess, key):
    return isinstance(guess, str) and guess.strip().lower().strip("/") == key.strip().lower().strip("/")


def same_sha(guess, key):
    g = str(guess or "").strip().lower()
    return len(g) >= 7 and re.fullmatch(r"[0-9a-f]+", g) is not None and key.startswith(g)


def check(template, key, guess, alternatives=()):
    """Return {item: passed} for every must-have item of one question."""
    k = key
    if template == "R1":
        return {
            "h1 rate within 1.5 points": within_points(guess.get("h1_failure_rate_pct"), k["h1_rate"], 1.5),
            "h2 rate within 1.5 points": within_points(guess.get("h2_failure_rate_pct"), k["h2_rate"], 1.5),
            "verdict": same_text(guess.get("verdict"), k["verdict"]),
        }
    if template == "R2":
        return {
            "main h1 median within 10%": within_rel(guess.get("main_h1_minutes"), k["main_h1_min"], 0.10),
            "main h2 median within 10%": within_rel(guess.get("main_h2_minutes"), k["main_h2_min"], 0.10),
            "main verdict": same_text(guess.get("main_verdict"), k["main_verdict"]),
        }
    if template == "R3":
        return {
            "wait h1 within 15%": within_rel(guess.get("wait_h1_hours"), k["wait_h1_h"], 0.15),
            "wait h2 within 15%": within_rel(guess.get("wait_h2_hours"), k["wait_h2_h"], 0.15),
            "after h1 within 15%": within_rel(guess.get("after_h1_hours"), k["after_h1_h"], 0.15),
            "after h2 within 15%": within_rel(guess.get("after_h2_hours"), k["after_h2_h"], 0.15),
            "wait verdict": same_text(guess.get("wait_verdict"), k["wait_verdict"]),
            "after verdict": same_text(guess.get("after_verdict"), k["after_verdict"]),
        }
    if template == "R4":
        return {
            "unapproved count within 10% (at least 1)": within_abs(
                guess.get("unapproved"), k["unapproved"], max(1, 0.10 * k["unapproved"])
            ),
            # The question asks for this count, not the share (fixed before the main run; see docs/decisions.md).
            "bot PRs among them exact": within_abs(guess.get("unapproved_bot_prs"), k["unapproved_bot_prs"], 0),
        }
    if template == "R5":
        return {
            "opened within 2": within_abs(guess.get("opened"), k["opened"], 2),
            "closed within 2": within_abs(guess.get("closed"), k["closed"], 2),
            "verdict": same_text(guess.get("verdict"), k["verdict"]),
            "median days within 10%": within_rel(
                guess.get("median_days_to_close"), k["median_days_to_close"], 0.10
            ),
        }
    if template == "R6":
        return {
            "most fixes module": same_text(guess.get("most_fixes_module"), k["most_fixes_module"]),
            "top share module": same_text(guess.get("top_share_module"), k["top_share_module"]),
        }
    if template == "R7":
        options = [k, *alternatives]
        best = max(
            (
                {
                    "first failing commit": same_sha(guess.get("first_failing_sha"), o["first_failing_sha"]),
                    "next passing commit": same_sha(guess.get("next_passing_sha"), o["next_passing_sha"]),
                    "time red within 10%": within_rel(guess.get("hours_red"), o["hours_red"], 0.10),
                }
                for o in options
            ),
            key=lambda r: sum(r.values()),
        )
        return best
    if template == "R8":
        return {
            "h1 share within 3 points": within_points(guess.get("h1_top2_pct"), k["h1_top2_share"], 3),
            "h2 share within 3 points": within_points(guess.get("h2_top2_pct"), k["h2_top2_share"], 3),
            "verdict": same_text(guess.get("verdict"), k["verdict"]),
        }
    if template == "R9":
        return {"top two share within 3 points": within_points(guess.get("top2_pct"), k["top2_share"], 3)}
    if template == "R10":
        return {
            "share within 3 points": within_points(guess.get("changed_test_pct"), k["share_changed_test"], 3)
        }
    if template == "R11":
        return {
            "opened within 5% (at least 2)": within_abs(
                guess.get("opened"), k["opened"], max(2, 0.05 * k["opened"])
            ),
            "merged share within 3 points": within_points(guess.get("merged_pct"), k["merged_share"], 3),
            "merge h1 median within 15%": within_rel(guess.get("merge_h1_hours"), k["merge_h1_h"], 0.15),
            "merge h2 median within 15%": within_rel(guess.get("merge_h2_hours"), k["merge_h2_h"], 0.15),
            "merge verdict": same_text(guess.get("merge_verdict"), k["merge_verdict"]),
        }
    if template == "R12":
        lines = lambda f, kf: within_abs(guess.get(f), k[kf], max(1, 0.10 * k[kf]))  # noqa: E731
        return {
            "h1 median within 10% (at least 1 line)": lines("h1_median_lines", "h1_median_lines"),
            "h2 median within 10% (at least 1 line)": lines("h2_median_lines", "h2_median_lines"),
            "verdict": same_text(guess.get("verdict"), k["verdict"]),
            "fix median within 10% (at least 1 line)": lines("fix_median_lines", "fix_median_lines"),
            "other median within 10% (at least 1 line)": lines("other_median_lines", "other_median_lines"),
        }
    raise ValueError(template)
