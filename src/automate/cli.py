"""Command-line interface for the agent-execution layer."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from automate.adapters import TreehouseAdapter
from automate.config import Settings, get_settings
from automate.models import RunStatus, Task
from automate.orchestrator import Orchestrator

app = typer.Typer(
    name="automate",
    help="Agent-execution layer: worktrees, crews, governance, and safe-push gating.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

config_app = typer.Typer(help="Inspect configuration.", no_args_is_help=True)
worktrees_app = typer.Typer(help="Inspect worktrees.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(worktrees_app, name="worktrees")


def _settings(dry_run: bool | None) -> Settings:
    return get_settings() if dry_run is None else get_settings(dry_run=dry_run)


@app.command()
def run(
    prompt: Annotated[str, typer.Argument(help="Natural-language task for the crew.")],
    repo: Annotated[str, typer.Option("--repo", "-r", help="Target repo (path or URL).")] = ".",
    task_id: Annotated[
        str, typer.Option("--id", help="Identifier for the worktree/branch.")
    ] = "task",
    base_ref: Annotated[
        str | None, typer.Option("--base", help="Base ref for the worktree.")
    ] = None,
    dry_run: Annotated[
        bool | None, typer.Option("--dry-run/--execute", help="Override configured dry-run.")
    ] = None,
) -> None:
    """Run a task through the full execution lifecycle."""
    settings = _settings(dry_run)
    task = Task(
        id=task_id,
        prompt=prompt,
        repo=repo,
        base_ref=base_ref or settings.default_base_ref,
    )
    record = Orchestrator.from_settings(settings).run(task)
    console.print_json(record.model_dump_json())
    if record.status is RunStatus.FAILED:
        raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """Show the resolved dry-run state and which tools/gates are configured."""
    settings = get_settings()
    console.print(f"[bold]auto-mate[/bold]  dry_run=[cyan]{settings.dry_run}[/cyan]")
    console.print(f"  treehouse    : {settings.treehouse_bin}")
    console.print(f"  crew         : {settings.crew_backend} (agent={settings.agent_cmd})")
    console.print(f"  firstmate    : {settings.firstmate_home or '[dim]unset[/dim]'}")
    console.print(f"  no-mistakes  : {settings.no_mistakes_bin}")
    console.print(f"  governance   : {settings.governance_cmd or '[dim]disabled[/dim]'}")
    console.print(f"  codegen/eval : {settings.codegen_cmd or '[dim]disabled[/dim]'}")


@config_app.command("show")
def config_show() -> None:
    """Print the resolved configuration as JSON."""
    console.print_json(data=get_settings().model_dump())


@worktrees_app.command("ls")
def worktrees_ls(
    repo: Annotated[str, typer.Option("--repo", "-r", help="Repository to inspect.")] = ".",
) -> None:
    """Show treehouse's worktree pool for a repository."""
    settings = get_settings()
    adapter = TreehouseAdapter(settings.treehouse_bin, dry_run=settings.dry_run)
    console.print(adapter.status(repo), markup=False)  # raw tool output, not Rich markup


def main() -> None:
    """Console-script entrypoint."""
    app()
