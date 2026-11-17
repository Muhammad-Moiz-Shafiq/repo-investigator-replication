"""Write questions/questions.json, the exact text of every study question.

Each template from docs/question_templates_draft.md is filled in with the repo's
settings. Every condition (no-tool floor, every coverage level, every variant) reads its
questions from this one file, so they all see the same words.

Usage:
  uv run python scripts/questions/render_questions.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
OUT = ROOT / "questions" / "questions.json"
FLOOR = ROOT / "floor_results" / "floor_summary.json"

WINDOW = (
    "All dates are in UTC. The window is 2025-10-01 to 2026-09-20. "
    "H1 is 2025-10-01 to 2026-03-31 and H2 is 2026-04-01 to 2026-09-20, both inclusive."
)
LANDING = (
    "For each commit, use the run from when it landed on the default branch (its earliest push run "
    "of that workflow), with its final result. Count each commit once, and leave out cancelled and "
    "skipped runs."
)
FIX_RULE = (
    "Count a commit as a fix if it is not a merge commit, is not from a bot, and the first line of its "
    "message contains the word fix, fixes, fixed, fixing or bugfix."
)
TEST_FILE = (
    "A test file is a file inside a test folder (such as test, tests, __tests__, testdata, testing, "
    "fixtures, or vite's playground) or with a test-style name (such as *_test.go, test_*.py, "
    "*Test.java or *.spec.ts)."
)

REPOS = {
    "tokio": {
        "slug": "tokio-rs/tokio",
        "ci": "the CI workflow (.github/workflows/ci.yml)",
        "label": "C-bug",
        "module": "the top-level folder",
    },
    "eslint": {
        "slug": "eslint/eslint",
        "ci": "the CI workflow (.github/workflows/ci.yml)",
        "label": "bug",
        "module": "a folder directly under lib/, written as lib/<name>",
    },
    "sqlalchemy": {
        "slug": "sqlalchemy/sqlalchemy",
        "ci": "the Run tests workflow (.github/workflows/run-test.yaml)",
        "label": "bug",
        "module": "a folder directly under lib/sqlalchemy/, written as lib/sqlalchemy/<name>",
    },
    "vite": {
        "slug": "vitejs/vite",
        "ci": "the CI workflow (.github/workflows/ci.yml)",
        "label": "p3-minor-bug",
        "module": "a folder directly under packages/, written as packages/<name>",
    },
    "junit-framework": {
        "slug": "junit-team/junit-framework",
        "ci": (
            "the CI workflow (.github/workflows/main.yml, renamed to ci.yml on 2026-05-15; "
            "treat both as one workflow)"
        ),
        "label": "type: bug",
        "module": "the top-level folder",
    },
    "prometheus": {
        "slug": "prometheus/prometheus",
        "ci": "the CI workflow (.github/workflows/ci.yml)",
        "label": "kind/bug",
        "module": "the top-level folder",
    },
}

ALL = list(REPOS)
NO_GERRIT = [r for r in ALL if r != "sqlalchemy"]
R6_REPOS = ["eslint", "prometheus", "sqlalchemy", "vite"]
R11_REPOS = ["eslint", "vite", "junit-framework", "prometheus"]

TEMPLATES = {
    "R1": (
        ALL,
        "I maintain {slug} and I'm deciding whether to spend time on CI. Did the share of commits on the "
        "default branch that fail {ci} change between H1 and H2? How often did a failing run pass just "
        "because someone re-ran it? {landing} A failing run means a result of failure, timed_out or "
        "startup_failure.",
    ),
    "R2": (
        ALL,
        "I contribute to {slug} and I'm tired of waiting for CI feedback. Did successful runs of {ci} on "
        "the default branch get slower or faster between H1 and H2? Is the change the same for successful "
        "pull request runs of the same workflow? {landing} Measure a run's duration from its start to its "
        "finish.",
    ),
    "R3": (
        NO_GERRIT,
        "I maintain {slug} and pull requests seem to sit too long before they get merged. For PRs merged "
        "in H1 and in H2 (split by merge date, PRs opened by bots left out), what is the median time from "
        "opening to the first review by someone other than the author, and from that first review to the "
        "merge? Did either part change between H1 and H2, and which part takes longer? A review here is "
        "any submitted review (approved, commented or changes requested) before the merge, not counting "
        "bots.",
    ),
    "R4": (
        NO_GERRIT,
        "I'm doing a security review of {slug}. Of the PRs merged in H2, how many were merged without an "
        "approval from someone other than the author before the merge, and how many of those were opened "
        "by bots? Bots that approve PRs don't count as approvals.",
    ),
    "R5": (
        ALL,
        'I triage bugs for {slug}. In the window, how many issues labeled "{label}" were opened, and how '
        "many were closed (whenever they were opened)? Is the bug backlog growing, shrinking or roughly "
        "balanced? For bugs opened in H1, what was the median time to close? Count a bug still open at the "
        "end of the window as not closed yet.",
    ),
    "R6": (
        R6_REPOS,
        "I'm new to reviewing code in {slug} and want to know where fixes cluster. {fix} A module is "
        "{module}. Leave out test files, documentation files and files at the repo root. In the window, "
        "which module had the most fix commits? Among modules with at least 20 commits in the window, "
        "which had the highest share of fix commits? {test}",
    ),
    "R7": (
        ALL,
        "I'm on build duty for {slug}. Find the longest stretch starting in H2 where {ci} stayed red on the "
        "default branch, measured from when the first failing run finished to when the next passing run "
        "finished. Which commit did it first fail on, what did that commit change, which commit did it "
        "next pass on, and how long was it red? {landing} A failing run means a result of failure, "
        "timed_out or startup_failure.",
    ),
    "R8": (
        ALL,
        "I lead {slug} and I'm thinking about what happens if key people step away. What share of "
        "non-merge commits by humans (bots left out) came from the two most active people in H1, and in "
        "H2? Did the work become more or less concentrated?",
    ),
    "R9": (
        NO_GERRIT,
        "I maintain {slug} and I'm worried about reviewer burnout. In H2, how many people reviewed pull "
        "requests, and what share of the review work did the two busiest reviewers do? Count one reviewer "
        "on one PR once, however many reviews they left. Leave out bots and authors reviewing their own "
        "PRs.",
    ),
    "R10": (
        ALL,
        "I review code in {slug}. {fix} In the window, how many fix commits were there, and what share of "
        "them also changed a test file? {test}",
    ),
    "R11": (
        R11_REPOS,
        "I maintain {slug} and want to know whether dependency updates are keeping up. Look at pull "
        "requests opened by the dependency bots renovate and dependabot. In the window, how many did they "
        "open, what share was merged, and what share was closed without being merged? Why were the closed "
        "ones not merged? For bot PRs merged in H1 and in H2 (split by merge date), what was the median time "
        "from opening to merge, and did it change?",
    ),
    "R12": (
        ALL,
        "I review code in {slug} and want to know whether changes are getting bigger. Look at non-merge "
        "commits by humans (bots left out), and measure a commit's size as lines added plus lines deleted. "
        "Did the median commit size change between H1 and H2? In the window, what is the median size of fix "
        "commits, and of all other commits? {fix}",
    ),
}


def main():
    # Questions the no-tool floor caught stay in the file, marked, so the floor can still be regraded.
    dropped = set(json.loads(FLOOR.read_text())["dropped"]) if FLOOR.exists() else set()
    questions = []
    for template, (repos, text) in TEMPLATES.items():
        for repo in repos:
            s = REPOS[repo]
            body = text.format(
                slug=s["slug"], ci=s["ci"], label=s["label"], module=s["module"],
                landing=LANDING, fix=FIX_RULE, test=TEST_FILE,
            )  # fmt: skip
            questions.append(
                {
                    "id": f"{template}-{repo}",
                    "template": template,
                    "repo": repo,
                    "repo_slug": s["slug"],
                    "question": f"{body} {WINDOW}",
                    "in_study": f"{template}-{repo}" not in dropped,
                    "dropped_by": "no-tool floor" if f"{template}-{repo}" in dropped else None,
                }
            )
    OUT.write_text(json.dumps(questions, indent=2) + "\n")
    kept = sum(q["in_study"] for q in questions)
    print(f"wrote {OUT} with {len(questions)} questions, {kept} in the study")


if __name__ == "__main__":
    main()
