"""A tree the agent may edit, which is not the tree the corpus holds.

Letting an agent write into the corpus checkout would be wrong in three
separate ways. A failed run leaves the tree modified, so the next task starts
from something other than the commit it names. Two tasks cannot run at once.
And an agent that edits a file the harness later reads has, in a small way,
reached the thing that judges it.

So the agent gets its own tree. Making that cheap matters, because a built
pandas checkout runs to hundreds of megabytes and the agent may touch three
files in it: the copy is made with hard links, so it costs almost nothing and
almost no space, and the link is broken on the first write to any file.

Breaking the link is the part that has to be right. Opening a hard-linked file
and writing to it modifies every name that file has, including the corpus's
own -- silently, with no error, and in a way that would corrupt subsequent
measurements rather than fail them. Every write here therefore goes to a new
file which is then renamed into place, so the original is untouched by
construction rather than by care.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: Where workspaces are made.
#:
#: Not the system temporary directory. On macOS that resolves under
#: /var/folders, which the container runtime does not mount into its virtual
#: machine, so a workspace created there exists on the host and is empty inside
#: the container. Every measurement then fails identically and the failure
#: looks like the agent's, which is how two rounds of a real run were lost
#: before the cause was found.
WORKSPACE_ROOT = Path.home() / ".speedproof" / "workspaces"

#: Files the agent has no business editing. The measurement reads these, and a
#: patch that changes them is changing the instrument rather than the code.
PROTECTED = (
    "_sp_",              # generated workloads and their paired baselines
    ".git",
    "conftest.py",
)


class WorkspaceError(Exception):
    """Raised when a workspace cannot be made or would be unsafe to use."""


@dataclass
class Workspace:
    """An isolated, cheap copy of a source tree."""

    root: Path
    origin: Path
    _written: set[str] = field(default_factory=set)

    # ---------------------------------------------------------------- making

    @classmethod
    def clone(cls, origin: Path, into: Path | None = None) -> "Workspace":
        """Make a hard-linked copy of ``origin``.

        ``cp -al`` links rather than copies, so a large tree costs almost
        nothing. Where it is unavailable the copy is made properly, which is
        slower and equally correct.
        """
        origin = Path(origin).resolve()
        if not origin.is_dir():
            raise WorkspaceError(f"nothing to clone at {origin}")
        if into is not None:
            root = Path(into)
        else:
            WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
            root = Path(tempfile.mkdtemp(prefix="agent-", dir=WORKSPACE_ROOT))
        root = root.resolve()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

        linked = subprocess.run(
            ["cp", "-al", str(origin), str(root)], capture_output=True
        )
        if linked.returncode != 0:
            shutil.copytree(origin, root, symlinks=True, dirs_exist_ok=True)
        return cls(root=root, origin=origin)

    # ---------------------------------------------------------------- using

    def read(self, relative: Path | str) -> str:
        return (self.root / relative).read_text()

    def write(self, relative: Path | str, text: str) -> None:
        """Replace a file, without touching the copy it was linked from.

        Writing into a hard-linked file changes every name that file has, so
        the new contents go to a fresh file which is renamed over the old one.
        Renaming replaces the directory entry and leaves the original inode,
        and therefore the corpus's copy, alone.
        """
        relative = Path(relative)
        self._refuse_if_protected(relative)
        target = (self.root / relative).resolve()
        self._refuse_if_outside(target)

        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=target.parent, prefix=".sp-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w") as stream:
                stream.write(text)
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        self._written.add(str(relative))

    @property
    def written(self) -> tuple[str, ...]:
        """Every file the agent has changed, for the record and for review."""
        return tuple(sorted(self._written))

    def diff(self) -> str:
        """What the agent changed, as a patch against the original tree."""
        if not self._written:
            return ""
        result = subprocess.run(
            ["diff", "-u", "-r", "--new-file", str(self.origin), str(self.root)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.stdout

    # ------------------------------------------------------------- guarding

    def _refuse_if_protected(self, relative: Path) -> None:
        parts = relative.parts
        name = relative.name
        if any(name.startswith(p) or p in parts for p in PROTECTED):
            raise WorkspaceError(
                f"{relative} is part of the measurement, not the code under "
                "measurement, and cannot be edited"
            )

    def _refuse_if_outside(self, target: Path) -> None:
        """Refuse a path that resolves outside the workspace.

        A relative path containing ``..``, or one landing on a symlink that
        points elsewhere, would otherwise let a write escape into the corpus
        or anywhere else the process can reach.
        """
        try:
            target.relative_to(self.root)
        except ValueError:
            raise WorkspaceError(
                f"{target} is outside the workspace"
            ) from None

    # ------------------------------------------------------------- clearing

    def release(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()
