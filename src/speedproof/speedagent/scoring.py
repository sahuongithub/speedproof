"""Scoring an arm against the maintainer who did the work first.

The obvious score is whether an arm beat some threshold, and with a corpus this
size it is unusable. Simulating the paired test that a binary outcome requires:
at ten tasks, against a true effect where one arm wins outright on 30% of tasks
and the other on 5%, the chance of detecting it is **0.04**. At twenty it is
0.32. Nothing about running the experiment more carefully rescues a design
where the answer is a coin flip.

So the score is continuous, and it is expressed against the human's own patch:

    expert_fraction = log(base / arm) / log(base / human)

the share of the maintainer's instruction reduction that an arm achieved, on a
log scale so that halving the work and halving it again count equally. One is
parity with the person who knew the codebase. Above one is better than they
did, which happens and is worth seeing rather than clipping away.

The log matters. A ratio of ratios on the raw counts would let one task where
the agent found a fifty-fold win dominate a corpus where it usually finds
nothing, and the headline would then describe that one task.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

#: An arm may be credited with at most this multiple of the expert's reduction.
#: Not to hide the result -- an arm that beats the expert is reported as
#: beating them -- but so that a single extraordinary task cannot carry a mean
#: over twenty ordinary ones.
CREDIT_CAP = 2.0


@dataclass(frozen=True)
class TaskScore:
    """One arm's result on one task, relative to the maintainer's own patch."""

    task: str
    repo: str
    base_ir: int
    human_ir: int | None
    arm_ir: int | None
    rejected: str | None = None

    @property
    def measurable(self) -> bool:
        """Whether the maintainer's patch removed enough work to score against.

        A task where the expert's own change is immeasurably small cannot say
        anything about an arm: the denominator would be near zero and the score
        meaningless in either direction.
        """
        return (
            self.human_ir is not None
            and self.base_ir > 0
            and self.human_ir > 0
            and self.human_ir < self.base_ir
        )

    @property
    def expert_fraction(self) -> float | None:
        """Share of the expert's log reduction this arm achieved."""
        if not self.measurable:
            return None
        if self.arm_ir is None or self.arm_ir <= 0:
            return 0.0
        expert = math.log(self.base_ir / self.human_ir)
        achieved = math.log(self.base_ir / self.arm_ir)
        return min(achieved / expert, CREDIT_CAP)

    @property
    def reached_parity(self) -> bool:
        fraction = self.expert_fraction
        return fraction is not None and fraction >= 1.0


@dataclass
class ArmResult:
    """One arm across the corpus."""

    name: str
    scores: list[TaskScore] = field(default_factory=list)

    @property
    def scored(self) -> list[TaskScore]:
        return [s for s in self.scores if s.expert_fraction is not None]

    @property
    def mean_fraction(self) -> float | None:
        values = [s.expert_fraction for s in self.scored]
        return statistics.fmean(values) if values else None

    @property
    def parity_count(self) -> int:
        return sum(1 for s in self.scored if s.reached_parity)

    def line(self) -> str:
        mean = self.mean_fraction
        return (
            f"  {self.name:12s} "
            f"{'-' if mean is None else f'{mean:6.1%}':>7} of the expert's "
            f"reduction   parity on {self.parity_count}/{len(self.scored)}"
        )


def paired_difference(a: ArmResult, b: ArmResult) -> list[tuple[str, str, float]]:
    """Per-task difference between two arms, on the tasks both scored.

    Pairing is not a nicety. The arms see the same tasks, the same trees and
    the same model, so their scores are strongly correlated, and comparing
    unpaired means throws that correlation away and widens the interval for
    nothing.
    """
    by_task = {s.task: s for s in b.scored}
    out = []
    for score in a.scored:
        other = by_task.get(score.task)
        if other is not None:
            out.append(
                (score.task, score.repo, score.expert_fraction - other.expert_fraction)
            )
    return out


def clustered_standard_error(
    differences: list[tuple[str, str, float]]
) -> float | None:
    """Standard error of the mean paired difference, clustered by repository.

    Tasks from one project are not independent draws: they share a build, a
    house style and often the same hot loops. Treating them as independent has
    been measured to understate the error by more than threefold, which turns a
    result that is not there into one that appears to be.
    """
    if len(differences) < 2:
        return None
    values = [d for _, _, d in differences]
    mean = statistics.fmean(values)

    by_repo: dict[str, list[float]] = {}
    for _, repo, value in differences:
        by_repo.setdefault(repo, []).append(value)

    total = 0.0
    for cluster in by_repo.values():
        residual = sum(value - mean for value in cluster)
        total += residual * residual
    n = len(values)
    return math.sqrt(total) / n if total > 0 else 0.0


def minimum_detectable_effect(
    differences: list[tuple[str, str, float]]
) -> float | None:
    """The smallest paired difference this corpus could show, at 80% power.

    Reported alongside the result rather than after it. A corpus that cannot
    resolve the difference an arm claims has not failed to find it; it was
    never able to.
    """
    if len(differences) < 2:
        return None
    values = [d for _, _, d in differences]
    spread = statistics.stdev(values)
    return 2.80 * spread / math.sqrt(len(values))
