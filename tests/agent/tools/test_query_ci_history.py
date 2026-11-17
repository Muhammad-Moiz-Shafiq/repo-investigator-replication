from datetime import date

from repo_investigator.agent.tools.query_ci_history import query_ci_history

# Ground truth hand-computed directly from Postgres (see agent_methodology_log.md):
# summing daily_ci_failure_rate rows for tokio-rs/tokio, 2026-09-15 to 2026-09-22,
# independently of the tool's own SQL.
TOKIO_TOTAL_RUNS = 357
TOKIO_FAILED_RUNS = 15
TOKIO_FAILURE_RATE = 0.042


def test_matches_hand_computed_ground_truth(db_conn):
    result = query_ci_history(db_conn, "tokio-rs/tokio", date(2026, 9, 15), date(2026, 9, 22))
    assert result.total_runs == TOKIO_TOTAL_RUNS
    assert result.failed_runs == TOKIO_FAILED_RUNS
    assert result.overall_failure_rate == TOKIO_FAILURE_RATE
    assert len(result.by_workflow) > 0
    assert len(result.by_day) > 0


def test_unknown_repo_returns_honest_empty_result_not_zero(db_conn):
    result = query_ci_history(db_conn, "fake-owner/fake-repo", date(2026, 1, 1), date(2026, 1, 2))
    assert result.total_runs == 0
    assert result.overall_failure_rate is None  # not a fake 0.0 -- there's no data, not a 0% rate
    assert result.by_workflow == []
