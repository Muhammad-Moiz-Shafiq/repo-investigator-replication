from repo_investigator.agent.tools.fetch_commit_diff import fetch_commit_diff

TOKIO_SHA = "3930bd182cb18b534a34af86874a427da4a03c45"


def test_matches_ground_truth_from_postgres(db_conn):
    result = fetch_commit_diff(db_conn, "tokio-rs/tokio", TOKIO_SHA)
    assert result.found is True
    assert result.author_login == "philphauler"
    assert result.is_bugfix is False
    assert len(result.files) == 1
    assert result.files[0].filename == "tokio/src/net/windows/named_pipe.rs"
    assert result.files[0].additions == 18
    assert result.files[0].deletions == 0


def test_nonexistent_sha_returns_found_false(db_conn):
    result = fetch_commit_diff(db_conn, "tokio-rs/tokio", "0" * 40)
    assert result.found is False
    assert result.files == []


def test_cross_repo_scoping_rejects_sha_from_different_repo(db_conn):
    # commits.sha is a global primary key, not scoped per repo -- without an
    # explicit repo_id check, a real tokio sha could wrongly "match" when
    # queried as if it belonged to a different repo.
    result = fetch_commit_diff(db_conn, "eslint/eslint", TOKIO_SHA)
    assert result.found is False
