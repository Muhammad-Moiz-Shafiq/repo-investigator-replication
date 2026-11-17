"""Independent pandas implementation of the twelve answer-key calculations.

Run from the repository root with:

    uv run --env-file .env python independent_check/keys_pandas.py

Only SANDBOX_DATABASE_URL is used.  The script issues SELECT queries against the
six base tables named in the independent-check specification and writes its
result beside this file as keys_pandas.json.
"""

from __future__ import annotations

import json
import math
import os
import re
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

W_START = pd.Timestamp("2025-10-01T00:00:00Z")
H2_START = pd.Timestamp("2026-04-01T00:00:00Z")
W_END = pd.Timestamp("2026-09-21T00:00:00Z")

REPOS = ["tokio", "eslint", "sqlalchemy", "vite", "junit-framework", "prometheus"]
REVIEW_REPOS = [repo for repo in REPOS if repo != "sqlalchemy"]
R6_REPOS = ["eslint", "prometheus", "sqlalchemy", "vite"]
R11_REPOS = ["eslint", "vite", "junit-framework", "prometheus"]

SETTINGS = {
    "tokio": {"workflow_ids": {1972898}, "bug_label": "C-bug", "module_depth": 1},
    "eslint": {"workflow_ids": {27292}, "bug_label": "bug", "module_depth": 2},
    "sqlalchemy": {"workflow_ids": {971063}, "bug_label": "bug", "module_depth": 3},
    "vite": {"workflow_ids": {6990137}, "bug_label": "p3-minor-bug", "module_depth": 2},
    "junit-framework": {
        "workflow_ids": {24797, 277287548},
        "bug_label": "type: bug",
        "module_depth": 1,
    },
    "prometheus": {"workflow_ids": {34174364}, "bug_label": "kind/bug", "module_depth": 1},
}

BOT_LOGINS = {
    "renovate",
    "dependabot",
    "github-actions",
    "junit-builds",
    "copilot-pull-request-reviewer",
    "copilot-swe-agent",
    "Copilot",
}
FAILURES = {"failure", "timed_out", "startup_failure"}
PASSING = {"success"}
FIX_RE = re.compile(r"\b(?:fix|fixes|fixed|fixing|bugfix)\b", re.IGNORECASE)
TEST_DIRS = {"test", "tests", "__tests__", "testdata", "testing", "fixtures", "playground"}
TEST_DIR_SUFFIXES = ("-test", "-tests", "_test", "_tests")
DOC_DIRS = {"doc", "docs", "documentation", ".github", "changelog.d"}
DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
JS_TEST_RE = re.compile(r"\.(?:test|spec)\.(?:js|jsx|ts|tsx|mjs|cjs|mts|cts)$", re.IGNORECASE)
JAVA_TEST_SUFFIXES = ("Test.java", "Tests.java", "Test.kt", "Tests.kt")


def is_bot(login: object) -> bool:
    if login is None or pd.isna(login):
        return False
    value = str(login)
    return value in BOT_LOGINS or value.endswith("[bot]") or value.lower().endswith("bot")


def half(timestamp: object) -> str | None:
    if timestamp is None or pd.isna(timestamp):
        return None
    if W_START <= timestamp < H2_START:
        return "h1"
    if H2_START <= timestamp < W_END:
        return "h2"
    return None


def first_line_is_fix(message: object) -> bool:
    first_line = str(message).splitlines()[0] if message is not None else ""
    return FIX_RE.search(first_line) is not None


def path_parts(filename: object) -> tuple[list[str], str]:
    parts = str(filename).replace("\\", "/").split("/")
    return parts[:-1], parts[-1]


def is_test_file(filename: object) -> bool:
    folders, basename = path_parts(filename)
    lower_folders = [part.lower() for part in folders]
    if any(part in TEST_DIRS or part.endswith(TEST_DIR_SUFFIXES) for part in lower_folders):
        return True
    lower_name = basename.lower()
    if lower_name.endswith(("_test.go", "_test.py")):
        return True
    if lower_name.startswith("test_") and lower_name.endswith(".py"):
        return True
    if basename.endswith(JAVA_TEST_SUFFIXES):
        return True
    return JS_TEST_RE.search(basename) is not None


