"""Materialising a task as two source trees.

A comparison needs the project as it stood before a human's optimisation, and
the same project with that optimisation applied. Both are produced as git
worktrees off a single local clone, so the two trees exist side by side and
neither is a mutation of the other.

The patch is applied rather than the merge commit being checked out. A merge
commit carries everything else that landed alongside it; the patch carries only
the change being measured.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from speedproof.corpus.task import Task


class CheckoutError(Exception):
    """Raised when a task cannot be materialised."""


@dataclass(frozen=True)
class Trees:
    """The two source trees a comparison runs against."""

    base: Path
    patched: Path
    task: Task


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=600
    )
    if check and proc.returncode != 0:
        raise CheckoutError(
            f"git {' '.join(args)} failed:\n{proc.stderr.strip()[-1500:]}"
        )
    return proc.stdout


def ensure_clone(repo: str, cache: Path) -> Path:  # noqa: D401
    """Clone ``repo`` into ``cache`` if it is not already there.

    Blobs are fetched on demand: the history is needed for its commits, and
    downloading every version of every file is not.
    """
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    local = cache / repo.split("/")[-1]
    if not (local / ".git").exists():
        _git(
            "clone",
            "--quiet",
            "--filter=blob:none",
            f"https://github.com/{repo}.git",
            str(local),
        )
    return local


def materialise(
    task: Task, cache: Path, workspace: Path, keep: bool = False
) -> Trees:
    """Produce the before and after trees for one task.

    ``keep`` leaves an existing workspace alone, which makes repeated
    measurement of the same task cheap.
    """
    clone = ensure_clone(task.repo, cache)
    # Absolute throughout: git resolves a relative worktree path against its
    # own working directory, which would put the trees inside the clone.
    workspace = Path(workspace).resolve() / task.slug
    base = workspace / "base"
    patched = workspace / "patched"

    if keep and base.exists() and patched.exists():
        return Trees(base=base, patched=patched, task=task)

    release(task, workspace, cache)
    workspace.mkdir(parents=True, exist_ok=True)

    for tree in (base, patched):
        _git("worktree", "add", "--detach", "--quiet", str(tree), task.base_sha,
             cwd=clone)

    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=patched,
        input=task.patch,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        release(task, workspace, cache)
        raise CheckoutError(
            f"the recorded patch for {task.task_id} does not apply at "
            f"{task.base_sha[:12]}:\n{proc.stderr.strip()[-1500:]}"
        )

    return Trees(base=base, patched=patched, task=task)


def release(task: Task, workspace: Path, cache: Path | None = None) -> None:
    """Remove a task's worktrees and the directory holding them."""
    workspace = Path(workspace).resolve()
    if not workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
        return
    if cache is not None:
        clone = Path(cache).resolve() / task.repo.split("/")[-1]
        if (clone / ".git").exists():
            for tree in (workspace / "base", workspace / "patched"):
                _git("worktree", "remove", "--force", str(tree),
                     cwd=clone, check=False)
    shutil.rmtree(workspace, ignore_errors=True)
