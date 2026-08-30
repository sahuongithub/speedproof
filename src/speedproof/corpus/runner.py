"""Taking one task from repository history to a verdict.

The stages are: check the task out, discover what its project offers as
workloads, find which of those reach the lines the patch changes, measure the
chosen one on both trees, and compare what each computed.

Most candidates do not survive this. A task can fail because its patch no
longer applies, because its project's benchmarks do not exercise the change,
because a workload does not run, or because the human's optimisation is too
small to measure. Each of those is recorded as its own outcome rather than
collapsed into a failure count, because the distribution of reasons is a result
in itself: it says what fraction of real optimisation work is measurable at
all, which nobody appears to have reported.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

from speedproof.corpus.checkout import CheckoutError, materialise, release
from speedproof.corpus.coverage import collect
from speedproof.corpus.relevance import Selection, select_workloads
from speedproof.corpus.task import Task
from speedproof.corpus.workload import Benchmark, discover, install
from speedproof.verifyperf.callgrind import MeasurementError, measure
from speedproof.verifyperf.fingerprint import Fingerprint


class Outcome(str, Enum):
    """Why a task did or did not become part of the corpus."""

    VALIDATED = "validated"
    """Measurable, correct, and the human's optimisation is visible."""

    NO_EFFECT = "no_effect"
    """Measured cleanly; the change is below the threshold on this workload."""

    REGRESSED = "regressed"
    """The patch measurably increases work on the selected workload."""

    NOT_EQUIVALENT = "not_equivalent"
    """The two trees compute different answers. Interesting, and excluded."""

    NO_WORKLOAD = "no_workload"
    """No workload in the project's suite reaches the changed lines."""

    NO_BENCHMARKS = "no_benchmarks"
    """The project has no callable benchmark at this commit."""

    PATCH_FAILED = "patch_failed"
    """The recorded patch no longer applies at the commit it names."""

    UNMEASURABLE = "unmeasurable"
    """Something did not run, so no verdict was reached."""

    @property
    def usable(self) -> bool:
        return self is Outcome.VALIDATED


@dataclass
class TaskResult:
    """What happened to one task, in enough detail to act on."""

    task_id: str
    repo: str
    classification: str
    outcome: Outcome
    detail: str = ""
    workload: str | None = None
    workloads_considered: int = 0
    selection_reason: str | None = None
    base_net_ir: int | None = None
    patched_net_ir: int | None = None
    work_reduction: float | None = None
    deterministic: bool | None = None
    equivalent: bool | None = None
    fingerprint: dict | None = None

    def line(self) -> str:
        head = f"{self.outcome.value:16s} {self.task_id:26s}"
        if self.work_reduction is not None:
            return (
                f"{head} {self.work_reduction:+7.2%}  "
                f"{self.base_net_ir:>12,} -> {self.patched_net_ir:>12,}"
            )
        return f"{head} {self.detail}"


@dataclass
class CorpusReport:
    """The outcome of every candidate, and the funnel they came through."""

    results: list[TaskResult] = field(default_factory=list)

    @property
    def validated(self) -> list[TaskResult]:
        return [r for r in self.results if r.outcome.usable]

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.outcome.value] = counts.get(result.outcome.value, 0) + 1
        return counts

    def summary(self) -> str:
        counts = self.counts()
        width = max((len(k) for k in counts), default=10)
        lines = [f"{len(self.results)} candidate(s) attempted"]
        for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {name:<{width}}  {count:>3}")
        lines.append(f"\n{len(self.validated)} validated")
        return "\n".join(lines)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "counts": self.counts(),
                    "validated": len(self.validated),
                    "results": [asdict(r) | {"outcome": r.outcome.value}
                                for r in self.results],
                },
                indent=1,
            )
            + "\n"
        )


