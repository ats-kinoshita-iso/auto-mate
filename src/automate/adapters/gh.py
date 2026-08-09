"""Adapter over the ``gh`` CLI: PR metadata, refs, and comments.

Implements the ``PullRequestHost`` port. Every ``gh`` invocation runs with the
local clone as working directory so the repository is inferred from ``origin``
(private repos work through the user's authenticated gh). PR heads are fetched
into a dedicated ``refs/automate/pr/<N>`` namespace that is never checked out,
so forced updates cannot collide with worktree branches.

Posting uses ``gh pr comment`` rather than ``gh pr review``: GitHub rejects
formal review events on self-authored PRs, while issue-style comments are always
allowed (drafts included) - and a comment is the honest shape for an automated
report.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from automate.adapters.base import CommandRunner
from automate.models import PullRequest, Worktree

_PR_FIELDS = "number,title,body,baseRefName,headRefName,headRefOid,isDraft,url,additions,deletions"
_COMMENT_MAX = 60_000  # GitHub's hard cap is 65,536; leave headroom for the marker.
_PR_LIST = TypeAdapter(list[PullRequest])


class GhAdapter:
    """Drive GitHub PR metadata, ref fetching, and commenting via gh."""

    def __init__(
        self,
        gh_bin: str = "gh",
        *,
        clone_root: str,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
        timeout: float | None = None,
    ) -> None:
        self._gh = gh_bin
        self._clone_root = Path(clone_root).expanduser()
        self._runner = runner or CommandRunner(dry_run=dry_run)
        self._timeout = timeout

    def ensure_clone(self, repo: str) -> str:
        """Resolve ``repo`` (local path or owner/name slug) to a local clone.

        Slug clones are keyed by the FULL slug (``<root>/<owner>/<name>``) so
        same-named repos of different owners never collide into one directory -
        a collision would silently review (and post to) the wrong repository.
        """
        if Path(repo).expanduser().is_dir():
            return str(Path(repo).expanduser())
        if "/" not in repo:
            raise ValueError(f"repo must be a local path or an owner/name slug, got {repo!r}")
        target = self._clone_root.joinpath(*repo.split("/"))
        if not target.is_dir() or self._runner.dry_run:
            self._runner.run([self._gh, "repo", "clone", repo, str(target)], timeout=self._timeout)
        return str(target)

    def list_open(self, clone: str) -> list[PullRequest]:
        """All open PRs (drafts included) of the clone's origin repo."""
        result = self._runner.run(
            [self._gh, "pr", "list", "--state", "open", "--json", _PR_FIELDS],
            cwd=clone,
            timeout=self._timeout,
        )
        if self._runner.dry_run:
            return [self._synthetic(1)]
        return _PR_LIST.validate_json(result.stdout)

    def view(self, clone: str, number: int) -> PullRequest:
        """Metadata for one PR."""
        result = self._runner.run(
            [self._gh, "pr", "view", str(number), "--json", _PR_FIELDS],
            cwd=clone,
            timeout=self._timeout,
        )
        if self._runner.dry_run:
            return self._synthetic(number)
        return PullRequest.model_validate_json(result.stdout)

    def fetch_pr(self, clone: str, pr: PullRequest) -> str:
        """Fetch the PR head into ``refs/automate/pr/<N>``; return that ref.

        The PR's base branch is fetched in the same call: an explicit refspec
        suppresses git's opportunistic remote-tracking updates, so without it
        ``origin/<base>`` would stay frozen at clone time (or be absent for a
        base created later) and the gates would diff against a stale base.
        """
        ref = f"refs/automate/pr/{pr.number}"
        self._runner.run(
            [
                "git",
                "-C",
                clone,
                "fetch",
                "origin",
                f"+refs/pull/{pr.number}/head:{ref}",
                f"+refs/heads/{pr.base_ref}:refs/remotes/origin/{pr.base_ref}",
            ],
            timeout=self._timeout,
        )
        return ref

    def checkout(self, worktree: Worktree, ref: str) -> None:
        """Move the worktree's task branch onto the PR head."""
        self._runner.run(["git", "-C", worktree.path, "reset", "--hard", ref])

    def comment(self, clone: str, number: int, body: str) -> str:
        """Post ``body`` as a PR comment; return the comment URL."""
        if len(body) > _COMMENT_MAX:
            body = body[:_COMMENT_MAX] + "\n\n*[review truncated to fit the comment limit]*"
        result = self._runner.run(
            [self._gh, "pr", "comment", str(number), "--body", body],
            cwd=clone,
            timeout=self._timeout,
        )
        if self._runner.dry_run:
            return f"https://example.invalid/pr/{number}#comment-dry-run"
        return result.stdout.strip()

    @staticmethod
    def _synthetic(number: int) -> PullRequest:
        """A stand-in PR so dry-run walks the whole review lifecycle."""
        return PullRequest(
            number=number,
            title=f"[dry-run] PR #{number}",
            base_ref="main",
            head_ref=f"dry-run/pr-{number}",
        )
