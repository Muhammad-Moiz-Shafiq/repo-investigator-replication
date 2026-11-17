import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from langfuse import Langfuse
from openai import OpenAI

from repo_investigator.agent.db import get_data_coverage_window
from repo_investigator.agent.schemas import AgentResult, AgentStep

# Raised from 10 after building Variant B: its execute_python tool has no
# server-side aggregation the way Variant A's curated tools do, so reaching
# the same depth of investigation takes far more turns (write query, run it,
# inspect, refine, repeat). A Variant B run was seen still making genuine
# forward progress -- self-correcting a real SQL bug, drilling toward the
# exact spike date -- when it hit the old cap at iteration 10. Raised
# uniformly for both variants, not just B, so the comparison holds "enough
# budget to actually finish" constant rather than "number of turns" constant.
MAX_ITERATIONS = 25

# Applied uniformly to every model, not just the one where it was found --
# see agent_methodology_log.md for how this was diagnosed: firing the exact
# same request 6 times against gemini-2.5-flash-lite produced 4 transient
# provider-side failures and 2 successes, with no code, prompt, or schema
# change between attempts. Retrying isolates each model's actual reasoning
# quality from upstream API instability that has nothing to do with it.
LLM_CALL_MAX_ATTEMPTS = 3
LLM_CALL_RETRY_DELAY_SECONDS = 1.5

# Prompts live in their own versioned files (not inline strings) so they're
# transparent and diffable on their own, and so evaluation results can record
# exactly which prompt version produced them -- see prompts/ for the change
# history of each (e.g. why v2 exists, what v1 got wrong). Every variant
# (curated tools, open sandbox) has its own prompt file and version string --
# passed in explicitly by the caller, never hardcoded here, so the loop
# itself has no idea which variant it's running.
_PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"


def _load_prompt_template(prompt_version: str) -> str:
    text = (_PROMPTS_DIR / f"system_prompt_{prompt_version}.md").read_text()
    # Strip the leading HTML comment (version/rationale metadata meant for
    # humans reading the file, not for the model).
    if text.startswith("<!--"):
        text = text.split("-->", 1)[1].lstrip()
    return text


def _build_system_prompt(conn: psycopg.Connection, prompt_version: str) -> str:
    window = get_data_coverage_window(conn)
    window_start, window_end = window if window else ("unknown", "unknown")
    return _load_prompt_template(prompt_version).format(
        today=datetime.now(UTC).date(), window_start=window_start, window_end=window_end
    )


def _call_llm_with_error_check(client: OpenAI, model: str, messages: list[dict], tool_schemas: list[dict]):
    """Wraps the raw chat.completions.create call to also catch the failure
    mode found during model selection testing: some providers (seen via
    OpenRouter) return HTTP 200 with the real error embedded in the JSON
    body instead of raising an HTTP error -- the SDK won't catch this on
    its own. Raises RuntimeError uniformly either way, so callers only need
    to handle one failure path.
    """
    response = client.chat.completions.create(model=model, messages=messages, tools=tool_schemas)
    error = getattr(response, "error", None)
    if error:
        raise RuntimeError(f"Upstream error in 200 response: {error}")
    if not response.choices:
        raise RuntimeError(f"Empty choices, no error field either: {response.model_dump_json()[:200]}")

    choice = response.choices[0]
    # A third failure shape, found via gemini-2.5-flash-lite: no top-level
    # `error`, a non-empty `choices` array, but finish_reason "error" (seen
    # with native_finish_reason "MALFORMED_FUNCTION_CALL" -- the model tried
    # to call a tool, its own function-calling formatter failed internally,
    # and the provider returns a fully empty message instead of a repairable
    # tool call). Without this check the loop reads "no tool_calls, no
    # content" as a normal converged-with-empty-answer turn.
    if getattr(choice, "finish_reason", None) == "error":
        raise RuntimeError(
            f"Provider returned finish_reason=error (native: "
            f"{getattr(choice, 'native_finish_reason', None)}): {response.model_dump_json()[:200]}"
        )
    # A fourth failure shape, found via gemini-2.5-flash-lite: finish_reason
    # is a normal-looking value (not "error"), but the message has neither
    # tool_calls nor content -- nothing genuinely converged, it's just
    # silent. Seen specifically on a later retry after repeated
    # MALFORMED_FUNCTION_CALL attempts, as if the provider gave up trying to
    # format a tool call and returned nothing instead. A real final answer
    # is never empty, so treat this as a failure to retry, not a valid
    # "no tool_calls -> converged" turn.
    if not choice.message.tool_calls and not choice.message.content:
        raise RuntimeError(
            f"Empty message: no tool_calls and no content (finish_reason="
            f"{getattr(choice, 'finish_reason', None)}): {response.model_dump_json()[:200]}"
        )
    return response


def _call_llm_with_retries(client: OpenAI, model: str, messages: list[dict], tool_schemas: list[dict]):
    """Retries transient provider-side failures (any of the shapes
    _call_llm_with_error_check catches) a bounded number of times before
    giving up -- see LLM_CALL_MAX_ATTEMPTS above for why. Only retries what
    _call_llm_with_error_check flags; a genuinely malformed request would
    fail identically on every attempt and still surface after the retries
    are exhausted.
    """
    last_error: Exception | None = None
    for attempt in range(LLM_CALL_MAX_ATTEMPTS):
        try:
            return _call_llm_with_error_check(client, model, messages, tool_schemas)
        except Exception as e:
            last_error = e
            if attempt < LLM_CALL_MAX_ATTEMPTS - 1:
                time.sleep(LLM_CALL_RETRY_DELAY_SECONDS)
    raise RuntimeError(
        f"Failed after {LLM_CALL_MAX_ATTEMPTS} attempts, last error: {last_error}"
    ) from last_error