def is_doc_file(filename: object) -> bool:
    folders, basename = path_parts(filename)
    if any(part.lower() in DOC_DIRS for part in folders):
        return True
    return basename.lower().endswith(DOC_SUFFIXES)


def module_for(filename: object, depth: int) -> str | None:
    folders, _ = path_parts(filename)
    if len(folders) < depth:
        return None
    return "/".join(folders[:depth])


def log_choose(n: int, k: int) -> float:
    if k < 0 or k > n:
        return -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact_two_sided(table: list[list[int]]) -> float:
    """Two-sided Fisher exact p-value using probability ordering (SciPy convention)."""
    a, b = (int(value) for value in table[0])
    c, d = (int(value) for value in table[1])
    row1, row2 = a + b, c + d
    col1 = a + c
    total = row1 + row2
    if total == 0:
        return 1.0

    low = max(0, col1 - row2)
    high = min(row1, col1)

    def log_probability(x: int) -> float:
        return log_choose(col1, x) + log_choose(total - col1, row1 - x) - log_choose(total, row1)

    observed_logp = log_probability(a)
    selected = [log_probability(x) for x in range(low, high + 1)]
    selected = [value for value in selected if value <= observed_logp + 1e-12]
    if not selected:
        return 0.0
    maximum = max(selected)
    return min(1.0, math.exp(maximum) * sum(math.exp(value - maximum) for value in selected))


def binomial_exact_two_sided(successes: int, trials: int) -> float:
    """Exact two-sided binomial p-value at p=0.5 using probability ordering."""
    if trials == 0:
        return 1.0
    observed_logp = log_choose(trials, successes) - trials * math.log(2)
    selected = []
    for value in range(trials + 1):
        logp = log_choose(trials, value) - trials * math.log(2)
        if logp <= observed_logp + 1e-12:
            selected.append(logp)
    maximum = max(selected)
    return min(1.0, math.exp(maximum) * sum(math.exp(value - maximum) for value in selected))


def rate_verdict(h1_fail: int, h1_total: int, h2_fail: int, h2_total: int) -> str:
    p_value = fisher_exact_two_sided([[h1_fail, h1_total - h1_fail], [h2_fail, h2_total - h2_fail]])
    if p_value >= 0.05 or h1_total == 0 or h2_total == 0:
        return "no clear change"
    return "up" if h2_fail / h2_total > h1_fail / h1_total else "down"


def stable_seed(label: str) -> int:
    return zlib.crc32(label.encode("utf-8"))


def median_verdict(h1: pd.Series, h2: pd.Series, label: str) -> str:
    first = h1.dropna().to_numpy(dtype=float)
    second = h2.dropna().to_numpy(dtype=float)
    if len(first) < 10 or len(second) < 10:
        return "too few"

    median1 = float(np.median(first))
    median2 = float(np.median(second))
    observed_ratio = (1.0 if median2 == 0 else math.inf) if median1 == 0 else median2 / median1

    rng = np.random.default_rng(stable_seed(label))
    first_samples = rng.choice(first, size=(4000, len(first)), replace=True)
    second_samples = rng.choice(second, size=(4000, len(second)), replace=True)
    first_medians = np.median(first_samples, axis=1)
    second_medians = np.median(second_samples, axis=1)
    ratios = np.divide(
        second_medians,
        first_medians,
        out=np.full(4000, np.inf),
        where=first_medians != 0,
    )
    ratios[(first_medians == 0) & (second_medians == 0)] = 1.0
    lower, upper = np.percentile(ratios, [2.5, 97.5])
    if lower > 1 and observed_ratio >= 1.2:
        return "up"
    if upper < 1 and observed_ratio <= 1 / 1.2:
        return "down"
    return "no clear change"


def json_float(value: object) -> float | None:
    if value is None or pd.isna(value) or not math.isfinite(float(value)):
        return None
    return float(value)


def fraction(numerator: int, denominator: int) -> float | None:
    return float(numerator / denominator) if denominator else None


def read_frame(connection: psycopg.Connection, query: str) -> pd.DataFrame:
    with connection.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
        columns = [column.name for column in cursor.description]
    return pd.DataFrame(rows, columns=columns)


