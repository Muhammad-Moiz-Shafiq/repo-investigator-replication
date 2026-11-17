from datetime import date

from repo_investigator.agent.tools.query_review_approval_stats import query_review_approval_stats


def test_matches_ground_truth_for_tokio(db_conn):
    # Ground truth computed independently via direct SQL (see
    # docs/ground_truth_answers.md): 419 merged PRs, 409 with approval.
    result = query_review_approval_stats(db_conn, "tokio-rs/tokio", date(2025, 9, 29), date(2026, 9, 23))
    assert result.total_merged_prs == 419
    assert result.prs_with_approval == 409
    assert result.prs_without_approval == 10
    assert result.approval_rate == 0.9761


def test_unknown_repo_returns_zeroed_result_not_an_error(db_conn):
    result = query_review_approval_stats(db_conn, "not/a-real-repo", date(2025, 9, 29), date(2026, 9, 23))
    assert result.total_merged_prs == 0
    assert result.approval_rate is None


def test_no_prs_in_range_gives_none_rate_not_division_by_zero(db_conn):
    result = query_review_approval_stats(db_conn, "tokio-rs/tokio", date(2010, 1, 1), date(2010, 1, 2))
    assert result.total_merged_prs == 0
    assert result.approval_rate is None
