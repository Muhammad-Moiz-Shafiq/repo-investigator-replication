"""Screen candidate repos for the scaled study against the selection thresholds.

Pulls activity stats for the same 12-month window the pilot used, so new repos
are comparable to tokio, eslint and sqlalchemy (which are included as a
reference row, not as candidates). Writes a JSON dump and a markdown table to
docs/repo_screening/, so the selection can be rerun and checked later.

Needs a GitHub token: GITHUB_TOKEN, or falls back to `gh auth token`.

Usage:
  uv run python scripts/screen_repo_candidates.py
  uv run python scripts/screen_repo_candidates.py --repos owner/a,owner/b
"""

import argparse
import json
import os
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import httpx

WINDOW_START = "2025-09-23"
WINDOW_END = "2026-09-23"
OUT_DIR = Path(__file__).parent.parent / "docs" / "repo_screening"

REFERENCE_REPOS = ["tokio-rs/tokio", "eslint/eslint", "sqlalchemy/sqlalchemy"]
CANDIDATE_REPOS = [
    # Go
    "caddyserver/caddy",
    "charmbracelet/bubbletea",
    "golangci/golangci-lint",
    "gohugoio/hugo",
    "prometheus/prometheus",
    "spf13/cobra",
    # TypeScript
    "vitejs/vite",
    "prettier/prettier",
    "vitest-dev/vitest",
    "honojs/hono",
    # Java / Kotlin
    "square/okhttp",
    "mockito/mockito",
    "junit-team/junit-framework",
    "Kotlin/kotlinx.coroutines",
    # passed over in the pilot
    "astral-sh/ruff",
    "BurntSushi/ripgrep",
    "serde-rs/serde",
]

# Thresholds agreed 2026-10-19. A repo has to pass all of them to be eligible.
MIN_MERGED_PRS = 300
MIN_COMMITS = 300
MIN_CONTRIBUTORS = 10
MIN_CI_RUNS = 500
MIN_REVIEWED_SHARE = 0.5
MIN_BUG_ISSUES = 20
MAX_BOT_COMMIT_SHARE = 0.3

REVIEW_SAMPLE_SIZE = 100


def _token() -> str:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


