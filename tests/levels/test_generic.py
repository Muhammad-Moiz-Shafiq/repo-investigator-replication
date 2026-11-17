"""Fairness test 3, level 2 half: the generic tools know nothing about any question.

The level 2 code (query tools, calculators, tool schemas) may not contain any
repo name, date, bot login, workflow path, label, fix word, CI result value or
other definition from a question. The shared verdict rules (0.05, 20%, 4,000
resamples) are allowed in the calculators: the system prompt states them and
every level gets the same calculators.
"""

import re
from pathlib import Path

import pytest

LEVELS = Path(__file__).parent.parent.parent / "src" / "repo_investigator" / "levels"
GENERIC_FILES = ["query.py", "calculators.py", "tools.py"]
FORBIDDEN = [
    r"tokio",
    r"eslint",
    r"sqlalchemy",
    r"vite\b",
    r"junit",
    r"prometheus",
    r"20(25|26)-\d\d",
    r"renovate",
    r"dependabot",
    r"github-actions",
    r"copilot",
    r"jenkins",
    r"googlegroups",
    r"\.github/workflows",
    r"\bci\.yml",
    r"C-bug|kind/bug|type: bug|p3-minor-bug",
    r"\bfix(es|ed|ing)?\b|bugfix",
    r"timed_out|startup_failure|cancelled|skipped",
    r"\blanding\b",
    r"\bH1\b|\bH2\b",
    r"test_file|doc_file|_test\.go|__tests__",
]


def code_and_strings(path: Path) -> str:
    # Comments and docstrings may explain where a feature came from; the code may not use it.
    text = path.read_text()
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


@pytest.mark.parametrize("name", GENERIC_FILES)
def test_no_question_specific_content(name):
    text = code_and_strings(LEVELS / name)
    hits = [p for p in FORBIDDEN if re.search(p, text, re.IGNORECASE)]
    assert not hits, f"{name} contains question-specific content: {hits}"


def test_the_test_catches_a_leak(tmp_path):
    leaky = tmp_path / "leaky.py"
    leaky.write_text('BOTS = ["renovate"]\nWHERE = "conclusion in (\'timed_out\')"\n')
    text = code_and_strings(leaky)
    assert [p for p in FORBIDDEN if re.search(p, text, re.IGNORECASE)]