def run_react_loop(
    conn: psycopg.Connection,
    llm_client: OpenAI,
    model: str,
    question: str,
    tool_schemas: list[dict],
    dispatch_fn: Callable[[psycopg.Connection, str, dict], dict],
    prompt_version: str,
    langfuse: Langfuse | None = None,
    system_prompt: str | None = None,
    tool_result_chars: int | None = 500,
) -> AgentResult:
    """Runs one investigative question to completion using whichever tool
    surface the caller passes in -- this is what makes the same loop usable
    for both Variant A (curated tools) and Variant B (open sandbox): the loop
    itself has no opinion on which one it's running, it just needs a tool
    schema list for the LLM and a dispatch function to execute whatever the
    LLM decides to call.

    The scaled study passes a fixed system_prompt (so the prompt text doesn't
    change with today's date) and tool_result_chars=None (so the run record
    keeps every tool result in full, for grading). The defaults keep the
    pilot's behavior.
    """
    messages = [
        {"role": "system", "content": system_prompt or _build_system_prompt(conn, prompt_version)},
        {"role": "user", "content": question},
    ]
    steps: list[AgentStep] = []

    agent_ctx = (
        langfuse.start_as_current_observation(
            name="react_loop",
            as_type="agent",
            input=question,
            metadata={"model": model, "prompt_version": prompt_version},
        )
        if langfuse
        else None
    )
    agent_span = agent_ctx.__enter__() if agent_ctx else None

    def trace_id():
        return langfuse.get_current_trace_id() if langfuse else None

    def clip(text: str) -> str:
        return text if tool_result_chars is None else text[:tool_result_chars]

    try:
        for turn in range(1, MAX_ITERATIONS + 1):
            gen_ctx = (
                langfuse.start_as_current_observation(
                    name="llm_call", as_type="generation", model=model, input=messages
                )
                if langfuse
                else None
            )
            gen_span = gen_ctx.__enter__() if gen_ctx else None
            try:
                response = _call_llm_with_retries(llm_client, model, messages, tool_schemas)
            except Exception as e:
                steps.append(AgentStep(step_type="error", content=f"LLM call failed: {e}", turn=turn))
                if gen_ctx:
                    gen_ctx.__exit__(None, None, None)
                result = AgentResult(
                    question=question,
                    model=model,
                    final_answer=None,
                    steps=steps,
                    converged=False,
                    langfuse_trace_id=trace_id(),
                    prompt_version=prompt_version,
                    stop_reason="provider_failure",
                    turns=turn,
                )
                return result

            message = response.choices[0].message
            if gen_span:
                usage = response.usage.model_dump() if getattr(response, "usage", None) else {}
                gen_span.update(
                    output=message.content or message.tool_calls,
                    usage_details={
                        k: usage[k]
                        for k in ("prompt_tokens", "completion_tokens")
                        if usage.get(k) is not None
                    }
                    or None,
                    cost_details={"total": usage["cost"]} if usage.get("cost") is not None else None,
                )
            if gen_ctx:
                gen_ctx.__exit__(None, None, None)

            if not message.tool_calls:
                steps.append(AgentStep(step_type="final_answer", content=message.content or "", turn=turn))
                if agent_span:
                    agent_span.update(output=message.content)
                return AgentResult(
                    question=question,
                    model=model,
                    final_answer=message.content,
                    steps=steps,
                    converged=True,
                    langfuse_trace_id=trace_id(),
                    prompt_version=prompt_version,
                    stop_reason="answered",
                    turns=turn,
                )

            if message.content:
                # What the model wrote alongside its tool calls: its reasoning for this turn.
                steps.append(AgentStep(step_type="reasoning", content=message.content, turn=turn))

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            for tool_call in message.tool_calls:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    tool_result = {"error": f"Model produced invalid JSON arguments: {e}"}
                    arguments = {}
                else:
                    tool_ctx = (
                        langfuse.start_as_current_observation(
                            name=tool_call.function.name, as_type="tool", input=arguments
                        )
                        if langfuse
                        else None
                    )
                    tool_span = tool_ctx.__enter__() if tool_ctx else None
                    try:
                        tool_result = dispatch_fn(conn, tool_call.function.name, arguments)
                    except Exception as e:
                        tool_result = {"error": f"Tool execution failed: {e}"}
                    if tool_span:
                        tool_span.update(output=tool_result)
                    if tool_ctx:
                        tool_ctx.__exit__(None, None, None)

                steps.append(
                    AgentStep(
                        step_type="tool_call",
                        content=f"Called {tool_call.function.name}",
                        tool_name=tool_call.function.name,
                        tool_arguments=arguments,
                        turn=turn,
                    )
                )
                steps.append(
                    AgentStep(
                        step_type="tool_result",
                        content=clip(json.dumps(tool_result, default=str)),
                        tool_name=tool_call.function.name,
                        turn=turn,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result, default=str),
                    }
                )

        # Exceeded MAX_ITERATIONS without producing a final answer.
        steps.append(
            AgentStep(step_type="error", content=f"Exceeded {MAX_ITERATIONS} iterations without converging")
        )
        if agent_span:
            agent_span.update(output=None, level="WARNING", status_message="max iterations exceeded")
        return AgentResult(
            question=question,
            model=model,
            final_answer=None,
            steps=steps,
            converged=False,
            langfuse_trace_id=trace_id(),
            prompt_version=prompt_version,
            stop_reason="budget",
            turns=MAX_ITERATIONS,
        )
    finally:
        if agent_ctx:
            agent_ctx.__exit__(None, None, None)
        if langfuse:
            langfuse.flush()
