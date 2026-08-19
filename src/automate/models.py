"""Typed data models for the agent-execution lifecycle."""

from __future__ import annotations

from enum import StrEnum

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
        None,
        description="treehouse per-acquisition lease id; guards release against "
        "releasing a lease a newer run of the same task now owns.",
    )


class CrewResult(BaseModel):
    """Outcome of running an agent crew against a worktree."""

    task_id: str
    branch: str
    changed: bool = Field(..., description="Whether the crew produced committed changes.")
    summary: str = Field("", description="Human-readable summary of what the crew did.")


class Verdict(BaseModel):
    """Outcome of a single governance or evaluation gate."""

    gate: str = Field(..., description="Name of the gate that produced this verdict.")
    passed: bool
    findings: list[str] = Field(default_factory=list)


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


class RunRecord(BaseModel):
    """Structured record of a single execution lifecycle run."""

    task: Task
    status: RunStatus
    worktree: Worktree | None = None
    crew: CrewResult | None = None
    verdicts: list[Verdict] = Field(default_factory=list)
    gate: GateResult | None = None
    log: list[str] = Field(default_factory=list)

    @property
    def shipped(self) -> bool:
        """True when the run completed and shipped through the safe-push gate."""
        return self.status is RunStatus.SHIPPED


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
