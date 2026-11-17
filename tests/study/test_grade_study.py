"""The study grader's code parts, without calling any judge.

A perfect answer must pass every question and an empty one none. Labels and
grounding must follow their written rules.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "grading"))
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
import grade_study as g  # noqa: E402
from grade_floor import key_as_guess  # noqa: E402

from repo_investigator.grading.extract import FIELDS  # noqa: E402

KEYS = g.load_keys(practice=False)


def as_extraction(template, guess):
    """Write a guess the way a judge would copy it."""
    ext = {}
    for name, (kind, _) in FIELDS[template].items():
        v = guess.get(name)
        item = {"value": v, "not_available": v is None, "stand_in": False}
        if kind.startswith("number"):
            item["unit"] = kind.split(":")[1] if v is not None else None
        ext[name] = item
    return ext


def score(qid, ext):
    q, key, alts = KEYS[qid]
    return g.check(q["template"], key, g.to_guess(q["template"], ext), alts)


def test_the_63_study_questions_are_loaded():
    assert len(KEYS) == 63
    assert "R6-eslint" not in KEYS and "R6-vite" not in KEYS


def test_a_perfect_answer_passes_every_question():
    for qid, (q, _, _) in KEYS.items():
        items = score(qid, as_extraction(q["template"], key_as_guess(q)))
        assert all(items.values()), (qid, items)


def test_an_empty_answer_passes_nothing():
    for qid, (q, _, _) in KEYS.items():
        assert not any(score(qid, as_extraction(q["template"], {})).values()), qid


def test_the_accepted_alternative_is_used():
    q = KEYS["R7-junit-framework"][0]
    ext = as_extraction(
        "R7", {"first_failing_sha": "ad922b18", "next_passing_sha": "05b4ea07", "hours_red": 33.1}
    )
    assert all(score(q["id"], ext).values())


def test_a_stand_in_never_scores():
    q = KEYS["R8-vite"][0]
    ext = as_extraction("R8", key_as_guess(q))
    for item in ext.values():
        item["stand_in"] = True
    assert not any(score(q["id"], ext).values())


def fields(*flags):
    return {f"f{i}": (na, si, None if na else 1.0) for i, (na, si) in enumerate(flags)}


def test_labels():
    assert g.label("", fields((True, False))) == "no_answer"
    assert g.label(None, fields((True, False))) == "no_answer"
    assert g.label("x", fields((True, False), (False, False))) == "gives_values"
    assert g.label("x", fields((False, True), (False, False))) == "gives_values"
    assert g.label("x", fields((False, True), (True, False))) == "stand_in"
    assert g.label("x", fields((True, False), (True, False))) == "no_values"


def ext_of(template, **values):
    return {
        n: {"value": v, "unit": u, "not_available": False, "stand_in": False} for n, (v, u) in values.items()
    }


def test_grounding_numbers():
    text = '{"rate": 0.378571, "share_pct": 39.2265, "count": 10, "median_seconds": 22140.0}'
    ext = ext_of(
        "R8",
        h1_top2_pct=(37.86, "percent"),
        h2_top2_pct=(39.23, "percent"),
    )
    assert g.grounded("R8", ext, text) == {"h1_top2_pct": True, "h2_top2_pct": True}
    ext = ext_of("R8", h1_top2_pct=(37.9, "percent"), h2_top2_pct=(41.0, "percent"))
    assert g.grounded("R8", ext, text) == {"h1_top2_pct": True, "h2_top2_pct": False}
    ext = ext_of("R4", unapproved=(10, "count"), unapproved_bot_prs=(11, "count"))
    assert g.grounded("R4", ext, text) == {"unapproved": True, "unapproved_bot_prs": False}
    ext = ext_of("R11", merge_h1_hours=(6.15, "hours"), merge_h2_hours=(369.0, "minutes"))
    assert g.grounded("R11", ext, text) == {"merge_h1_hours": True, "merge_h2_hours": True}


def test_grounding_sha_and_names_and_verdicts():
    text = "first failing ad922b18343e7677 in module promql"
    ext = ext_of("R7", first_failing_sha=("ad922b18", None), next_passing_sha=("05b4ea07", None))
    assert g.grounded("R7", ext, text) == {"first_failing_sha": True, "next_passing_sha": False}
    ext = ext_of("R6", most_fixes_module=("promql", None), top_share_module=("model", None))
    assert g.grounded("R6", ext, text) == {"most_fixes_module": True, "top_share_module": False}
    ext = ext_of("R1", verdict=("up", None))
    assert g.grounded("R1", ext, text) == {}


def test_had_data():
    run = lambda *results: {"steps": [{"step_type": "tool_result", "content": c} for c in results]}  # noqa: E731
    assert not g.had_data(run())
    assert not g.had_data(run('{"error": "Unknown tool"}', '{"stdout": "", "stderr": "Traceback"}'))
    assert g.had_data(run('{"error": "x"}', '{"stdout": "42\\n", "stderr": ""}'))
    assert g.had_data(run('{"rows": [1, 2]}'))
