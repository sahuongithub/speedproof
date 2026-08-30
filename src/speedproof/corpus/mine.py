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
#: uppercase prefixes the scientific-Python projects use -- pandas, numpy and
#: scipy all write ``PERF:``.
_PERF_SUBJECT = re.compile(
    r"^perf(\([^)]*\))?:"          # perf: / perf(scope):
    r"|^PERF[:\s]"                  # PERF: as pandas and numpy write it
    r"|^(ENH|MAINT)\b.*\b(perf|speed|fast|optimi)",
    re.I,
)

#: Optimisations whose benefit an instruction count cannot see, recognised from
#: the subject line so they are never mined in the first place. Valgrind
#: serialises threads, so a change that genuinely scales across cores is
#: recorded as a regression; the rest are excluded by the validity boundary.
_OUT_OF_SCOPE_SUBJECT = re.compile(
    r"\b(parallel|multithread|thread(ed|ing)?|nogil|concurren|simd|avx|sse|neon"
    r"|vectori[sz])\b",
    re.I,
)

#: Speeding up a project's own test run is real work and is not a library
#: optimisation, so it cannot be measured by a library benchmark.
_HARNESS_SCOPE = re.compile(r"^perf\((tests?|ci|build|docs?)\)", re.I)


class MiningError(Exception):
    """Raised when a repository's history could not be read."""


@dataclass(frozen=True)
class MiningReport:
    """What the history offered, and what survived each filter."""

    commits_scanned: int = 0
    out_of_scope: int = 0
    claimed_perf: int = 0
    library_only: int = 0
    after_suite: int = 0
    single_parent: int = 0
    kept: int = 0

    def summary(self) -> str:
        return "\n".join(
            [
                f"  commits scanned          {self.commits_scanned:>6}",
                f"  out of scope for Ir      {self.out_of_scope:>6}",
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
    python_only: bool = False,
    since: str | None = None,
) -> tuple[list[Task], MiningReport]:
    """Read a repository's history for changes it says are optimisations.

    ``since`` bounds how far back to look, as a date git understands. Bounding
    is not only a speed measure: on a blobless clone, walking a long history
    with file names attached needs tree objects the clone does not hold, and
    git will try to fetch them. On pandas that failed outright after
    sixty-nine seconds and returned nothing at all, which is a silent zero
    rather than an error. A recent window is also the more useful one, since
    those commits are likeliest to still build.
    """
    suite_from = _suite_first_seen(clone, benchmark_dir)
    scanned = claimed = library = after = single = out_of_scope = 0
    tasks: list[Task] = []

    # One pass, with the changed files inline. Asking git for each commit's
    # files separately costs a process per candidate, which on a repository of
    # pandas' size takes longer than the whole rest of the pipeline.
    window = ["--since", since] if since else []
    raw = _git(
        "log", "--format=%x00%H|%P|%ci|%s", "--name-only", *window, cwd=clone
    ).split("\x00")
    if len(raw) <= 1:
        raise MiningError(
            "git returned no history. On a blobless clone this usually means "
            "the walk needed tree objects the clone does not hold; bound it "
            "with `since=`."
        )
    for record in raw:
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        parts = header.split("|", 3)
        if len(parts) != 4:
            continue
        sha, parents, date, subject = parts
        changed = [f for f in body.split("\n") if f.strip()]
        scanned += 1

        if not _PERF_SUBJECT.search(subject) or _HARNESS_SCOPE.search(subject):
            continue
        if _OUT_OF_SCOPE_SUBJECT.search(subject):
            # Not a rejection of the change, only of this instrument's ability
            # to judge it.
            out_of_scope += 1
            continue
        claimed += 1

        touches_library = [f for f in changed if f.startswith(library_dir)]
        touches_only_library = touches_library and not any(
            f.startswith(("tests/", "docs/", ".github/")) for f in changed
        )
        if not touches_only_library:
            continue
        # When a project ships compiled extensions, a patch confined to Python
        # leaves the compiled artefacts identical on both sides, so a single
        # build serves the comparison.
        if python_only and not all(f.endswith(".py") for f in touches_library):
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
        out_of_scope=out_of_scope,
        claimed_perf=claimed,
        library_only=library,
        after_suite=after,
        single_parent=single,
        kept=len(tasks),
    )
