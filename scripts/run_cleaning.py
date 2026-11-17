import os
import sys

from repo_investigator.cleaning.clean_ci_runs import clean_ci_runs, read_raw_ci_runs
from repo_investigator.cleaning.clean_commit_files import clean_commit_files, read_raw_commit_files
from repo_investigator.cleaning.clean_commits import clean_commits, read_raw_commits
from repo_investigator.cleaning.clean_issues import bug_issue_numbers, clean_issues, read_raw_issues
from repo_investigator.cleaning.clean_pull_requests import (
    clean_pr_reviews,
    clean_pull_requests,
    read_raw_pull_requests,
)
from repo_investigator.cleaning.derived_metrics import (
    compute_contributor_bugfix_association,
    compute_daily_ci_failure_rate,
    compute_review_turnaround,
)
from repo_investigator.cleaning.spark_session import make_spark_session
from repo_investigator.db.connection import get_psycopg_connection, jdbc_url_and_properties
from repo_investigator.db.loaders import clear_repo_data, get_or_create_repo, write_table

REPOS = [
    "tokio-rs/tokio",
    "eslint/eslint",
    "sqlalchemy/sqlalchemy",
    "vitejs/vite",
    "junit-team/junit-framework",
    "prometheus/prometheus",
]
STAGING_DIR = "data/raw"


def clean_one_repo(spark, conn, jdbc_url, jdbc_props, owner: str, repo: str) -> None:
    repo_id = get_or_create_repo(conn, owner, repo)
    print(f"{owner}/{repo}: repo_id={repo_id}, clearing old data", flush=True)
    clear_repo_data(conn, repo_id)

    base = f"{STAGING_DIR}/{owner}/{repo}"

    # Issues must be cleaned before commits: commit is_bugfix depends on
    # knowing which issue numbers are bug-labeled.
    issues = clean_issues(read_raw_issues(spark, f"{base}/issues/*.json.gz"), repo_id)
    bug_nums = bug_issue_numbers(issues)
    write_table(issues, "issues", jdbc_url, jdbc_props)
    print(f"  issues written ({len(bug_nums)} bug-labeled issues found)", flush=True)

    commits = clean_commits(read_raw_commits(spark, f"{base}/commits/*.json.gz"), repo_id, bug_nums)
    commits.cache()
    write_table(commits, "commits", jdbc_url, jdbc_props)
    print("  commits written", flush=True)

    commit_files = clean_commit_files(read_raw_commit_files(spark, f"{base}/commit_files/*.json.gz"))
    commit_files.cache()
    write_table(commit_files, "commit_files", jdbc_url, jdbc_props)
    print("  commit_files written", flush=True)

    raw_prs = read_raw_pull_requests(spark, f"{base}/pull_requests/*.json.gz")
    prs = clean_pull_requests(raw_prs, repo_id)
    prs.cache()
    write_table(prs, "pull_requests", jdbc_url, jdbc_props)
    print("  pull_requests written", flush=True)

    pr_reviews = clean_pr_reviews(raw_prs, repo_id)
    pr_reviews.cache()
    write_table(pr_reviews, "pr_reviews", jdbc_url, jdbc_props)
    print("  pr_reviews written", flush=True)

    ci_runs = clean_ci_runs(read_raw_ci_runs(spark, f"{base}/ci_runs/*.json.gz"), repo_id)
    ci_runs.cache()
    write_table(ci_runs, "ci_runs", jdbc_url, jdbc_props)
    print("  ci_runs written", flush=True)

    write_table(compute_daily_ci_failure_rate(ci_runs), "daily_ci_failure_rate", jdbc_url, jdbc_props)
    write_table(compute_review_turnaround(prs, pr_reviews), "review_turnaround", jdbc_url, jdbc_props)
    write_table(
        compute_contributor_bugfix_association(commits, commit_files),
        "contributor_bugfix_association",
        jdbc_url,
        jdbc_props,
    )
    print(f"{owner}/{repo}: derived tables written", flush=True)


def main():
    spark = make_spark_session()
    conn = get_psycopg_connection(os.environ["DATABASE_URL"])
    jdbc_url, jdbc_props = jdbc_url_and_properties(os.environ["DATABASE_URL"])

    # pass owner/repo args to clean only those, e.g. new repos without
    # rewriting the pilot repos that are already loaded
    for repo_slug in sys.argv[1:] or REPOS:
        owner, repo = repo_slug.split("/")
        clean_one_repo(spark, conn, jdbc_url, jdbc_props, owner, repo)

    conn.close()
    spark.stop()
    print("All repos cleaned and loaded.")


if __name__ == "__main__":
    main()
