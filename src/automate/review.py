"""The PR-review lifecycle: fetch -> gate verdicts -> deep review -> report -> post.

A parallel lifecycle next to :mod:`automate.orchestrator`. It reuses the same
ports where they fit (worktrees, gates) and adds two of its own (the PR host and
the reviewer). Gates judge the PR's diff against the PR's *own* base branch -
stacked PRs target a branch other than main - while the deep reviewer explores a
real checkout of the PR head, so review depth is not bound by the gates'
embedded-diff cap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from automate.adapters import AgentReviewAdapter, GhAdapter, TreehouseAdapter
from automate.config import Settings
from automate.harnesses import harness_gates
from automate.models import (
    CrewResult,
    PullRequest,
    ReviewRecord,
    ReviewStatus,
    Task,
    Verdict,
    Worktree,
)
from automate.ports import Gate, PullRequestHost, Reviewer, WorktreeProvider


class ReviewOrchestrator:
    """Reviews pull requests and records each outcome.

    Mirrors :class:`Orchestrator`'s record-not-raise discipline: ``review_pr``
    never throws; crashes surface as a FAILED record. Gate failures are review
    *content*, not review failures.
    """

    def __init__(
        self,
        *,
        host: PullRequestHost,
        treehouse: WorktreeProvider,
        reviewer: Reviewer,
        gates: list[Gate],
        reports_dir: str,
    ) -> None:
        self._host = host
        self._treehouse = treehouse
        self._reviewer = reviewer
        self._gates = gates
        self._reports_dir = Path(reports_dir).expanduser()

    @classmethod
    def from_settings(cls, settings: Settings) -> ReviewOrchestrator:
        """Build a review orchestrator with the bundled adapters wired from config."""
        dry = settings.dry_run
        return cls(
            host=GhAdapter(
                settings.gh_bin,
                clone_root=settings.review_clone_root,
                dry_run=dry,
                timeout=settings.review_timeout_s,
            ),
            treehouse=TreehouseAdapter(settings.treehouse_bin, dry_run=dry),
            reviewer=AgentReviewAdapter(
                agent_cmd=settings.review_agent_cmd,
                dry_run=dry,
                timeout=settings.review_timeout_s,
            ),
            gates=list(harness_gates(settings)),
            reports_dir=str(Path(settings.workspace_root).expanduser() / "reviews"),
        )

    def review_pr(self, repo: str, number: int, *, post: bool = False) -> ReviewRecord:
        """Review one PR end to end, returning a structured record."""
        placeholder = PullRequest(number=number, title="(metadata unavailable)", base_ref="main")
        record = ReviewRecord(pr=placeholder, status=ReviewStatus.FAILED)
        try:
            self._execute(repo, number, post, record)
        except Exception as exc:  # boundary: surface failures in the record
            record.status = ReviewStatus.FAILED
            record.log.append(f"review failed: {exc}")
        return record

    def review_open(self, repo: str, *, post: bool = False) -> list[ReviewRecord]:
        """Review every open PR of ``repo`` sequentially.

        The clone/list phase honors the same record-not-raise boundary as
        ``review_pr``: an unreachable host yields one FAILED record instead of
        an uncaught traceback.
        """
        try:
            clone = self._host.ensure_clone(repo)
            prs = self._host.list_open(clone)
        except Exception as exc:  # boundary: surface failures in a record
            placeholder = PullRequest(number=0, title="(open PRs unavailable)", base_ref="main")
            record = ReviewRecord(pr=placeholder, status=ReviewStatus.FAILED)
            record.log.append(f"listing open PRs failed: {exc}")
            return [record]
        # Pass the resolved clone path so each review skips re-resolution.
        return [self.review_pr(clone, pr.number, post=post) for pr in prs]

    def _execute(self, repo: str, number: int, post: bool, record: ReviewRecord) -> None:
        clone = self._host.ensure_clone(repo)
        record.log.append(f"clone at {clone}")

        pr = self._host.view(clone, number)
        record.pr = pr
        head_ref = self._host.fetch_pr(clone, pr)
        record.log.append(f"fetched PR #{pr.number} ({pr.head_ref} -> {pr.base_ref}) as {head_ref}")

        # Synthesized lifecycle objects let CommandGate.evaluate run unchanged:
        # gates diff head_ref against the PR's own base inside the clone.
        task = Task(
            id=f"pr-{pr.number}",
            prompt=pr.intent,
            repo=clone,
            base_ref=f"origin/{pr.base_ref}",
        )
        crew = CrewResult(
            task_id=task.id, branch=head_ref, changed=True, summary=f"PR #{pr.number} head"
        )
        record.verdicts = [gate.evaluate(task, crew) for gate in self._gates]
        for verdict in record.verdicts:
            record.log.append(self._format_verdict(verdict))

        worktree = self._treehouse.create(task)
        try:
            self._host.checkout(worktree, head_ref)
            record.review = self._reviewer.review(task, worktree)
            record.log.append(f"deep review completed in {worktree.path}")
        finally:
            # A review checkout holds no unique state (the PR head lives in the
            # clone's refs), so release on every outcome - nothing to autopsy.
            self._release(worktree, record)

        report = self._compose(pr, record)
        record.report_path = self._save(clone, pr, report)
        record.log.append(f"report saved to {record.report_path}")

        if post:
            record.comment_url = self._host.comment(clone, pr.number, report)
            record.posted = True
            record.status = ReviewStatus.POSTED
            record.log.append(f"posted to PR #{pr.number}: {record.comment_url}")
        else:
            record.status = ReviewStatus.REVIEWED

    def _release(self, worktree: Worktree, record: ReviewRecord) -> None:
        try:
            self._treehouse.release(worktree)
        except Exception as exc:  # boundary: release must not mask the outcome
            record.log.append(f"worktree release failed (lease left open): {exc}")

    def _compose(self, pr: PullRequest, record: ReviewRecord) -> str:
        """Assemble the posted/saved report: header, gate verdicts, review body."""
        draft = " (draft)" if pr.draft else ""
        lines = [
            f"## auto-mate review - PR #{pr.number}: {pr.title}{draft}",
            "",
            f"- branch: `{pr.head_ref}` -> `{pr.base_ref}`  (+{pr.additions}/-{pr.deletions})",
        ]
        if pr.url:
            lines.append(f"- url: {pr.url}")
        lines += ["", "### Gate verdicts", ""]
        for verdict in record.verdicts:
            state = "PASS" if verdict.passed else "FAIL"
            lines.append(f"- **{verdict.gate}**: {state}")
            lines.extend(f"  - {finding}" for finding in verdict.findings)
        lines += ["", "### Review", "", record.review, ""]
        return "\n".join(lines)

    def _save(self, clone: str, pr: PullRequest, report: str) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        path = self._reports_dir / f"{Path(clone).name}-pr-{pr.number}-{stamp}.md"
        path.write_text(report, encoding="utf-8")
        return str(path)

    @staticmethod
    def _format_verdict(verdict: Verdict) -> str:
        state = "passed" if verdict.passed else "failed"
        suffix = f" ({'; '.join(verdict.findings)})" if verdict.findings else ""
        return f"gate {verdict.gate} {state}{suffix}"
