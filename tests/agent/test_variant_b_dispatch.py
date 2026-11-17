from unittest.mock import MagicMock, patch

import pytest

from repo_investigator.agent.variant_b_dispatch import make_variant_b_dispatch_fn


@patch("repo_investigator.agent.variant_b_dispatch.run_python_in_sandbox")
def test_dispatches_execute_python_to_the_sandbox_with_the_configured_url(mock_run):
    mock_run.return_value = {"stdout": "42\n", "stderr": "", "exit_code": 0, "timed_out": False}
    dispatch = make_variant_b_dispatch_fn("postgresql://sandbox-url")

    result = dispatch(MagicMock(), "execute_python", {"code": "print(42)"})

    assert result == {"stdout": "42\n", "stderr": "", "exit_code": 0, "timed_out": False}
    mock_run.assert_called_once_with("print(42)", "postgresql://sandbox-url")


def test_unknown_tool_name_raises_value_error():
    dispatch = make_variant_b_dispatch_fn("postgresql://sandbox-url")

    with pytest.raises(ValueError, match="Unknown tool"):
        dispatch(MagicMock(), "not_execute_python", {})
