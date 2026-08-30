"""Choosing the workloads that actually exercise a patch.

A repository's benchmark suite contains many workloads and a patch touches a
few lines. Measuring a workload that never executes those lines produces a
number that is perfectly reproducible and completely uninformative, so
selection has to be driven by what the workload runs rather than by what it is
called.

The published implementations of this idea share a set of blind spots, and each
one is a way to silently select nothing:

* **Only what the coverage tool measures can be a dependency.** Data files,
  templates and compiled extensions never appear, so a patch that changes one
  looks like a patch that changes nothing.
* **Only what runs inside a test can be a dependency.** Code executed at import
  or collection time is untraced, which makes a change to a package's
  ``__init__`` a hard miss.
* **A patch with no detected dependencies selects no workloads**, and a loop
  that skips such tasks reports a clean run over an empty set.

Every one of those is handled here by escalating to the whole suite rather than
by quietly selecting none. Over-selection costs measurement time; under-
selection produces a confident wrong answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_DIFF_HEADER = re.compile(r"^\+\+\+ b/(.+)$", re.M)
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)

#: Extensions whose contents coverage can attribute to a workload. Anything
#: else changes behaviour invisibly, as far as this selector is concerned.
_TRACEABLE = frozenset({".py"})

#: Paths that are part of a project's own checking rather than its behaviour.
#: A change confined to these does not need a performance workload at all.
_TEST_PATH = re.compile(r"(^|/)(tests?|testing|conftest\.py)(/|$)")


class Selection(str, Enum):
    """Why a set of workloads was chosen."""

    COVERED = "covered"
    """Workloads observed to execute the changed lines."""

    ALL_UNTRACEABLE = "all_untraceable"
    """The patch changes something coverage cannot attribute, so everything runs."""

    ALL_IMPORT_TIME = "all_import_time"
    """The patch changes code that runs at import, which coverage does not attribute."""

    ALL_NO_COVERAGE = "all_no_coverage"
    """No coverage was available, so nothing could be ruled out."""

    NONE_TESTS_ONLY = "none_tests_only"
    """The patch only changes the project's own tests."""


@dataclass(frozen=True)
class PatchScope:
    """Which lines of which files a patch changes, in the post-image."""

    lines: dict[str, set[int]] = field(default_factory=dict)

    @property
    def files(self) -> set[str]:
        return set(self.lines)

    @property
    def python_files(self) -> set[str]:
        return {f for f in self.lines if Path(f).suffix in _TRACEABLE}

    @property
    def untraceable_files(self) -> set[str]:
        """Changed files whose contents coverage cannot attribute to a workload."""
        return {
            f
            for f in self.lines
            if Path(f).suffix not in _TRACEABLE and not _TEST_PATH.search(f)
        }

    @property
    def only_touches_tests(self) -> bool:
        return bool(self.lines) and all(_TEST_PATH.search(f) for f in self.lines)

    @property
    def touches_import_time(self) -> bool:
        """True when the patch changes a module that runs before any workload.

        A package's ``__init__`` executes during import, which happens outside
        the region a coverage tool attributes to a workload. Such a change can
        break or speed up everything while appearing to touch nothing.
        """
        return any(Path(f).name == "__init__.py" for f in self.python_files)


def patch_scope(patch: str) -> PatchScope:
    """Read which post-image lines a unified diff touches."""
    lines: dict[str, set[int]] = {}
    current: str | None = None
    for line in patch.splitlines():
        header = _DIFF_HEADER.match(line)
        if header:
            current = header.group(1)
            lines.setdefault(current, set())
            continue
        hunk = _HUNK.match(line)
        if hunk and current is not None:
            start = int(hunk.group(1))
            count = int(hunk.group(2) or 1)
            lines[current].update(range(start, start + count))
    # A file listed with no hunks carries no information; keep it as a changed
    # file so that untraceable-extension checks still see it.
    return PatchScope(lines=lines)


@dataclass(frozen=True)
class WorkloadSelection:
    """The workloads to measure for a task, and why."""

    workloads: tuple[str, ...]
    reason: Selection
    detail: str = ""

    @property
    def measurable(self) -> bool:
        return bool(self.workloads)

    def __str__(self) -> str:
        return (
            f"{len(self.workloads)} workload(s) [{self.reason.value}]"
            + (f": {self.detail}" if self.detail else "")
        )


def select_workloads(
    patch: str,
    coverage: dict[str, dict[str, set[int]]] | None,
    all_workloads: tuple[str, ...],
) -> WorkloadSelection:
    """Choose which workloads to measure for ``patch``.

    ``coverage`` maps a workload name to the lines it executed, per file. Pass
    ``None`` when coverage could not be collected; the whole suite is then
    selected, because nothing can be ruled out.
    """
    scope = patch_scope(patch)

    if scope.only_touches_tests:
        return WorkloadSelection(
            (), Selection.NONE_TESTS_ONLY,
            "the patch changes only the project's own tests",
        )

    if scope.untraceable_files:
        sample = ", ".join(sorted(scope.untraceable_files)[:3])
        return WorkloadSelection(
            all_workloads, Selection.ALL_UNTRACEABLE,
            f"changes files coverage cannot attribute ({sample})",
        )

    if scope.touches_import_time:
        return WorkloadSelection(
            all_workloads, Selection.ALL_IMPORT_TIME,
            "changes a module executed at import, which coverage does not attribute",
        )

    if coverage is None:
        return WorkloadSelection(
            all_workloads, Selection.ALL_NO_COVERAGE,
            "no coverage available, so no workload could be ruled out",
        )

    chosen: list[str] = []
    for workload, covered in coverage.items():
        for path, changed in scope.lines.items():
            if changed & covered.get(path, set()):
                chosen.append(workload)
                break

    if not chosen:
        # Deliberately not an empty selection. Coverage says these workloads do
        # not reach the change, but coverage misses import-time execution and
        # anything it cannot attribute, so "no workload is relevant" is a claim
        # this data cannot support.
        return WorkloadSelection(
            (), Selection.COVERED,
            "no workload was observed to execute the changed lines",
        )

    return WorkloadSelection(
        tuple(sorted(chosen)), Selection.COVERED,
        f"execute {sum(len(v) for v in scope.lines.values())} changed line(s)",
    )
