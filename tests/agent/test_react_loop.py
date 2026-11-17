import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from repo_investigator.agent.react_loop import LLM_CALL_MAX_ATTEMPTS, MAX_ITERATIONS, run_react_loop


def _fake_message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _fake_response(content=None, tool_calls=None, error=None, choices_present=True, finish_reason="stop"):
    response = SimpleNamespace(
        choices=(
            [SimpleNamespace(message=_fake_message(content, tool_calls), finish_reason=finish_reason)]
            if choices_present
            else []
        ),
        error=error,
    )
    response.model_dump_json = lambda: json.dumps({"error": error})
    return response


def _fake_tool_call(name="query_ci_history", arguments='{"repo": "x/y"}', call_id="call_1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def _make_client(responses):
    """responses: list of fake response objects returned in order, one per LLM call."""
    client = MagicMock()
    client.chat.completions.create.side_effect = responses
    return client


def _run(client, dispatch_fn=None):
    """These tests only care about the loop's control flow, not which
    variant's tools/prompt it's running with -- pass through empty/mocked
    values for the parts that don't matter to a given test.
    """
    return run_react_loop(
        conn=MagicMock(),
        llm_client=client,
        model="test-model",
        question="q",
        tool_schemas=[],
        dispatch_fn=dispatch_fn or MagicMock(),
        prompt_version="v2_grounded",
    )


def test_stops_immediately_when_first_response_has_no_tool_calls():
    client = _make_client([_fake_response(content="Final answer, no tools needed.")])
    result = _run(client)

    assert result.converged is True
    assert result.final_answer == "Final answer, no tools needed."
    assert client.chat.completions.create.call_count == 1


def test_executes_tool_call_then_converges_on_second_response():
    mock_dispatch = MagicMock(return_value={"total_runs": 10, "failed_runs": 1})
    responses = [
        _fake_response(tool_calls=[_fake_tool_call()]),
        _fake_response(content="Based on the tool result, here is the answer."),
    ]
    client = _make_client(responses)

    result = _run(client, dispatch_fn=mock_dispatch)

    assert result.converged is True
    assert result.final_answer == "Based on the tool result, here is the answer."
    assert client.chat.completions.create.call_count == 2
    mock_dispatch.assert_called_once()
    tool_call_steps = [s for s in result.steps if s.step_type == "tool_call"]
    assert len(tool_call_steps) == 1
    assert tool_call_steps[0].tool_name == "query_ci_history"


def test_stops_after_max_iterations_if_model_never_converges():
    mock_dispatch = MagicMock(return_value={"ok": True})
    # Always returns a tool call, never a final answer -- the loop must not run forever.
    client = _make_client([_fake_response(tool_calls=[_fake_tool_call()]) for _ in range(MAX_ITERATIONS)])

    result = _run(client, dispatch_fn=mock_dispatch)

    assert result.converged is False
    assert result.final_answer is None
    assert client.chat.completions.create.call_count == MAX_ITERATIONS


@patch("repo_investigator.agent.react_loop.time.sleep")
def test_handles_upstream_error_embedded_in_200_response_without_crashing(mock_sleep):
    # The real failure mode found during model smoke-testing: HTTP 200 with
    # the actual error inside the JSON body instead of an HTTP error status.
    # A persistent (not transient) error should exhaust retries, not hang.
    error_response = _fake_response(error={"message": "Service temporarily overloaded", "code": 503})
    client = _make_client([error_response] * LLM_CALL_MAX_ATTEMPTS)

    result = _run(client)

    assert result.converged is False
    assert result.final_answer is None
    assert any(s.step_type == "error" for s in result.steps)
    assert client.chat.completions.create.call_count == LLM_CALL_MAX_ATTEMPTS  # retries, then stops


def test_handles_finish_reason_error_without_treating_it_as_a_real_answer():
    # Found running gemini-2.5-flash-lite: no top-level `error`, non-empty
    # `choices`, but finish_reason "error" (native_finish_reason
    # MALFORMED_FUNCTION_CALL) and a fully empty message. Must not be read
    # as "no tool_calls -> converged with an empty final answer."
    client = _make_client([_fake_response(content=None, tool_calls=None, finish_reason="error")])

    result = _run(client)

    assert result.converged is False
    assert result.final_answer is None
    assert any(s.step_type == "error" for s in result.steps)


def test_handles_empty_message_with_normal_finish_reason_without_treating_it_as_real():
    # Found running gemini-2.5-flash-lite in a real evaluation run: finish_reason
    # "stop" (not "error"), no tool_calls, no content -- silently empty rather
    # than a real converged answer. Seen after repeated MALFORMED_FUNCTION_CALL
    # attempts, as if the provider gave up formatting a tool call and returned
    # nothing at all instead of a fourth attempt.
    client = _make_client([_fake_response(content=None, tool_calls=None, finish_reason="stop")])

    result = _run(client)

    assert result.converged is False
    assert result.final_answer is None
    assert any(s.step_type == "error" for s in result.steps)


@patch("repo_investigator.agent.react_loop.time.sleep")
def test_retries_transient_failure_then_succeeds(mock_sleep):
    responses = [
        _fake_response(content=None, tool_calls=None, finish_reason="error"),
        _fake_response(content="Answer after one retry."),
    ]
    client = _make_client(responses)

    result = _run(client)

    assert result.converged is True
    assert result.final_answer == "Answer after one retry."
    assert client.chat.completions.create.call_count == 2
    mock_sleep.assert_called_once()
    # The transient failure was recovered from -- no error step should leak through.
    assert not any(s.step_type == "error" for s in result.steps)


@patch("repo_investigator.agent.react_loop.time.sleep")
def test_gives_up_after_exhausting_retries_on_persistent_failure(mock_sleep):
    responses = [
        _fake_response(content=None, tool_calls=None, finish_reason="error")
        for _ in range(LLM_CALL_MAX_ATTEMPTS)
    ]
    client = _make_client(responses)

    result = _run(client)

    assert result.converged is False
    assert result.final_answer is None
    assert client.chat.completions.create.call_count == LLM_CALL_MAX_ATTEMPTS
    assert any(s.step_type == "error" for s in result.steps)


def test_handles_malformed_tool_call_arguments_without_crashing():
    responses = [
        _fake_response(tool_calls=[_fake_tool_call(arguments="not valid json {{{")]),
        _fake_response(content="Recovered and answered anyway."),
    ]
    client = _make_client(responses)

    result = _run(client)

    assert result.converged is True
    assert result.final_answer == "Recovered and answered anyway."