class GitHub:
    def __init__(self, token: str):
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=60,
            follow_redirects=True,
        )

    def graphql(self, query: str, variables: dict) -> dict:
        payload = {"query": query, "variables": variables}
        resp = self.client.post("https://api.github.com/graphql", json=payload)
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise RuntimeError(body["errors"])
        return body["data"]

    def rest(self, path: str, params: dict | None = None) -> dict:
        resp = self.client.get(f"https://api.github.com{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def search_count(self, q: str) -> int:
        query = "query($q: String!) { search(query: $q, type: ISSUE, first: 0) { issueCount } }"
        data = self.graphql(query, {"q": q})
        return data["search"]["issueCount"]


REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    isArchived isFork isMirror stargazerCount hasIssuesEnabled
    primaryLanguage { name }
    owner { __typename }
    labels(first: 100) { nodes { name } }
  }
}
"""

HISTORY_QUERY = """
query($owner: String!, $name: String!, $since: GitTimestamp!, $until: GitTimestamp!, $after: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(since: $since, until: $until, first: 100, after: $after) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { author { user { login } name } }
      }
    } } }
  }
}
"""

REVIEW_SAMPLE_QUERY = """
query($q: String!, $n: Int!) {
  search(query: $q, type: ISSUE, first: $n) {
    nodes { ... on PullRequest { reviews(first: 1) { totalCount } } }
  }
}
"""


def ci_run_count(gh: GitHub, full_name: str) -> tuple[int, bool]:
    """Actions runs in the window. The API caps total_count at 2500 per query, so
    count one month at a time and flag the result if any month still hit the cap."""
    total, capped = 0, False
    start = date.fromisoformat(WINDOW_START)
    end = date.fromisoformat(WINDOW_END)
    while start < end:
        nxt = date(start.year + (start.month == 12), start.month % 12 + 1, start.day)
        nxt = min(nxt, end)
        count = gh.rest(
            f"/repos/{full_name}/actions/runs",
            {
                "created": f"{start}..{nxt - timedelta(days=1)}",
                "per_page": 1,
            },
        )["total_count"]
        total += count
        capped = capped or count >= 2500
        start = nxt
    return total, capped


def commit_authors(gh: GitHub, owner: str, name: str) -> tuple[int, set[str], int]:
    """Walk default-branch history in the window. Returns (total, distinct humans, bot commits)."""
    humans, bots, after, total = set(), 0, None, 0
    while True:
        data = gh.graphql(
            HISTORY_QUERY,
            {
                "owner": owner,
                "name": name,
                "after": after,
                "since": f"{WINDOW_START}T00:00:00Z",
                "until": f"{WINDOW_END}T00:00:00Z",
            },
        )
        history = data["repository"]["defaultBranchRef"]["target"]["history"]
        total = history["totalCount"]
        for node in history["nodes"]:
            login = (node["author"]["user"] or {}).get("login") or node["author"]["name"] or ""
            if login.endswith("[bot]") or "bot" in login.lower().split("-"):
                bots += 1
            else:
                humans.add(login)
        if not history["pageInfo"]["hasNextPage"]:
            return total, humans, bots
        after = history["pageInfo"]["endCursor"]


def screen(gh: GitHub, full_name: str) -> dict:
    owner, name = full_name.split("/")
    repo = gh.graphql(REPO_QUERY, {"owner": owner, "name": name})["repository"]
    window = f"{WINDOW_START}..{WINDOW_END}"

    merged_prs = gh.search_count(f"repo:{full_name} is:pr is:merged merged:{window}")
    issues_opened = gh.search_count(f"repo:{full_name} is:issue created:{window}")

    # \b keeps "debug" out, and "not bug" style labels mean the opposite
    label_names = [node["name"] for node in repo["labels"]["nodes"]]
    bug_labels = [
        n for n in label_names if re.search(r"\bbug\b", n, re.I) and not re.match(r"not\b", n, re.I)
    ]
    bug_issues = sum(
        gh.search_count(f'repo:{full_name} is:issue created:{window} label:"{label}"') for label in bug_labels
    )

    sample = gh.graphql(
        REVIEW_SAMPLE_QUERY,
        {
            "q": f"repo:{full_name} is:pr is:merged merged:{window} sort:updated-desc",
            "n": REVIEW_SAMPLE_SIZE,
        },
    )["search"]["nodes"]
    reviewed = sum(1 for pr in sample if pr["reviews"]["totalCount"] > 0)
    reviewed_share = reviewed / len(sample) if sample else 0.0

    ci_runs, ci_capped = ci_run_count(gh, full_name)

    commits, humans, bot_commits = commit_authors(gh, owner, name)

    row = {
        "repo": full_name,
        "language": (repo["primaryLanguage"] or {}).get("name"),
        "owner_type": repo["owner"]["__typename"],
        "stars": repo["stargazerCount"],
        "archived": repo["isArchived"],
        "fork_or_mirror": repo["isFork"] or repo["isMirror"],
        "issues_enabled": repo["hasIssuesEnabled"],
        "commits": commits,
        "contributors": len(humans),
        "bot_commit_share": round(bot_commits / commits, 3) if commits else 0.0,
        "merged_prs": merged_prs,
        "reviewed_share": round(reviewed_share, 2),
        "issues_opened": issues_opened,
        "bug_labels": bug_labels,
        "bug_issues": bug_issues,
        "ci_runs": f">={ci_runs}" if ci_capped else ci_runs,
        "ci_runs_count": ci_runs,
    }
    row["fails"] = failed_thresholds(row)
    return row


def failed_thresholds(row: dict) -> list[str]:
    checks = {
        "archived": not row["archived"],
        "fork/mirror": not row["fork_or_mirror"],
        "no issues": row["issues_enabled"],
        "commits": row["commits"] >= MIN_COMMITS,
        "merged PRs": row["merged_prs"] >= MIN_MERGED_PRS,
        "contributors": row["contributors"] >= MIN_CONTRIBUTORS,
        "bots": row["bot_commit_share"] <= MAX_BOT_COMMIT_SHARE,
        "reviews": row["reviewed_share"] >= MIN_REVIEWED_SHARE,
        "bug issues": row["bug_issues"] >= MIN_BUG_ISSUES,
        "CI runs": row["ci_runs_count"] >= MIN_CI_RUNS,
    }
    return [name for name, ok in checks.items() if not ok]


def to_markdown(rows: list[dict]) -> str:
    cols = [
        "repo",
        "language",
        "owner_type",
        "commits",
        "contributors",
        "bot_commit_share",
        "merged_prs",
        "reviewed_share",
        "issues_opened",
        "bug_issues",
        "ci_runs",
        "fails",
    ]
    lines = [
        f"# Repo screening, window {WINDOW_START} to {WINDOW_END}",
        "",
        f"Generated {date.today()} by scripts/screen_repo_candidates.py. Reference rows are the pilot repos.",
        "",
        "| " + " | ".join(cols) + " |",
        "|" + "---|" * len(cols),
    ]
    for r in rows:
        cells = [str(r[c]) if c != "fails" else (", ".join(r["fails"]) or "pass") for c in cols]
        if r["repo"] in REFERENCE_REPOS:
            cells[0] = f"{r['repo']} (pilot)"
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", help="comma-separated owner/name list, overrides the default candidates")
    args = parser.parse_args()
    repos = args.repos.split(",") if args.repos else REFERENCE_REPOS + CANDIDATE_REPOS

    gh = GitHub(_token())
    rows = []
    for full_name in repos:
        print(f"screening {full_name}")
        try:
            rows.append(screen(gh, full_name))
        except Exception as e:
            print(f"  failed: {e}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    (OUT_DIR / f"screening_{stamp}.json").write_text(json.dumps(rows, indent=2))
    (OUT_DIR / f"screening_{stamp}.md").write_text(to_markdown(rows))
    print(to_markdown(rows))


if __name__ == "__main__":
    main()
