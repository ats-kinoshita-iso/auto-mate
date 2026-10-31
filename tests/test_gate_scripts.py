"""The gate scripts' contract, exercised end to end with a fake Claude Code binary."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEGEN = REPO_ROOT / "scripts" / "gates" / "codegen.sh"

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("git")), reason="needs bash and git"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "switch", "-q", "-c", "feature")
    (repo / "a.txt").write_text("one\ntwo\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "change")
    return repo


def _fake_agent(tmp_path: Path, body: str, *, name: str = "claude", as_json: bool = True) -> Path:
    """A stand-in agent: ignores its arguments and prints a canned response."""
    script = tmp_path / "bin" / name
    script.parent.mkdir(exist_ok=True)
    if as_json:
        payload = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": "sess-fake",
            "total_cost_usd": 0.0123,
            "usage": {
                "input_tokens": 3,
                "output_tokens": 9,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 0,
            },
            "modelUsage": {
                "claude-haiku-5-5": {
                    "inputTokens": 3,
                    "outputTokens": 9,
                    "cacheReadInputTokens": 100,
                    "cacheCreationInputTokens": 0,
                    "costUSD": 0.0123,
                }
            },
            "duration_ms": 10,
            "duration_api_ms": 5,
            "num_turns": 1,
            "permission_denials": [],
            "result": body,
        }
        body = json.dumps(payload)
    script.write_text("#!/usr/bin/env bash\ncat <<'EOF_FAKE'\n" + body + "\nEOF_FAKE\n")
    script.chmod(0o755)
    return script


def _run_gate(repo: Path, agent: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GATE_AGENT_CMD": str(agent), **extra_env}
    return subprocess.run(
        ["bash", str(CODEGEN), "t1", "feature", "add a line", "main"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_pass_verdict_carries_a_usage_line(repo: Path, tmp_path: Path) -> None:
    agent = _fake_agent(tmp_path, "Looks complete.\nVERDICT: PASS")
    proc = _run_gate(repo, agent)
    assert proc.returncode == 0, proc.stderr
    assert "VERDICT: PASS" in proc.stdout
    usage_lines = [line for line in proc.stdout.splitlines() if line.startswith("USAGE: ")]
    assert len(usage_lines) == 1
    usage = json.loads(usage_lines[0][len("USAGE: ") :])
    assert usage["total_cost_usd"] == 0.0123 and usage["session_id"] == "sess-fake"
    assert "result" not in usage  # the review text is not duplicated into the trailer


def test_fail_verdict_exits_one_with_the_reason_on_stderr(repo: Path, tmp_path: Path) -> None:
    agent = _fake_agent(tmp_path, "Missing tests.\nVERDICT: FAIL - no tests for the new branch")
    proc = _run_gate(repo, agent)
    assert proc.returncode == 1
    assert "VERDICT: FAIL - no tests" in proc.stderr


def test_missing_verdict_is_an_infrastructure_error(repo: Path, tmp_path: Path) -> None:
    agent = _fake_agent(tmp_path, "I could not decide.")
    proc = _run_gate(repo, agent)
    assert proc.returncode == 2
    assert "no VERDICT line" in proc.stderr


def test_non_claude_agent_runs_in_plain_text_mode(repo: Path, tmp_path: Path) -> None:
    agent = _fake_agent(tmp_path, "Fine.\nVERDICT: PASS", name="reviewer", as_json=False)
    proc = _run_gate(repo, agent)
    assert proc.returncode == 0, proc.stderr
    assert not any(line.startswith("USAGE: ") for line in proc.stdout.splitlines())


def test_claude_that_prints_no_result_object_falls_back_verbatim(
    repo: Path, tmp_path: Path
) -> None:
    agent = _fake_agent(tmp_path, "Plain reply.\nVERDICT: PASS", as_json=False)
    proc = _run_gate(repo, agent)
    assert proc.returncode == 0, proc.stderr
    assert "VERDICT: PASS" in proc.stdout
    assert not any(line.startswith("USAGE: ") for line in proc.stdout.splitlines())


def test_json_mode_can_be_forced_off(repo: Path, tmp_path: Path) -> None:
    agent = _fake_agent(tmp_path, "Fine.\nVERDICT: PASS", as_json=False)
    proc = _run_gate(repo, agent, GATE_OUTPUT_JSON="0")
    assert proc.returncode == 0, proc.stderr
