"""The tool menu of every template at every coverage level.

- Level 2: the 7 query tools and the 4 calculators, the same for every template.
- Level 1: level 2 plus the template's part tools.
- Level 0: level 1 plus the template's direct tool.
- Level 3: level 2 minus every query tool that reads a table the answer needs.

Side check only: padded_level2 is level 2 plus filler tools, up to the
template's level 0 size. No main menu has a filler.

ESSENTIAL lists, per template, the tables the answer can't be computed
without. Level 3 removes every tool that reads any of them, even only to check
that a row exists. That is stricter than "the tool shows those fields", on
purpose: test 4 then only has to compare declared reads.
"""

from repo_investigator.levels.domain import TOOLS as DOMAIN_TOOLS
from repo_investigator.levels.fillers import FILLERS
from repo_investigator.levels.fillers import READS as FILLER_READS
from repo_investigator.levels.query import TABLES
from repo_investigator.levels.tools import CALCULATORS

TEMPLATES = [f"R{i}" for i in range(1, 13)]
QUERY_TOOLS = list(TABLES)
LEVEL2 = [*QUERY_TOOLS, *CALCULATORS]

ESSENTIAL = {
    "R1": {"ci_runs"},
    "R2": {"ci_runs"},
    "R3": {"pr_reviews"},
    "R4": {"pr_reviews"},
    "R5": {"issues"},
    "R6": {"commit_files"},
    "R7": {"ci_runs"},
    "R8": {"commits"},
    "R9": {"pr_reviews"},
    "R10": {"commit_files"},
    "R11": {"pull_requests"},
    "R12": {"commits"},
}
# Workflows only describe CI runs, so they go with them.
GOES_WITH = {"ci_runs": {"workflows_snapshot"}}


def reads(tool: str) -> set[str]:
    if tool in TABLES:
        return set(TABLES[tool].reads)
    if tool in DOMAIN_TOOLS:
        return set(DOMAIN_TOOLS[tool].reads)
    if tool in FILLERS:
        return set(FILLER_READS)
    return set()  # calculators read no table


def removed_at_level3(template: str) -> set[str]:
    gone = set(ESSENTIAL[template])
    for t in list(gone):
        gone |= GOES_WITH.get(t, set())
    return gone


def menu(template: str, level: int) -> list[str]:
    parts = [t.name for t in DOMAIN_TOOLS.values() if t.template == template and t.level == 1]
    direct = [t.name for t in DOMAIN_TOOLS.values() if t.template == template and t.level == 0]
    if level == 0:
        return [*direct, *parts, *LEVEL2]
    if level == 1:
        return [*parts, *LEVEL2]
    if level == 2:
        return list(LEVEL2)
    if level == 3:
        gone = removed_at_level3(template)
        return [t for t in LEVEL2 if not reads(t) & gone]
    raise ValueError(f"Unknown level {level}.")


def padded_level2(template: str) -> list[str]:
    """Level 2 padded with fillers to the template's level 0 size, for the menu size side check only."""
    extra = len(menu(template, 0)) - len(LEVEL2)
    if extra > len(FILLERS):
        raise ValueError(f"{template} needs {extra} fillers, only {len(FILLERS)} exist.")
    return [*LEVEL2, *list(FILLERS)[:extra]]
