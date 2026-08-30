"""Finding optimisation commits in a repository's own history.

Published mining pipelines take a repository's merged pull requests, filter
them by keywords, and pass the survivors to a language model to judge intent.
The keyword step is a recall-preserving prefilter and nothing more: measured
precision on commit subjects runs somewhere between ten and thirty per cent,
because a project whose subject matter is optimisation discusses optimising
constantly without changing its own speed.

The approach here is narrower and needs no judge. A project that marks its
optimisations in its commit subjects -- with a conventional-commits `perf:`
prefix, or a project-specific equivalent -- has already told us its intent, and
that annotation was written by the person who made the change rather than
inferred afterwards. Fewer projects qualify, and the ones that do give up their
history almost for free.

What still has to be checked, because the annotation does not say it: that the
change touches the library rather than its test harness, that a benchmark suite
existed at that commit, and -- the part every pipeline gets wrong -- that some
benchmark actually executes the lines the change touches.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from speedproof.corpus.task import Task

#: Subjects that claim an optimisation. Conventional commits first, then the
#: prefixes the scientific-Python projects use.
_PERF_SUBJECT = re.compile(
    r"^perf(\([^)]*\))?:"          # perf: / perf(scope):
    r"|^(ENH|MAINT|PERF)\b.*\b(perf|speed|fast|optimi)",
    re.I,
)

#: Speeding up a project's own test run is real work and is not a library
#: optimisation, so it cannot be measured by a library benchmark.
_HARNESS_SCOPE = re.compile(r"^perf\((tests?|ci|build|docs?)\)", re.I)


@dataclass(frozen=True)
class MiningReport:
    """What the history offered, and what survived each filter."""

    commits_scanned: int = 0
    claimed_perf: int = 0
    library_only: int = 0
    after_suite: int = 0
    single_parent: int = 0
    kept: int = 0

    def summary(self) -> str:
        return "\n".join(
            [
                f"  commits scanned          {self.commits_scanned:>6}",
                f"  claim an optimisation    {self.claimed_perf:>6}",
                f"  change the library       {self.library_only:>6}",
                f"  after the suite existed  {self.after_suite:>6}",
                f"  have a single parent     {self.single_parent:>6}",
                f"  kept                     {self.kept:>6}",
            ]
        )


def _git(*args: str, cwd: Path) -> str:
    """Run git and decode leniently.

    A long-lived repository will contain commit messages that are not valid
    UTF-8 -- sympy has one at around eight megabytes into its log. Decoding
    strictly means one such byte ends the mining run for the whole project, so
    undecodable bytes are replaced rather than raised on.
    """
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, timeout=600
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace")


def _suite_first_seen(clone: Path, benchmark_dir: str) -> str | None:
    out = _git(
        "log", "--diff-filter=A", "--format=%ci", "--reverse", "--", benchmark_dir,
        cwd=clone,
    )
    return out.split("\n")[0][:10] if out.strip() else None


def mine(
    repo: str,
    clone: Path,
    library_dir: str = "src/",
    benchmark_dir: str = "benchmarks",
    classification: str = "declared_optimisation",
) -> tuple[list[Task], MiningReport]:
    """Read a repository's history for changes it says are optimisations."""
    suite_from = _suite_first_seen(clone, benchmark_dir)
    scanned = claimed = library = after = single = 0
    tasks: list[Task] = []

    log = _git("log", "--format=%H|%P|%ci|%s", cwd=clone).splitlines()
    for line in log:
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        sha, parents, date, subject = parts
        scanned += 1

        if not _PERF_SUBJECT.search(subject) or _HARNESS_SCOPE.search(subject):
            continue
        claimed += 1

        changed = _git(
            "show", "--stat", "--format=", "--name-only", sha, cwd=clone
        ).split()
        touches_library = [f for f in changed if f.startswith(library_dir)]
        touches_only_library = touches_library and not any(
            f.startswith(("tests/", "docs/", ".github/")) for f in changed
        )
        if not touches_only_library:
            continue
        library += 1

        if suite_from and date[:10] < suite_from:
            continue
        after += 1

        # A merge has no single "before", so there is no base tree to compare
        # against and no patch that isolates the change.
        parent_list = parents.split()
        if len(parent_list) != 1:
            continue
        single += 1

        base = parent_list[0]
        patch = _git("format-patch", "-1", "--stdout", "--no-signature", sha, cwd=clone)
        if not patch.strip():
            continue

        benchmark_files = tuple(
            f
            for f in _git("ls-tree", "-r", "--name-only", base, cwd=clone).splitlines()
            if f.startswith(f"{benchmark_dir}/")
            and f.endswith(".py")
            and "__init__" not in f
        )
        if not benchmark_files:
            continue

        tasks.append(
            Task(
                task_id=f"{repo.split('/')[-1]}_{sha[:10]}",
                repo=repo,
                base_sha=base,
                merge_sha=sha,
                patch=patch,
                classification=classification,
                difficulty="unknown",
                merged_at=date.replace(" ", "T", 1)[:19] + "Z",
                benchmark_files=benchmark_files,
            )
        )

    return tasks, MiningReport(
        commits_scanned=scanned,
        claimed_perf=claimed,
        library_only=library,
        after_suite=after,
        single_parent=single,
        kept=len(tasks),
    )
