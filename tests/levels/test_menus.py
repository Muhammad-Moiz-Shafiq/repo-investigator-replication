"""Fairness tests 4 and 5 (the parts that need no model run)."""

import pytest

from repo_investigator.levels import domain
from repo_investigator.levels.menus import ESSENTIAL, LEVEL2, TEMPLATES, menu, reads
from repo_investigator.levels.tools import ALL_SCHEMAS


@pytest.mark.parametrize("t", TEMPLATES)
def test_levels_are_nested(t):
    m0, m1, m2, m3 = (menu(t, level) for level in range(4))
    assert set(m3) < set(m2) < set(m1) < set(m0)
    assert set(m2) == set(LEVEL2)
    assert len(set(m0) - set(m1)) == 1  # exactly one direct tool


@pytest.mark.parametrize("t", TEMPLATES)
def test_level3_reads_nothing_the_answer_needs(t):
    for tool in menu(t, 3):
        assert not reads(tool) & ESSENTIAL[t], f"{t} level 3 keeps {tool}, which reads {reads(tool)}"


@pytest.mark.parametrize("t", TEMPLATES)
def test_level3_still_has_the_other_data(t):
    # Level 3 removes coverage for this question, not everything.
    assert len(menu(t, 3)) >= 8


def test_every_tool_has_a_schema_and_declares_reads():
    for t in TEMPLATES:
        for tool in menu(t, 0):
            assert tool in ALL_SCHEMAS
    for tool in domain.TOOLS.values():
        assert tool.reads, f"{tool.name} declares no tables"


def test_direct_tools_need_only_what_the_question_states():
    # Level 0 tools take dates and question-stated values, never a key value.
    for tool in domain.TOOLS.values():
        assert "repo" in tool.required
        for p in tool.params:
            assert "threshold" not in p and "answer" not in p


@pytest.mark.parametrize("t", TEMPLATES)
def test_padded_level2_matches_level0_size_and_adds_only_fillers(t):
    from repo_investigator.levels.fillers import FILLERS
    from repo_investigator.levels.menus import padded_level2

    padded = padded_level2(t)
    assert len(padded) == len(menu(t, 0))
    assert set(padded) - set(LEVEL2) <= set(FILLERS)
    for level in range(4):
        assert not set(menu(t, level)) & set(FILLERS), "fillers must never be in a main menu"


def test_fillers_read_no_study_table():
    from repo_investigator.levels.fillers import FILLERS

    study = {
        "ci_runs",
        "commits",
        "commit_files",
        "pull_requests",
        "pr_reviews",
        "issues",
        "workflows_snapshot",
    }
    for f in FILLERS:
        assert not reads(f) & study
