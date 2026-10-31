"""Typed data models for the agent-execution lifecycle."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Task(BaseModel):
    """A unit of work dispatched through the execution lifecycle."""

    id: str = Field(..., description="Stable identifier, used to name the worktree and branch.")
    prompt: str = Field(..., description="Natural-language instruction for the crew.")
    repo: str = Field(..., description="Target repository (path or URL).")
    base_ref: str = Field("main", description="Branch or ref the worktree is cut from.")


class Worktree(BaseModel):
    """An isolated workspace provisioned for a task."""

    task_id: str
    path: str = Field(..., description="Filesystem path to the worktree root.")
    branch: str = Field(..., description="Branch checked out in the worktree.")
    lease_id: str | None = Field(
        default=None,
        description="treehouse per-acquisition lease id; guards release against "
        "releasing a lease a newer run of the same task now owns.",
    )


class TokenUsage(BaseModel):
    """Token counts of one or more model calls.

    The field names are the Messages API's, and the shape is the ``usage``
    object of the stack's diagnostic events (cloud-catcher ADR-0006), so run
    records roll up into diagnostics without translation.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
        )


class AgentUsage(BaseModel):
    """What one headless agent invocation reported about itself.

    Parsed from the ``result`` object that ``claude -p --output-format json``
    prints (see :mod:`automate.claude_output`). ``cost_usd`` is Claude Code's
    client-side estimate and ``cost_source`` says so, so rollups never mix it
    with other accounting. ``session_id_inherited`` flags a child that reported
    the orchestrating session's own id (observed inside Claude Code cloud
    sessions); such an id cannot serve as a join key, the task id must.
    """

    session_id: str | None = None
    session_id_inherited: bool = False
    usage: TokenUsage = Field(default_factory=TokenUsage)
    usage_by_model: dict[str, TokenUsage] = Field(default_factory=dict)
    cost_usd: float | None = None
    cost_source: Literal["claude-code-estimate"] | None = None
    duration_ms: int | None = None
    api_duration_ms: int | None = None
    num_turns: int | None = None
    subagents_spawned: int | None = None
    permission_denials: int | None = None
    subtype: str | None = Field(
        default=None,
        description="Claude Code result subtype: success, error_max_turns, "
        "error_max_budget_usd, error_during_execution, ...",
    )
    cap_hit: Literal["turns", "budget"] | None = Field(
        default=None, description="Set when the subtype says a turn or dollar cap ended the run."
    )


class CrewResult(BaseModel):
    """Outcome of running an agent crew against a worktree."""

    task_id: str
    branch: str
    changed: bool = Field(..., description="Whether the crew produced committed changes.")
    summary: str = Field("", description="Human-readable summary of what the crew did.")
    usage: AgentUsage | None = Field(
        default=None,
        description="Usage and cost the crew's agent reported; None when the backend "
        "reports nothing (dry-run, firstmate, a non-claude agent).",
    )


class Verdict(BaseModel):
    """Outcome of a single governance or evaluation gate."""

    gate: str = Field(..., description="Name of the gate that produced this verdict.")
    passed: bool
    findings: list[str] = Field(default_factory=list)
    usage: AgentUsage | None = Field(
        default=None, description="Usage the gate's agent reported through the gate's USAGE line."
    )


class GateResult(BaseModel):
    """Outcome of the safe-push (ship) gate."""

    task_id: str
    pushed: bool
    pr_url: str | None = None
    findings: list[str] = Field(default_factory=list)


class RunStatus(StrEnum):
    """Terminal status of a lifecycle run."""

    SHIPPED = "shipped"
    GATED = "gated"
    NO_CHANGES = "no_changes"
    FAILED = "failed"


def sum_usage(reports: list[AgentUsage | None]) -> tuple[TokenUsage | None, float | None]:
    """Total tokens and reported cost over the usage reports that exist."""
    present = [report for report in reports if report is not None]
    if not present:
        return None, None
    total = TokenUsage()
    for report in present:
        total = total + report.usage
    costs = [report.cost_usd for report in present if report.cost_usd is not None]
    return total, (round(sum(costs), 6) if costs else None)


class RunRecord(BaseModel):
    """Structured record of a single execution lifecycle run."""

    task: Task
    status: RunStatus
    worktree: Worktree | None = None
    crew: CrewResult | None = None
    verdicts: list[Verdict] = Field(default_factory=list)
    gate: GateResult | None = None
    log: list[str] = Field(default_factory=list)
    total_usage: TokenUsage | None = Field(
        default=None, description="Crew plus gate tokens; set by summarize_usage()."
    )
    total_cost_usd: float | None = Field(
        default=None,
        description="Sum of reported costs (Claude Code estimates); set by summarize_usage().",
    )

    @property
    def shipped(self) -> bool:
        """True when the run completed and shipped through the safe-push gate."""
        return self.status is RunStatus.SHIPPED

    def summarize_usage(self) -> None:
        """Fold the crew's and the gates' usage into the totals."""
        crew_usage = self.crew.usage if self.crew is not None else None
        self.total_usage, self.total_cost_usd = sum_usage(
            [crew_usage, *(verdict.usage for verdict in self.verdicts)]
        )


class PullRequest(BaseModel):
    """Metadata for one GitHub pull request (parsed from ``gh --json`` output)."""

    model_config = ConfigDict(populate_by_name=True)

    number: int
    title: str
    body: str = ""
    base_ref: str = Field(validation_alias="baseRefName", description="Branch the PR targets.")
    head_ref: str = Field(default="", validation_alias="headRefName")
    head_sha: str = Field(default="", validation_alias="headRefOid")
    url: str = ""
    draft: bool = Field(default=False, validation_alias="isDraft")
    additions: int = 0
    deletions: int = 0

    @property
    def intent(self) -> str:
        """Title plus body - the contract reviews judge the diff against."""
        body = self.body.strip()
        if len(body) > 4000:
            body = body[:4000] + "\n[...body truncated]"
        return f"{self.title}\n\n{body}".strip()


class ReviewStatus(StrEnum):
    """Terminal status of a PR review."""

    REVIEWED = "reviewed"
    POSTED = "posted"
    FAILED = "failed"


class ReviewRecord(BaseModel):
    """Structured record of one PR review (the review lifecycle's RunRecord).

    Gate failures are review *content* (they appear in ``verdicts`` and the
    report), not review failures; ``FAILED`` is reserved for crashes.
    """

    pr: PullRequest
    status: ReviewStatus
    verdicts: list[Verdict] = Field(default_factory=list)
    review: str = Field(default="", description="The deep-review agent's markdown body.")
    report_path: str | None = None
    posted: bool = False
    comment_url: str | None = None
    log: list[str] = Field(default_factory=list)
    total_usage: TokenUsage | None = Field(
        default=None, description="Gate tokens; set by summarize_usage()."
    )
    total_cost_usd: float | None = Field(
        default=None, description="Sum of reported gate costs; set by summarize_usage()."
    )

    def summarize_usage(self) -> None:
        """Fold the gates' usage into the totals."""
        self.total_usage, self.total_cost_usd = sum_usage(
            [verdict.usage for verdict in self.verdicts]
        )
