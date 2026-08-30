"""Deciding whether a repository can supply usable tasks.

The published rule for choosing repositories is that they ship a benchmark
suite, so that workloads come from the project rather than from whoever is
doing the measuring. That rule is necessary and not sufficient. A suite is only
usable here if it exists at the commit a task is based on, and if it runs in
memory rather than reading a directory of files and shelling out to another
program.

This module answers that question for a candidate repository before any effort
is spent ingesting its tasks.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: A benchmark the harness can call. Several conventions are in use and none is
#: more valid than another: asv names methods ``time_*``, pytest-benchmark takes
#: a ``benchmark`` fixture, pyperf registers named callables. Recognising only
#: one of them rejects working repositories for using a different runner.
_TIMED_METHOD = re.compile(
    r"^\s*def\s+(time_|track_|test_.*benchmark)"      # asv, pytest-benchmark
    r"|\bbenchmark\s*\(\s*lambda"                    # pytest-benchmark inline
    r"|\.bench_func\s*\(|\.bench_time_func\s*\(",  # pyperf
    re.M,
)

#: Signs that a benchmark reaches outside the process for its input, which
#: would measure the filesystem as much as the code.
#:
#: Reading a data file that is checked in beside the benchmark is deliberately
#: *not* on this list. A fixed file in a sealed container is as deterministic as
#: a string literal, and an earlier version of this check rejected a good
#: repository for loading its own sample data. What cannot be sealed is
#: discovering inputs at run time or calling another program.
_REACHES_OUT = re.compile(
    r"\b(glob\.|glob\(|subprocess\.|os\.walk|os\.listdir|argparse\."
    r"|requests\.|urllib|socket\.|tempfile\.mkd)",
    re.M,
)

#: Commit subjects that claim a performance change.
#:
#: This is a recall-preserving prefilter and nothing more. Matching keywords in
#: commit messages runs at somewhere between ten and thirty per cent precision,
#: because a project whose subject matter is optimisation discusses optimising
#: constantly without changing its own speed. A count from this regex says a
#: repository is worth looking at, never that a particular commit is a genuine
#: optimisation; that judgement needs the change itself.
_PERF_SUBJECT = re.compile(
    r"^perf(\(|:|\s)"                                   # conventional commits
    r"|^(ENH|MAINT|PERF)\b.*\b(perf|speed|fast|optimi)"  # numpy-style prefixes
    r"|\b(speed(s|ed)?[ -]?up|faster|optimi[sz]e[ds]?)\b",
    re.I,
)

#: Test-harness speedups are real work and are not library optimisations.
_HARNESS_ONLY = re.compile(r"^perf\(tests?\)", re.I)


@dataclass
class RepoSurvey:
    """What a candidate repository can actually supply."""

    repo: str
    pure_python: bool
    suite_first_seen: str | None
    suite_files: int
    timed_methods: int
    self_contained: bool
    perf_commits_after_suite: int
    library_perf_commits: int
    note: str = ""

    @property
    def usable(self) -> bool:
        return (
            self.pure_python
            and self.suite_first_seen is not None
            and self.self_contained
            and self.library_perf_commits > 0
        )

    def __str__(self) -> str:
        verdict = "usable" if self.usable else "rejected"
        return (
            f"{self.repo:28s} {verdict:9s} suite={self.suite_first_seen or '-':10s} "
            f"timed={self.timed_methods:<4} library_perf={self.library_perf_commits:<4} "
            f"{self.note}"
        )


def _git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=600
    )
    return proc.stdout if proc.returncode == 0 else ""


def _benchmark_files(clone: Path) -> list[Path]:
    found: list[Path] = []
    for directory in ("benchmarks", "bench", "asv_bench"):
        root = clone / directory
        if root.is_dir():
            found.extend(p for p in root.rglob("*.py") if "__init__" not in p.name)
    return found


def survey(repo: str, cache: Path) -> RepoSurvey:
    """Assess one repository without ingesting any of its tasks."""
    from speedproof.corpus.checkout import ensure_clone

    clone = ensure_clone(repo, cache)

    compiled = [
        p
        for pattern in ("*.pyx", "*.rs")
        for p in clone.rglob(pattern)
        if ".git" not in p.parts and "test" not in str(p).lower()
    ]
    pure = not compiled

    files = _benchmark_files(clone)
    timed = 0
    reaches_out = 0
    for path in files:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        timed += len(_TIMED_METHOD.findall(text))
        if _REACHES_OUT.search(text):
            reaches_out += 1

    first_seen = None
    for directory in ("benchmarks", "bench"):
        out = _git(
            "log", "--diff-filter=A", "--format=%ci", "--reverse", "--", directory,
            cwd=clone,
        )
        if out.strip():
            candidate = out.split("\n")[0][:10]
            first_seen = min(first_seen, candidate) if first_seen else candidate

    after = library = 0
    if first_seen:
        for line in _git("log", "--format=%ci|%s", cwd=clone).splitlines():
            date, _, subject = line.partition("|")
            if date[:10] < first_seen or not _PERF_SUBJECT.search(subject):
                continue
            after += 1
            if not _HARNESS_ONLY.search(subject):
                library += 1

    note = ""
    if not pure:
        note = f"has {len(compiled)} compiled sources"
    elif not files:
        note = "no benchmark directory"
    elif timed == 0:
        note = "benchmarks define no timed methods"
    elif reaches_out and reaches_out >= len(files) / 2:
        note = f"{reaches_out}/{len(files)} benchmarks discover inputs at run time"

    return RepoSurvey(
        repo=repo,
        pure_python=pure,
        suite_first_seen=first_seen,
        suite_files=len(files),
        timed_methods=timed,
        self_contained=bool(timed) and reaches_out < max(1, len(files) / 2),
        perf_commits_after_suite=after,
        library_perf_commits=library,
        note=note,
    )
