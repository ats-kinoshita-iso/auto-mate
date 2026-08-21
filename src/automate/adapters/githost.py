"""A plain-git ``PullRequestHost`` for environments without the ``gh`` CLI.

Claude Code cloud containers (and locked-down CI) have git - routed through an
authenticated proxy - but no ``gh`` and no direct GitHub API access. This host
covers the review lifecycle's git-shaped needs with git alone:

- clones come from ``https://github.com/<owner>/<name>`` (the proxy injects
  credentials for in-scope repos);
- PR heads are fetched from GitHub's public ``refs/pull/<N>/head`` namespace
  into the same never-checked-out ``refs/automate/pr/<N>`` namespace GhAdapter
  uses, along with the PR's base branch (same explicit-refspec rationale);
- PR *metadata* is not reachable over the git protocol, so it comes from
  configuration: ``AUTOMATE_REVIEW_BASE_REF`` names the base branch and
  ``AUTOMATE_REVIEW_INTENT`` optionally carries the PR's title/description for
  the gates to judge against.

Two operations need the GitHub API and are deliberately unsupported, failing
loudly instead of degrading: ``list_open`` (use ``--pr N``) and ``comment``
(``--post``). In the documented cloud pattern the orchestrating session posts
the saved report itself through its own GitHub access.
"""

from __future__ import annotations

from pathlib import Path

from automate.adapters.base import AdapterError, CommandRunner
from automate.models import PullRequest, Worktree


class GitHost:
    """PR refs and checkouts via plain git; metadata from configuration."""

    def __init__(
        self,
        *,
        clone_root: str,
        base_ref: str = "main",
        intent: str = "",
        dry_run: bool = True,
        runner: CommandRunner | None = None,
        timeout: float | None = None,
    ) -> None:
        self._clone_root = Path(clone_root).expanduser()
        self._base_ref = base_ref
        self._intent = intent
        self._runner = runner or CommandRunner(dry_run=dry_run)
        self._timeout = timeout

    def ensure_clone(self, repo: str) -> str:
        """Resolve ``repo`` (local path or owner/name slug) to a local clone.

        Mirrors GhAdapter: slug clones are keyed by the FULL slug so same-named
        repos of different owners never collide into one directory.
        """
        if Path(repo).expanduser().is_dir():
            return str(Path(repo).expanduser())
        if "/" not in repo:
            raise ValueError(f"repo must be a local path or an owner/name slug, got {repo!r}")
        target = self._clone_root.joinpath(*repo.split("/"))
        if not target.is_dir() or self._runner.dry_run:
            url = f"https://github.com/{repo}.git"
            self._runner.run(["git", "clone", url, str(target)], timeout=self._timeout)
        return str(target)

    def list_open(self, clone: str) -> list[PullRequest]:
        raise AdapterError(
            "listing open PRs needs the GitHub API - use the gh host "
            "(AUTOMATE_REVIEW_HOST=gh) or review a single PR with --pr N"
        )

    def view(self, clone: str, number: int) -> PullRequest:
        """Metadata from configuration - the git protocol carries none.

        The title/body come from ``AUTOMATE_REVIEW_INTENT`` when set, so the
        gates judge the diff against the real PR contract; otherwise a neutral
        placeholder keeps the lifecycle honest about what it knows.
        """
        title, _, body = self._intent.partition("\n")
        return PullRequest(
            number=number,
            title=title.strip() or f"PR #{number} (metadata via git host)",
            body=body.strip(),
            base_ref=self._base_ref,
            # Deliberately the ref path, not a branch name: the git protocol
            # doesn't expose the head's human branch name, and the ref path is
            # the truthful head identity this host knows (reports show it as-is).
            head_ref=f"refs/pull/{number}/head",
        )

    def fetch_pr(self, clone: str, pr: PullRequest) -> str:
        """Fetch the PR head + its base into the automate ref namespace.

        Same refspecs as GhAdapter: ``refs/pull/<N>/head`` is GitHub's public
        read-only PR namespace, and the explicit base refspec keeps the gates'
        diff base fresh (see gh.py for the stale-base rationale).
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
        """Reset the review worktree to the fetched PR head."""
        self._runner.run(["git", "-C", worktree.path, "reset", "--hard", ref])

    def comment(self, clone: str, number: int, body: str) -> str:
        raise AdapterError(
            "posting needs the GitHub API - the report is saved locally; "
            "post it via the gh host or the orchestrating session's GitHub access"
        )