def run_task(
    task: Task,
    cache: Path,
    workspace: Path,
    image: str | None = None,
    platform: str | None = None,
    threshold: float = 0.02,
    repetitions: int = 2,
    fingerprint: Fingerprint | None = None,
    keep: bool = False,
) -> TaskResult:
    """Carry one task through every stage and report where it got to."""
    result = TaskResult(
        task_id=task.task_id,
        repo=task.repo,
        classification=task.classification,
        outcome=Outcome.UNMEASURABLE,
    )

    try:
        trees = materialise(task, cache, workspace, keep=True)
    except CheckoutError as exc:
        result.outcome = Outcome.PATCH_FAILED
        result.detail = str(exc).splitlines()[0][:100]
        return result

    try:
        benchmarks = discover(trees.base, task.benchmark_files)
        result.workloads_considered = len(benchmarks)
        if not benchmarks:
            result.outcome = Outcome.NO_BENCHMARKS
            result.detail = "no callable benchmark at this commit"
            return result

        try:
            coverage = collect(trees.base, benchmarks, image=image, platform=platform)
        except MeasurementError as exc:
            # Coverage is unavailable rather than empty. The selector escalates
            # on that rather than concluding nothing is relevant.
            coverage = None
            result.detail = f"coverage unavailable: {str(exc).splitlines()[0][:60]}"

        selection = select_workloads(
            task.patch, coverage, tuple(b.name for b in benchmarks)
        )
        result.selection_reason = selection.reason.value
        if not selection.measurable:
            result.outcome = (
                Outcome.NO_WORKLOAD
                if selection.reason is Selection.COVERED
                else Outcome.NO_BENCHMARKS
            )
            result.detail = selection.detail
            return result

        # Measure the cheapest relevant workload. Where several reach the
        # change they are measuring the same patch, and Valgrind is expensive
        # enough that the choice is worth making deliberately.
        chosen_name = min(
            selection.workloads,
            key=lambda n: sum(len(v) for v in (coverage or {}).get(n, {}).values())
            or 10**9,
        )
        chosen = next(b for b in benchmarks if b.name == chosen_name)
        result.workload = chosen.name

        measurements = {}
        for side, tree in (("base", trees.base), ("patched", trees.patched)):
            workload, baseline = install(tree, chosen)
            measurements[side] = measure(
                tree,
                workload,
                repetitions=repetitions,
                fingerprint=fingerprint,
                platform=platform,
                image=image,
                baseline=baseline,
            )

        base, patched = measurements["base"], measurements["patched"]
        result.base_net_ir = base.net
        result.patched_net_ir = patched.net
        result.deterministic = base.deterministic and patched.deterministic
        result.fingerprint = asdict(base.fingerprint)

        if base.net <= 0:
            result.outcome = Outcome.UNMEASURABLE
            result.detail = "the workload does no measurable work"
            return result

        result.work_reduction = (base.net - patched.net) / base.net

        equivalent = _same_answer(trees, chosen, image, platform)
        result.equivalent = equivalent
        if equivalent is False:
            result.outcome = Outcome.NOT_EQUIVALENT
            result.detail = "the two trees compute different answers"
            return result

        if result.work_reduction >= threshold:
            result.outcome = Outcome.VALIDATED
        elif result.work_reduction <= -threshold:
            result.outcome = Outcome.REGRESSED
        else:
            result.outcome = Outcome.NO_EFFECT
            result.detail = f"below the {threshold:.0%} threshold"
        return result

    except MeasurementError as exc:
        result.outcome = Outcome.UNMEASURABLE
        result.detail = str(exc).splitlines()[0][:100]
        return result
    finally:
        if not keep:
            release(task, workspace / task.slug, cache)


def _same_answer(trees, benchmark: Benchmark, image, platform) -> bool | None:
    """Whether both trees compute the same thing, where that can be seen.

    A benchmark under this convention usually returns nothing, so for most
    workloads there is no value to compare and this returns ``None``: unknown,
    not equal. Reporting unknown as equal would be the vacuous check every
    published benchmark in this area has, so correctness for those tasks has to
    come from the project's own tests instead.
    """
    from speedproof.verifyperf.verify import _capture

    try:
        digests = {
            side: _capture(
                tree,
                Path(f"_sp_{benchmark.cls or 'fn'}_{benchmark.method}".lower() + ".py"),
                "checksum",
                platform,
            )
            for side, tree in (("base", trees.base), ("patched", trees.patched))
        }
    except Exception:
        return None
    # Every timing benchmark returns None, which hashes identically whatever
    # the code did. That agreement is not evidence.
    if len(set(digests.values())) == 1 and _is_empty_digest(digests["base"]):
        return None
    return digests["base"] == digests["patched"]


#: The canonical encoding of ``None``, which is what a timing benchmark returns.
_NONE_DIGEST: str | None = None


def _is_empty_digest(digest: str) -> bool:
    global _NONE_DIGEST
    if _NONE_DIGEST is None:
        from speedproof.verifyperf.canon import checksum

        _NONE_DIGEST = checksum(None)
    return digest == _NONE_DIGEST
