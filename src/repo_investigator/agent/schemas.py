from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class DateRange(BaseModel):
    start: date
    end: date


# --- query_ci_history ---


class WorkflowCIStats(BaseModel):
    workflow_name: str
    total_runs: int
    failed_runs: int
    failure_rate: float


class DailyCIStats(BaseModel):
    date: date
    total_runs: int
    failed_runs: int
    failure_rate: float


class CIHistoryResult(BaseModel):
    repo: str
    date_from: date
    date_to: date
    total_runs: int
    failed_runs: int
    overall_failure_rate: float | None  # None if total_runs is 0 -- no division by zero
    by_workflow: list[WorkflowCIStats]
    by_day: list[DailyCIStats]


# --- fetch_commit_diff ---


class FileDiff(BaseModel):
    filename: str
    status: str
    additions: int
    deletions: int
    patch: str | None  # None: GitHub omits patch text for very large diffs (~0.5% of files)


class CommitDiff(BaseModel):
    repo: str
    sha: str
    found: bool  # False if the sha doesn't exist in our ingested data -- distinct from "found, but no files"
    message: str | None = None
    author_login: str | None = None
    committed_at: datetime | None = None
    is_bugfix: bool | None = None
    files: list[FileDiff] = []


# --- query_issues_prs ---


class IssuePRFilters(BaseModel):
    kind: Literal["issues", "pull_requests", "both"] = "both"
    state: str | None = None  # e.g. "OPEN", "CLOSED", "MERGED" -- matches the raw GitHub state value
    is_bug: bool | None = None  # issues only, ignored for pull_requests


class IssueSummary(BaseModel):
    number: int
    title: str
    state: str
    author_login: str | None
    created_at: datetime
    closed_at: datetime | None
    labels: list[str]
    is_bug: bool
    comment_count: int


class PRSummary(BaseModel):
    number: int
    title: str
    state: str
    author_login: str | None
    created_at: datetime
    merged_at: datetime | None
    review_comment_count: int
    approval_count: int
    time_to_merge_seconds: int | None


class IssuePRResult(BaseModel):
    repo: str
    date_from: date
    date_to: date
    issues: list[IssueSummary]
    pull_requests: list[PRSummary]


# --- query_review_approval_stats ---
# Added 2026-09-25 after finding no existing tool could answer "what
# fraction of merged PRs got approved" directly -- query_issues_prs only
# returns a raw per-PR list, forcing the model to aggregate approval_count
# itself, which it mostly got wrong (see agent_methodology_log.md). This
# fills that specific, evidenced gap; it doesn't replace query_issues_prs.


class PRApprovalStats(BaseModel):
    repo: str
    date_from: date
    date_to: date
    total_merged_prs: int
    prs_with_approval: int
    prs_without_approval: int
    approval_rate: float | None  # None if total_merged_prs is 0 -- no division by zero


# --- compare_periods ---

SUPPORTED_METRICS = Literal[
    "ci_failure_rate",
    "avg_hours_to_first_review",
    "avg_hours_to_merge",
    "commit_count",
    "pr_count",
    "issue_count",
]


class ComparisonResult(BaseModel):
    repo: str
    metric: SUPPORTED_METRICS
    period_a: DateRange
    period_a_value: float | None  # None if no data exists in that period for this metric
    period_b: DateRange
    period_b_value: float | None
    absolute_change: float | None
    percent_change: float | None  # None if period_a_value is 0 or None -- no division by zero


# --- query_contributor_associations ---


class ContributorAssociation(BaseModel):
    author_login: str
    commit_count: int
    implicated_commit_count: int
    association_rate: float


# --- ReAct loop ---


class AgentStep(BaseModel):
    step_type: Literal["reasoning", "tool_call", "tool_result", "final_answer", "error"]
    content: str  # human-readable summary, always populated
    tool_name: str | None = None
    tool_arguments: dict | None = None
    turn: int | None = None  # which model turn this step belongs to, from 1


class AgentResult(BaseModel):
    question: str
    model: str
    final_answer: str | None  # None if the loop never converged
    steps: list[AgentStep]
    converged: bool  # False if max_iterations was hit without a final answer
    langfuse_trace_id: str | None = None
    prompt_version: str | None = None  # e.g. "v2_grounded" -- see prompts/ for what changed and why
    # Added for the scaled study. answered: the model gave a final answer.
    # budget: it used all MAX_ITERATIONS turns. provider_failure: an LLM call
    # still failed after the retries (an infrastructure problem, not model behavior).
    stop_reason: Literal["answered", "budget", "provider_failure"] | None = None
    turns: int = 0


class ContributorAssociationResult(BaseModel):
    repo: str
    # The underlying metric is computed once over the whole ingested window,
    # not an arbitrary sub-range (see agent_methodology_log.md) -- these
    # reflect what was ACTUALLY computed, which may not match a narrower
    # date_from/date_to the caller passed in. Never silently pretend a
    # narrower window was honored when it wasn't.
    computed_window_start: date
    computed_window_end: date
    contributors: list[ContributorAssociation]
