import pytest

from repo_investigator.agent.tool_dispatch import dispatch_tool_call


def test_unknown_tool_name_raises_value_error(db_conn):
    with pytest.raises(ValueError, match="Unknown tool"):
        dispatch_tool_call(db_conn, "not_a_real_tool", {})


def test_strips_default_api_prefix_gemini_adds(db_conn):
    # Found via evaluation: gemini-2.5-flash-lite (through OpenRouter)
    # sometimes calls "default_api.query_ci_history" instead of
    # "query_ci_history" -- the tool it picked was correct, just wrapped.
    result = dispatch_tool_call(
        db_conn,
        "default_api.query_ci_history",
        {"repo": "eslint/eslint", "date_from": "2026-08-01", "date_to": "2026-08-31"},
    )
    assert "error" not in result


def test_does_not_reinterpret_a_genuinely_unknown_prefixed_name(db_conn):
    # A dotted name should only be reinterpreted if the suffix is a real
    # tool -- otherwise this would silently paper over hallucinated names.
    with pytest.raises(ValueError, match="Unknown tool"):
        dispatch_tool_call(db_conn, "default_api.not_a_real_tool", {})
