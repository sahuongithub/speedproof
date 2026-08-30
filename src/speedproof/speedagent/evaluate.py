"""Running every arm over the corpus, and reporting what it shows.

The report is arranged so that a reader can tell whether the result means
anything before being told what it is. That order matters: the smallest
difference this corpus could have resolved is stated before the difference
actually observed, because a corpus that cannot resolve a difference has not
failed to find it -- it was never able to.

Arms are compared paired, on the tasks both scored, with the error clustered by
repository. Tasks mined from one project share a build, a house style and often
the same hot loops, so treating them as independent draws understates the error
by enough to turn a result that is not there into one that appears to be.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from speedproof.speedagent.scoring import (
    ArmResult,
    TaskScore,
    clustered_standard_error,
    minimum_detectable_effect,
    paired_difference,
)


@dataclass
class Comparison:
    """One arm against another, on the tasks both answered."""

    left: str
    right: str
    difference: float | None
    standard_error: float | None
    tasks: int
    repositories: int
    detectable: float | None

    @property
    def resolvable(self) -> bool:
        """Whether this corpus could have resolved a difference this size."""
        if self.difference is None or self.detectable is None:
            return False
        return abs(self.difference) >= self.detectable

    def line(self) -> str:
        if self.difference is None:
            return f"  {self.left} - {self.right}: no tasks in common"
        error = f" ± {self.standard_error:.3f}" if self.standard_error else ""
        verdict = "" if self.resolvable else "   (below what this corpus can resolve)"
        return (
            f"  {self.left} - {self.right}: {self.difference:+.3f}{error}"
            f"   n={self.tasks} in {self.repositories} repo(s){verdict}"
        )


@dataclass
class Report:
    """Every arm, every comparison, and what the corpus could have shown."""

    arms: dict[str, ArmResult] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)

    def record(self, arm: str, score: TaskScore) -> None:
        self.arms.setdefault(arm, ArmResult(arm)).scores.append(score)

    def compare(self, left: str, right: str) -> Comparison:
        a, b = self.arms.get(left), self.arms.get(right)
        if a is None or b is None:
            return Comparison(left, right, None, None, 0, 0, None)
        differences = paired_difference(a, b)
        if not differences:
            return Comparison(left, right, None, None, 0, 0, None)
        values = [d for _, _, d in differences]
        return Comparison(
            left=left,
            right=right,
            difference=sum(values) / len(values),
            standard_error=clustered_standard_error(differences),
            tasks=len(values),
            repositories=len({repo for _, repo, _ in differences}),
            detectable=minimum_detectable_effect(differences),
        )

    #: The comparisons the project exists to make, in the order they answer
    #: the question. The first says whether iterating helped at all; the second
    #: is the one that decides whether the loop is feedback or merely compute;
    #: the third and fourth say what the profile was worth in each setting.
    CONTRASTS = (
        ("agent", "one_shot"),
        ("agent", "best_of"),
        ("agent", "agent_no_profile"),
        ("one_shot_profile", "one_shot"),
        ("agent", "human"),
    )

    def summary(self) -> str:
        lines = ["Each arm, as a share of the maintainer's own reduction:", ""]
        for name in ("one_shot", "one_shot_profile", "best_of",
                     "agent_no_profile", "agent"):
            arm = self.arms.get(name)
            if arm and arm.scored:
                lines.append(arm.line())

        if self.dropped:
            lines.append("")
            lines.append("Tasks not scored:")
            for reason, count in sorted(self.dropped.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {reason:24s} {count:>3}")

        lines.append("")
        lines.append("Paired differences, clustered by repository:")
        lines.append("")
        for left, right in self.CONTRASTS:
            comparison = self.compare(left, right)
            if comparison.difference is not None:
                lines.append(comparison.line())

        lines.append("")
        lines.append(
            "A difference smaller than what the corpus can resolve is not "
            "evidence of no difference; it is evidence that this corpus was "
            "the wrong size to ask."
        )
        return "\n".join(lines)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "arms": {
                name: {
                    "mean_expert_fraction": arm.mean_fraction,
                    "reached_parity": arm.parity_count,
                    "scored": len(arm.scored),
                    "tasks": [
                        {
                            "task": s.task,
                            "repo": s.repo,
                            "base_ir": s.base_ir,
                            "human_ir": s.human_ir,
                            "arm_ir": s.arm_ir,
                            "expert_fraction": s.expert_fraction,
                            "rejected": s.rejected,
                        }
                        for s in arm.scores
                    ],
                }
                for name, arm in self.arms.items()
            },
            "dropped": self.dropped,
            "contrasts": [
                {
                    "left": c.left,
                    "right": c.right,
                    "difference": c.difference,
                    "standard_error": c.standard_error,
                    "tasks": c.tasks,
                    "repositories": c.repositories,
                    "minimum_detectable_effect": c.detectable,
                    "resolvable": c.resolvable,
                }
                for c in (self.compare(l, r) for l, r in self.CONTRASTS)
                if c.difference is not None
            ],
        }
        path.write_text(json.dumps(payload, indent=1) + "\n")
