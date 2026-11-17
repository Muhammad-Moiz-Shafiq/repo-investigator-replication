from datetime import date

from repo_investigator.agent.schemas import IssuePRFilters
from repo_investigator.agent.tools.query_issues_prs import query_issues_prs


def test_bug_issue_filter_matches_ground_truth(db_conn):
    result = query_issues_prs(
        db_conn,
        "tokio-rs/tokio",
        IssuePRFilters(kind="issues", is_bug=True),
        date(2026, 9, 1),
        date(2026, 9, 22),
    )
    assert len(result.issues) == 7
    assert all(i.is_bug for i in result.issues)
    assert result.pull_requests == []


def test_merged_pr_filter_matches_ground_truth(db_conn):
    result = query_issues_prs(
        db_conn,
        "tokio-rs/tokio",
        IssuePRFilters(kind="pull_requests", state="MERGED"),
        date(2026, 9, 1),
        date(2026, 9, 22),
    )
    assert len(result.pull_requests) == 51
    assert all(p.state == "MERGED" for p in result.pull_requests)
    assert result.issues == []


def test_both_kind_populates_both_lists(db_conn):
    result = query_issues_prs(
        db_conn, "tokio-rs/tokio", IssuePRFilters(kind="both"), date(2026, 9, 1), date(2026, 9, 22)
    )
    assert len(result.issues) > 0
    assert len(result.pull_requests) > 0
