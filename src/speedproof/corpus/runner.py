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

from speedproof.corpus.checkout import CheckoutError, release
from speedproof.corpus.task import Task
from speedproof.corpus.variants import (
    GroundTruthFailed,
    NotPreparable,
    computes_same_answer,
    measure_tree,
    prepare,
)
from speedproof.verifyperf.callgrind import MeasurementError
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

    GROUND_TRUTH_FAILED = "ground_truth_failed"
    """The maintainer's own patch does not pass the gate on this workload.

    The task is broken rather than hard: no arm could be judged fairly on it,
    since the reference answer itself does not satisfy the check. Counted and
    reported rather than quietly dropped.
    """

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
        prepared = prepare(
            task, cache, workspace,
            image=image, platform=platform, fingerprint=fingerprint,
        )
    except CheckoutError as exc:
        result.outcome = Outcome.PATCH_FAILED
        result.detail = str(exc).splitlines()[0][:100]
        return result
    except GroundTruthFailed as exc:
        result.outcome = Outcome.GROUND_TRUTH_FAILED
        result.detail = str(exc)[:120]
        return result
    except NotPreparable as exc:
        result.outcome = Outcome(exc.outcome)
        result.detail = exc.detail
        return result
    except MeasurementError as exc:
        result.outcome = Outcome.UNMEASURABLE
        result.detail = str(exc).splitlines()[0][:100]
        return result

    try:
        result.workload = prepared.benchmark.name
        result.workloads_considered = len(prepared.selection.workloads)
        result.selection_reason = prepared.selection.reason.value

        base = measure_tree(prepared, prepared.trees.base, repetitions)
        patched = measure_tree(prepared, prepared.trees.patched, repetitions)
        result.base_net_ir = base.net
        result.patched_net_ir = patched.net
        result.deterministic = base.deterministic and patched.deterministic
        result.fingerprint = asdict(base.fingerprint)

        if base.net <= 0:
            result.outcome = Outcome.UNMEASURABLE
            result.detail = "the workload does no measurable work"
            return result

        result.work_reduction = (base.net - patched.net) / base.net

        equivalent = computes_same_answer(prepared, prepared.trees.patched)
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
