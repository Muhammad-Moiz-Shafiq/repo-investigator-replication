"""Checks that cleaning from the gzipped raw files reproduces the database exactly.

Second half of the compression check (the first half is the per-file hash
check in compress_raw_storage.py). For each repo, this runs the same cleaning
functions run_cleaning.py uses, but on the staged .json.gz files, and
compares every resulting table against what is already in Postgres, row by
row in both directions. It only reads from the database, never writes.

Columns are compared as strings after casting the cleaned value to the
database column's type, so int vs bigint or double vs NUMERIC(5,4) rounding
don't show up as false differences. Generated id columns are skipped since
they only exist on the database side.

Usage (after staging the .gz files with stage_raw_data.py):
  uv run python scripts/verify_compressed_cleaning.py
"""

import os
import sys

from dotenv import load_dotenv
from pyspark.sql import functions as F
from run_cleaning import REPOS, STAGING_DIR

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


def cleaned_tables(spark, base: str, repo_id: int) -> dict:
    issues = clean_issues(read_raw_issues(spark, f"{base}/issues/*.json.gz"), repo_id)
    commits = clean_commits(
        read_raw_commits(spark, f"{base}/commits/*.json.gz"), repo_id, bug_issue_numbers(issues)
    )
    commit_files = clean_commit_files(read_raw_commit_files(spark, f"{base}/commit_files/*.json.gz"))
    raw_prs = read_raw_pull_requests(spark, f"{base}/pull_requests/*.json.gz")
    prs = clean_pull_requests(raw_prs, repo_id)
    pr_reviews = clean_pr_reviews(raw_prs, repo_id)
    ci_runs = clean_ci_runs(read_raw_ci_runs(spark, f"{base}/ci_runs/*.json.gz"), repo_id)
    return {
        "issues": issues,
        "commits": commits,
        "commit_files": commit_files,
        "pull_requests": prs,
        "pr_reviews": pr_reviews,
        "ci_runs": ci_runs,
        "daily_ci_failure_rate": compute_daily_ci_failure_rate(ci_runs),
        "review_turnaround": compute_review_turnaround(prs, pr_reviews),
        "contributor_bugfix_association": compute_contributor_bugfix_association(commits, commit_files),
    }


def db_table(spark, jdbc_url: str, jdbc_props: dict, table: str, repo_id: int):
    if table == "commit_files":
        # no repo_id column, so scope it through the parent commits
        where = f"commit_sha IN (SELECT sha FROM commits WHERE repo_id = {repo_id})"
    else:
        where = f"repo_id = {repo_id}"
    return (
        spark.read.format("jdbc")
        .option("url", jdbc_url)
        .option("query", f"SELECT * FROM {table} WHERE {where}")  # noqa: S608
        .option("user", jdbc_props["user"])
        .option("password", jdbc_props["password"])
        .option("driver", jdbc_props["driver"])
        .load()
    )


def compare(cleaned, stored) -> tuple[int, int, int, int]:
    """Returns (cleaned rows, stored rows, only in cleaned, only in stored)."""
    stored_types = dict(stored.dtypes)
    cols = [c for c in cleaned.columns if c in stored_types]
    as_db_type = cleaned.select(
        [F.col(c).cast(stored.schema[c].dataType).cast("string").alias(c) for c in cols]
    )
    as_stored = stored.select([F.col(c).cast("string").alias(c) for c in cols])
    return (
        as_db_type.count(),
        as_stored.count(),
        as_db_type.exceptAll(as_stored).count(),
        as_stored.exceptAll(as_db_type).count(),
    )


def main():
    load_dotenv()
    spark = make_spark_session()
    conn = get_psycopg_connection(os.environ["DATABASE_URL"])
    jdbc_url, jdbc_props = jdbc_url_and_properties(os.environ["DATABASE_URL"])

    all_match = True
    for slug in REPOS:
        owner, repo = slug.split("/")
        row = conn.execute("SELECT id FROM repos WHERE owner = %s AND name = %s", (owner, repo)).fetchone()
        repo_id = row[0]
        print(f"{slug} (repo_id={repo_id})")
        for table, cleaned in cleaned_tables(spark, f"{STAGING_DIR}/{owner}/{repo}", repo_id).items():
            n_clean, n_db, only_clean, only_db = compare(
                cleaned, db_table(spark, jdbc_url, jdbc_props, table, repo_id)
            )
            ok = n_clean == n_db and only_clean == 0 and only_db == 0
            all_match = all_match and ok
            status = "OK" if ok else "MISMATCH"
            print(f"  {table:32s} cleaned={n_clean:6d} db={n_db:6d} diff={only_clean}/{only_db} {status}")

    conn.close()
    spark.stop()
    print("ALL TABLES MATCH" if all_match else "MISMATCHES FOUND")
    sys.exit(0 if all_match else 1)


if __name__ == "__main__":
    main()