def load_data(connection: psycopg.Connection) -> dict[str, pd.DataFrame]:
    repo_filter = "('tokio','eslint','sqlalchemy','vite','junit-framework','prometheus')"
    queries = {
        "commits": f"""
            SELECT r.name AS repo, c.sha, c.author_login, c.author_email,
                   c.committed_at, c.message, c.is_merge, c.additions, c.deletions
            FROM commits c JOIN repos r ON r.id = c.repo_id
            WHERE r.name IN {repo_filter}
        """,
        "commit_files": f"""
            SELECT r.name AS repo, cf.commit_sha, cf.filename
            FROM commit_files cf
            JOIN commits c ON c.sha = cf.commit_sha
            JOIN repos r ON r.id = c.repo_id
            WHERE r.name IN {repo_filter}
        """,
        "pull_requests": f"""
            SELECT r.name AS repo, p.number, p.author_login, p.created_at, p.merged_at,
                   p.closed_at, p.title
            FROM pull_requests p JOIN repos r ON r.id = p.repo_id
            WHERE r.name IN {repo_filter}
        """,
        "pr_reviews": f"""
            SELECT r.name AS repo, v.id, v.pr_number, v.reviewer_login, v.state, v.submitted_at
            FROM pr_reviews v JOIN repos r ON r.id = v.repo_id
            WHERE r.name IN {repo_filter}
        """,
        "issues": f"""
            SELECT r.name AS repo, i.number, i.created_at, i.closed_at, i.labels
            FROM issues i JOIN repos r ON r.id = i.repo_id
            WHERE r.name IN {repo_filter}
        """,
        "ci_runs": f"""
            SELECT r.name AS repo, ci.id, ci.commit_sha, ci.workflow_id, ci.conclusion,
                   ci.event, ci.run_attempt, ci.started_at, ci.completed_at, ci.duration_seconds
            FROM ci_runs ci JOIN repos r ON r.id = ci.repo_id
            WHERE r.name IN {repo_filter}
        """,
    }
    frames = {name: read_frame(connection, query) for name, query in queries.items()}
    datetime_columns = {
        "commits": ["committed_at"],
        "pull_requests": ["created_at", "merged_at", "closed_at"],
        "pr_reviews": ["submitted_at"],
        "issues": ["created_at", "closed_at"],
        "ci_runs": ["started_at", "completed_at"],
    }
    for frame_name, columns in datetime_columns.items():
        for column in columns:
            frames[frame_name][column] = pd.to_datetime(frames[frame_name][column], utc=True)
    return frames


def prepare(data: dict[str, pd.DataFrame]) -> None:
    commits = data["commits"]
    commits["is_bot"] = commits["author_login"].map(is_bot)
    automation = commits["author_login"].isna() & commits["author_email"].isin(
        ["jenkins@eslint-03", "eslint@googlegroups.com"]
    )
    commits["human"] = ~commits["is_merge"] & ~commits["is_bot"] & ~automation
    commits["fix"] = commits["human"] & commits["message"].map(first_line_is_fix)
    commits["half"] = commits["committed_at"].map(half)
    commits["person"] = commits["author_login"].where(
        commits["author_login"].notna(), commits["author_email"]
    )

    data["commit_files"]["is_test"] = data["commit_files"]["filename"].map(is_test_file)
    data["commit_files"]["is_doc"] = data["commit_files"]["filename"].map(is_doc_file)

    prs = data["pull_requests"]
    prs["author_is_bot"] = prs["author_login"].map(is_bot)
    prs["merged_half"] = prs["merged_at"].map(half)

    reviews = data["pr_reviews"]
    reviews["reviewer_is_bot"] = reviews["reviewer_login"].map(is_bot)


