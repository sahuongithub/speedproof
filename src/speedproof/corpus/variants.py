"""Preparing a task once, and measuring several answers to it.

A task already carries the two trees a corpus run needs: the code before a
maintainer optimised it, and the same code after. Everything expensive about
getting to a measurement -- checking out, compiling, discovering what the
project offers as workloads, profiling them, deciding which one reaches the
changed lines -- is done to produce that pair, and none of it depends on whose
optimisation is being measured.

So it is done once, and then several answers are measured against it:

``base``
    The code as it stood. The starting point every other answer is relative to.

``human``
    The maintainer's own patch. This is the interesting one to compare against,
    because it is what someone who knew the codebase actually did, and it makes
    the question "did the agent find what the human found" rather than "did the
    agent make a number go down".

``one_shot``
    One prompt with basic instructions, which is the first baseline the brief
    sanctions. Same code, same request, same measurement.

``agent``
    The loop.

All four are measured on the same workload with the same oracle and the same
correctness gate. Nothing about the comparison depends on the agent behaving,
because the agent's only contribution is a patch; everything after that happens
where it cannot reach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from speedproof.corpus.build import build, needs_build, share_artefacts
from speedproof.corpus.checkout import Trees, materialise
from speedproof.corpus.coverage import collect as collect_coverage
from speedproof.corpus.relevance import WorkloadSelection, select_workloads
from speedproof.corpus.task import Task
from speedproof.corpus.workload import Benchmark, discover, install
from speedproof.speedagent.profile import Profile
from speedproof.speedagent.profile import collect as collect_profile
from speedproof.verifyperf.callgrind import IrMeasurement, MeasurementError, measure
from speedproof.verifyperf.fingerprint import Fingerprint


class Variant(str, Enum):
    """Whose answer is being measured."""

    BASE = "base"
    HUMAN = "human"
    ONE_SHOT = "one_shot"
    AGENT = "agent"


@dataclass
class Prepared:
    """Everything a task needs before any answer can be measured.

    Produced once per task. The cost of getting here -- a pandas build alone is
    around four minutes -- is why it is not produced once per answer.
    """

    task: Task
    trees: Trees
    benchmark: Benchmark
    workload: Path
    workload_baseline: Path
    selection: WorkloadSelection
    profile: Profile
    fingerprint: Fingerprint
    image: str | None = None
    platform: str | None = None
    #: What the base tree computes, as a canonical digest. Every other answer
    #: is required to match it, or it is not an optimisation.
    reference: str | None = None
    #: Files the human's patch changes, which is what an agent is pointed at.
    changed_files: tuple[str, ...] = field(default=())


class NotPreparable(Exception):
    """Raised when a task cannot be brought to the point of measurement.

    Carries the reason as one of the runner's outcomes, so a task that cannot
    be prepared is reported as what stopped it rather than as a failure.
    """

    def __init__(self, outcome: str, detail: str) -> None:
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail


def prepare(
    task: Task,
    cache: Path,
    workspace: Path,
    image: str | None = None,
    platform: str | None = None,
    fingerprint: Fingerprint | None = None,
) -> Prepared:
    """Bring a task to the point where an answer can be measured."""
    from speedproof.corpus.relevance import Selection, patch_scope
    from speedproof.verifyperf.callgrind import probe_environment
    from speedproof.verifyperf.verify import _capture

    trees = materialise(task, cache, workspace, keep=True)

    if needs_build(task.repo):
        build(task.repo, trees.base, image=image, platform=platform)
        share_artefacts(trees.base, trees.patched)

    benchmarks = discover(trees.base, task.benchmark_files)
    if not benchmarks:
        raise NotPreparable("no_benchmarks", "no callable benchmark at this commit")

    try:
        coverage = collect_coverage(
            trees.base, benchmarks, image=image, platform=platform
        )
    except MeasurementError as exc:
        coverage = None  # unavailable, which the selector escalates on
        del exc

    selection = select_workloads(
        task.patch, coverage, tuple(b.name for b in benchmarks)
    )
    if not selection.measurable:
        outcome = (
            "no_workload" if selection.reason is Selection.COVERED else "no_benchmarks"
        )
        raise NotPreparable(outcome, selection.detail)

    # Where several workloads reach the change they measure the same patch, so
    # the cheapest is chosen. Valgrind is expensive enough to decide this
    # deliberately rather than take the first.
    chosen_name = min(
        selection.workloads,
        key=lambda n: sum(len(v) for v in (coverage or {}).get(n, {}).values())
        or 10**9,
    )
    chosen = next(b for b in benchmarks if b.name == chosen_name)

    workload, workload_baseline = install(trees.base, chosen)
    install(trees.patched, chosen)

    fingerprint = fingerprint or probe_environment(trees.base, platform, image)
    reference = None
    try:
        reference = _capture(trees.base, workload, "checksum", platform)
    except Exception:
        # Unknown, not equal. A workload that returns nothing comparable is
        # handled by the caller rather than silently treated as agreeing.
        pass

    profile = collect_profile(trees.base, workload, image=image, platform=platform)

    return Prepared(
        task=task,
        trees=trees,
        benchmark=chosen,
        workload=workload,
        workload_baseline=workload_baseline,
        selection=selection,
        profile=profile,
        fingerprint=fingerprint,
        image=image,
        platform=platform,
        reference=reference,
        changed_files=tuple(sorted(patch_scope(task.patch).python_files)),
    )


def measure_tree(prepared: Prepared, tree: Path, repetitions: int = 2) -> IrMeasurement:
    """Measure one tree on the task's chosen workload."""
    return measure(
        tree,
        prepared.workload,
        repetitions=repetitions,
        fingerprint=prepared.fingerprint,
        platform=prepared.platform,
        image=prepared.image,
        baseline=prepared.workload_baseline,
    )


def computes_same_answer(prepared: Prepared, tree: Path) -> bool | None:
    """Whether ``tree`` computes what the base tree computed.

    Returns None when there is nothing to compare -- a timing benchmark returns
    None, which hashes identically whatever the code did, and reporting that
    agreement as equality is the vacuous check this project exists to avoid.
    """
    from speedproof.verifyperf.canon import checksum
    from speedproof.verifyperf.verify import _capture

    if prepared.reference is None:
        return None
    try:
        digest = _capture(tree, prepared.workload, "checksum", prepared.platform)
    except Exception:
        return None
    if digest == checksum(None):
        return None
    return digest == prepared.reference