def landing_runs(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ci = data["ci_runs"]
    commits = data["commits"][["repo", "sha"]]
    eligible = ci[
        ci.apply(lambda row: row["workflow_id"] in SETTINGS[row["repo"]]["workflow_ids"], axis=1)
        & ci["event"].eq("push")
        & ci["started_at"].notna()
    ].copy()
    eligible = eligible.merge(commits, left_on=["repo", "commit_sha"], right_on=["repo", "sha"], how="inner")
    eligible = eligible.sort_values(["repo", "commit_sha", "started_at", "id"])
    landing = eligible.drop_duplicates(["repo", "commit_sha"], keep="first").copy()
    landing["half"] = landing["started_at"].map(half)
    landing["counted"] = landing["conclusion"].notna() & ~landing["conclusion"].isin(["cancelled", "skipped"])
    landing["failing"] = landing["conclusion"].isin(FAILURES)
    landing["passing"] = landing["conclusion"].isin(PASSING)
    return landing


def compute_r1(landing: pd.DataFrame) -> dict:
    result = {}
    for repo in REPOS:
        rows = landing[(landing["repo"] == repo) & landing["counted"]]
        values = {}
        counts = {}
        for period in ("h1", "h2"):
            period_rows = rows[rows["half"] == period]
            total = len(period_rows)
            failures = int(period_rows["failing"].sum())
            rerun_passes = int(
                ((period_rows["run_attempt"] > 1) & period_rows["conclusion"].eq("success")).sum()
            )
            counts[period] = (failures, total)
            values[f"{period}_failing"] = failures
            values[f"{period}_counted"] = total
            values[f"{period}_rate"] = fraction(failures, total)
            values[f"{period}_rerun_pass_share"] = fraction(rerun_passes, total)
        values["verdict"] = rate_verdict(*counts["h1"], *counts["h2"])
        result[repo] = values
    return result


def compute_r2(data: dict[str, pd.DataFrame], landing: pd.DataFrame) -> dict:
    result = {}
    ci = data["ci_runs"]
    for repo in REPOS:
        values = {}
        main = landing[
            (landing["repo"] == repo)
            & landing["conclusion"].eq("success")
            & landing["duration_seconds"].notna()
        ].copy()
        main["minutes"] = main["duration_seconds"] / 60
        main_h1 = main.loc[main["half"] == "h1", "minutes"]
        main_h2 = main.loc[main["half"] == "h2", "minutes"]
        values["main_h1_min"] = json_float(main_h1.median())
        values["main_h2_min"] = json_float(main_h2.median())
        values["main_verdict"] = median_verdict(main_h1, main_h2, f"R2:{repo}:main")

        pr = ci[
            (ci["repo"] == repo)
            & ci["workflow_id"].isin(SETTINGS[repo]["workflow_ids"])
            & ci["event"].eq("pull_request")
            & ci["conclusion"].eq("success")
            & ci["duration_seconds"].notna()
        ].copy()
        pr["half"] = pr["started_at"].map(half)
        pr["minutes"] = pr["duration_seconds"] / 60
        pr_h1 = pr.loc[pr["half"] == "h1", "minutes"]
        pr_h2 = pr.loc[pr["half"] == "h2", "minutes"]
        values["pr_h1_min"] = json_float(pr_h1.median())
        values["pr_h2_min"] = json_float(pr_h2.median())
        values["pr_verdict"] = median_verdict(pr_h1, pr_h2, f"R2:{repo}:pr")
        result[repo] = values
    return result


def eligible_reviews(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    reviews = data["pr_reviews"].merge(
        data["pull_requests"][["repo", "number", "author_login", "created_at", "merged_at"]],
        left_on=["repo", "pr_number"],
        right_on=["repo", "number"],
        how="inner",
    )
    return reviews[
        reviews["reviewer_login"].notna()
        & reviews["reviewer_login"].ne(reviews["author_login"])
        & ~reviews["reviewer_is_bot"]
        & reviews["merged_at"].notna()
        & (reviews["submitted_at"] <= reviews["merged_at"])
    ].copy()


def compute_r3(data: dict[str, pd.DataFrame], reviews: pd.DataFrame) -> dict:
    result = {}
    prs = data["pull_requests"]
    for repo in REVIEW_REPOS:
        merged = prs[(prs["repo"] == repo) & prs["merged_at"].notna() & ~prs["author_is_bot"]].copy()
        first = (
            reviews[reviews["repo"] == repo]
            .sort_values(["pr_number", "submitted_at", "id"])
            .drop_duplicates("pr_number", keep="first")[["pr_number", "submitted_at"]]
        )
        merged = merged.merge(first, left_on="number", right_on="pr_number", how="left")
        merged["wait_h"] = (merged["submitted_at"] - merged["created_at"]).dt.total_seconds() / 3600
        merged["after_h"] = (merged["merged_at"] - merged["submitted_at"]).dt.total_seconds() / 3600
        with_review = merged[merged["submitted_at"].notna()]
        wait_h1 = with_review.loc[with_review["merged_half"] == "h1", "wait_h"]
        wait_h2 = with_review.loc[with_review["merged_half"] == "h2", "wait_h"]
        after_h1 = with_review.loc[with_review["merged_half"] == "h1", "after_h"]
        after_h2 = with_review.loc[with_review["merged_half"] == "h2", "after_h"]
        h2 = merged[merged["merged_half"] == "h2"]
        result[repo] = {
            "wait_h1_h": json_float(wait_h1.median()),
            "wait_h2_h": json_float(wait_h2.median()),
            "wait_verdict": median_verdict(wait_h1, wait_h2, f"R3:{repo}:wait"),
            "after_h1_h": json_float(after_h1.median()),
            "after_h2_h": json_float(after_h2.median()),
            "after_verdict": median_verdict(after_h1, after_h2, f"R3:{repo}:after"),
            "h2_no_review_share": fraction(int(h2["submitted_at"].isna().sum()), len(h2)),
        }
    return result


def compute_r4(data: dict[str, pd.DataFrame], reviews: pd.DataFrame) -> dict:
    result = {}
    prs = data["pull_requests"]
    approved_pairs = reviews[reviews["state"].eq("APPROVED")][["repo", "pr_number"]].drop_duplicates()
    for repo in REVIEW_REPOS:
        merged = prs[(prs["repo"] == repo) & (prs["merged_half"] == "h2")].copy()
        approved_numbers = set(approved_pairs.loc[approved_pairs["repo"] == repo, "pr_number"])
        unapproved = merged[~merged["number"].isin(approved_numbers)]
        result[repo] = {
            "merged_h2": len(merged),
            "unapproved": len(unapproved),
            "unapproved_share": fraction(len(unapproved), len(merged)),
            "unapproved_bot_prs": int(unapproved["author_is_bot"].sum()),
        }
    return result


def compute_r5(data: dict[str, pd.DataFrame]) -> dict:
    result = {}
    issues = data["issues"]
    for repo in REPOS:
        label = SETTINGS[repo]["bug_label"]
        bugs = issues[
            (issues["repo"] == repo) & issues["labels"].map(lambda labels, wanted=label: wanted in labels)
        ]
        opened = int(((bugs["created_at"] >= W_START) & (bugs["created_at"] < W_END)).sum())
        closed = int(((bugs["closed_at"] >= W_START) & (bugs["closed_at"] < W_END)).sum())
        trials = opened + closed
        p_value = binomial_exact_two_sided(closed, trials)
        if p_value < 0.05 and opened > closed:
            verdict = "growing"
        elif p_value < 0.05 and closed > opened:
            verdict = "shrinking"
        else:
            verdict = "balanced"

        h1 = bugs[(bugs["created_at"] >= W_START) & (bugs["created_at"] < H2_START)].copy()
        h1["not_closed"] = h1["closed_at"].isna() | (h1["closed_at"] >= W_END)
        h1["days"] = (h1["closed_at"] - h1["created_at"]).dt.total_seconds() / 86400
        h1.loc[h1["not_closed"], "days"] = math.inf
        median_days = h1["days"].median()
        result[repo] = {
            "opened": opened,
            "closed": closed,
            "verdict": verdict,
            "h1_bugs": len(h1),
            "median_days_to_close": json_float(median_days),
            "share_not_closed": fraction(int(h1["not_closed"].sum()), len(h1)),
        }
    return result


def compute_r6(data: dict[str, pd.DataFrame]) -> dict:
    result = {}
    commits = data["commits"]
    files = data["commit_files"]
    for repo in R6_REPOS:
        selected_commits = commits[
            (commits["repo"] == repo)
            & commits["human"]
            & (commits["committed_at"] >= W_START)
            & (commits["committed_at"] < W_END)
        ][["sha", "fix"]]
        selected_files = files[(files["repo"] == repo) & ~files["is_test"] & ~files["is_doc"]].copy()
        depth = SETTINGS[repo]["module_depth"]
        selected_files["module"] = selected_files["filename"].map(
            lambda name, module_depth=depth: module_for(name, module_depth)
        )
        touches = (
            selected_files.dropna(subset=["module"])[["commit_sha", "module"]]
            .drop_duplicates()
            .merge(selected_commits, left_on="commit_sha", right_on="sha", how="inner")
        )
        summary = touches.groupby("module", as_index=False).agg(
            commits=("commit_sha", "nunique"), fixes=("fix", "sum")
        )
        summary["fix_share"] = summary["fixes"] / summary["commits"]
        most = summary.sort_values(["fixes", "commits", "module"], ascending=[False, False, True]).iloc[0]
        eligible = summary[summary["commits"] >= 20]
        top_share = eligible.sort_values(
            ["fix_share", "fixes", "commits", "module"], ascending=[False, False, False, True]
        ).iloc[0]
        result[repo] = {
            "most_fixes_module": most["module"],
            "most_fixes_count": int(most["fixes"]),
            "most_fixes_module_commits": int(most["commits"]),
            "top_share_module": top_share["module"],
            "top_share": float(top_share["fix_share"]),
        }
    return result


def compute_r7(landing: pd.DataFrame) -> dict:
    result = {}
    for repo in REPOS:
        rows = landing[(landing["repo"] == repo) & landing["counted"]].sort_values(["started_at", "id"])
        records = list(rows.to_dict("records"))
        streaks = []
        index = 1
        while index < len(records) - 1:
            if records[index - 1]["passing"] and records[index]["failing"]:
                first = index
                while index < len(records) and records[index]["failing"]:
                    index += 1
                if index < len(records) and records[index]["passing"]:
                    first_row = records[first]
                    next_pass = records[index]
                    if (
                        half(first_row["started_at"]) == "h2"
                        and pd.notna(first_row["completed_at"])
                        and pd.notna(next_pass["completed_at"])
                    ):
                        hours = (next_pass["completed_at"] - first_row["completed_at"]).total_seconds() / 3600
                        streaks.append(
                            {
                                "first_failing_sha": first_row["commit_sha"],
                                "next_passing_sha": next_pass["commit_sha"],
                                "failing_commits": index - first,
                                "hours_red": float(hours),
                            }
                        )
                continue
            index += 1
        streaks.sort(key=lambda row: (-row["hours_red"], -row["failing_commits"], row["first_failing_sha"]))
        result[repo] = (
            streaks[0]
            if streaks
            else {
                "first_failing_sha": "",
                "next_passing_sha": "",
                "failing_commits": 0,
                "hours_red": 0.0,
            }
        )
    return result


def compute_r8(data: dict[str, pd.DataFrame]) -> dict:
    result = {}
    commits = data["commits"]
    for repo in REPOS:
        selected = commits[(commits["repo"] == repo) & commits["human"]]
        counts = {}
        shares = {}
        for period in ("h1", "h2"):
            period_rows = selected[selected["half"] == period]
            people = period_rows.groupby("person", dropna=False).size().sort_values(ascending=False)
            top_two = int(people.head(2).sum())
            total = len(period_rows)
            counts[period] = (top_two, total)
            shares[period] = fraction(top_two, total)
        p_value = fisher_exact_two_sided(
            [
                [counts["h1"][0], counts["h1"][1] - counts["h1"][0]],
                [counts["h2"][0], counts["h2"][1] - counts["h2"][0]],
            ]
        )
        difference = shares["h2"] - shares["h1"]
        if p_value < 0.05 and difference >= 0.05:
            verdict = "more concentrated"
        elif p_value < 0.05 and difference <= -0.05:
            verdict = "less concentrated"
        else:
            verdict = "no clear change"
        result[repo] = {
            "h1_top2_share": shares["h1"],
            "h2_top2_share": shares["h2"],
            "verdict": verdict,
        }
    return result


def compute_r9(data: dict[str, pd.DataFrame]) -> dict:
    result = {}
    reviews = data["pr_reviews"].merge(
        data["pull_requests"][["repo", "number", "author_login"]],
        left_on=["repo", "pr_number"],
        right_on=["repo", "number"],
        how="inner",
    )
    reviews = reviews[
        reviews["submitted_at"].map(half).eq("h2")
        & reviews["reviewer_login"].notna()
        & reviews["reviewer_login"].ne(reviews["author_login"])
        & ~reviews["reviewer_is_bot"]
    ][["repo", "pr_number", "reviewer_login"]].drop_duplicates()
    for repo in REVIEW_REPOS:
        selected = reviews[reviews["repo"] == repo]
        pair_counts = selected.groupby("reviewer_login").size().sort_values(ascending=False)
        result[repo] = {
            "reviewers": int(selected["reviewer_login"].nunique()),
            "top2_share": fraction(int(pair_counts.head(2).sum()), len(selected)),
        }
    return result


def compute_r10(data: dict[str, pd.DataFrame]) -> dict:
    result = {}
    commits = data["commits"]
    test_commits = set(data["commit_files"].loc[data["commit_files"]["is_test"], "commit_sha"])
    for repo in REPOS:
        fixes = commits[
            (commits["repo"] == repo)
            & commits["fix"]
            & (commits["committed_at"] >= W_START)
            & (commits["committed_at"] < W_END)
        ]
        changed_test = int(fixes["sha"].isin(test_commits).sum())
        result[repo] = {
            "fix_commits": len(fixes),
            "share_changed_test": fraction(changed_test, len(fixes)),
        }
    return result


def compute_r11(data: dict[str, pd.DataFrame]) -> dict:
    result = {}
    prs = data["pull_requests"]
    for repo in R11_REPOS:
        dependency_prs = prs[
            (prs["repo"] == repo) & prs["author_login"].isin(["renovate", "dependabot"])
        ].copy()
        opened = dependency_prs[
            (dependency_prs["created_at"] >= W_START) & (dependency_prs["created_at"] < W_END)
        ]
        merged_count = int((opened["merged_at"] < W_END).sum())
        closed_unmerged = opened[opened["merged_at"].isna() & (opened["closed_at"] < W_END)]
        autoclosed_count = int(
            closed_unmerged["title"].str.contains("autoclosed", case=False, regex=False, na=False).sum()
        )

        # This cohort includes PRs opened before W, unlike the share denominators above.
        dependency_prs["merge_hours"] = (
            dependency_prs["merged_at"] - dependency_prs["created_at"]
        ).dt.total_seconds() / 3600
        h1 = dependency_prs.loc[dependency_prs["merged_half"] == "h1", "merge_hours"]
        h2 = dependency_prs.loc[dependency_prs["merged_half"] == "h2", "merge_hours"]
        result[repo] = {
            "opened": len(opened),
            "merged_share": fraction(merged_count, len(opened)),
            "closed_unmerged_share": fraction(len(closed_unmerged), len(opened)),
            "closed_autoclosed_share": fraction(autoclosed_count, len(closed_unmerged)),
            "merge_h1_h": json_float(h1.median()),
            "merge_h2_h": json_float(h2.median()),
            "merge_verdict": median_verdict(h1, h2, f"R11:{repo}:merge"),
        }
    return result


def compute_r12(data: dict[str, pd.DataFrame]) -> dict:
    result = {}
    commits = data["commits"]
    for repo in REPOS:
        human = commits[
            (commits["repo"] == repo)
            & commits["human"]
            & (commits["committed_at"] >= W_START)
            & (commits["committed_at"] < W_END)
        ].copy()
        human["size"] = human["additions"] + human["deletions"]
        h1 = human.loc[human["half"] == "h1", "size"]
        h2 = human.loc[human["half"] == "h2", "size"]
        result[repo] = {
            "h1_median_lines": json_float(h1.median()),
            "h2_median_lines": json_float(h2.median()),
            "verdict": median_verdict(h1, h2, f"R12:{repo}:size"),
            "fix_median_lines": json_float(human.loc[human["fix"], "size"].median()),
            "other_median_lines": json_float(human.loc[~human["fix"], "size"].median()),
        }
    return result


def main() -> None:
    database_url = os.environ.get("SANDBOX_DATABASE_URL")
    if not database_url:
        raise RuntimeError("SANDBOX_DATABASE_URL is required; DATABASE_URL is intentionally unused")

    with psycopg.connect(database_url) as connection:
        connection.read_only = True
        data = load_data(connection)

    prepare(data)
    landing = landing_runs(data)
    reviews = eligible_reviews(data)
    result = {
        "R1": compute_r1(landing),
        "R2": compute_r2(data, landing),
        "R3": compute_r3(data, reviews),
        "R4": compute_r4(data, reviews),
        "R5": compute_r5(data),
        "R6": compute_r6(data),
        "R7": compute_r7(landing),
        "R8": compute_r8(data),
        "R9": compute_r9(data),
        "R10": compute_r10(data),
        "R11": compute_r11(data),
        "R12": compute_r12(data),
    }

    output_path = Path(__file__).with_name("keys_pandas.json")
    output_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
