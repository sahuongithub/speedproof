"""Comparing the agent against the baseline the brief sanctions.

The baseline is one prompt with basic instructions, which is the first of the
four the hackathon brief allows. It sees the same code, is asked for the same
thing, and is measured by the same harness on the same cases. What it does not
get is the loop: no profile, no measured feedback, no second attempt.

Both are scored on the same three questions, in the order that matters:
does it still compute the right answers, does it do less work, and did the
harness reach that verdict without the agent's help.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from speedproof.speedagent.agent import (
    BASELINE_PROMPT,
    AgentError,
    Attempt,
    Trajectory,
    ask,
    extract_source,
    optimise,
)
from speedproof.verifyperf.callgrind import MeasurementError, measure, probe_environment

TASKS = ("group_totals", "prefix_search", "running_stats")


@dataclass
class Comparison:
    """What each approach achieved on one task."""

    task: str
    baseline_ir: int
    one_shot_ir: int | None = None
    one_shot_correct: bool | None = None
    agent_ir: int | None = None
    agent_rounds: int = 0
    trajectory: dict | None = None

    def _reduction(self, value: int | None) -> float | None:
        if value is None or self.baseline_ir <= 0:
            return None
        return (self.baseline_ir - value) / self.baseline_ir

    @property
    def one_shot_reduction(self) -> float | None:
        return self._reduction(self.one_shot_ir)

    @property
    def agent_reduction(self) -> float | None:
        return self._reduction(self.agent_ir)

    def line(self) -> str:
        def pct(v):
            return f"{v:+7.1%}" if v is not None else "      -"
        note = "" if self.one_shot_correct is not False else "  (one-shot broke it)"
        return (
            f"  {self.task:16s} {self.baseline_ir:>12,}"
            f" {pct(self.one_shot_reduction)} {pct(self.agent_reduction)}{note}"
        )


@dataclass
class Results:
    comparisons: list[Comparison] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"  {'task':16s} {'starting Ir':>12} {'one-shot':>8} {'agent':>8}",
            "  " + "-" * 48,
        ]
        lines += [c.line() for c in self.comparisons]
        got = [c for c in self.comparisons if c.agent_reduction is not None]
        one = [c for c in self.comparisons if c.one_shot_reduction is not None]
        if got:
            lines.append("")
            lines.append(
                f"  mean work removed: one-shot "
                f"{sum(c.one_shot_reduction for c in one)/len(one):+.1%}"
                if one else "  one-shot: nothing measurable"
            )
            lines.append(
                f"                     agent    "
                f"{sum(c.agent_reduction for c in got)/len(got):+.1%}"
            )
        broke = [c for c in self.comparisons if c.one_shot_correct is False]
        if broke:
            lines.append(
                f"\n  the one-shot baseline changed the answers on "
                f"{len(broke)} of {len(self.comparisons)} tasks; the harness "
                f"rejected those rather than scoring them"
            )
        return "\n".join(lines)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "tasks": [
                {
                    "task": c.task,
                    "baseline_ir": c.baseline_ir,
                    "one_shot_ir": c.one_shot_ir,
                    "one_shot_correct": c.one_shot_correct,
                    "one_shot_reduction": c.one_shot_reduction,
                    "agent_ir": c.agent_ir,
                    "agent_reduction": c.agent_reduction,
                    "agent_rounds": c.agent_rounds,
                }
                for c in self.comparisons
            ]
        }, indent=1) + "\n")


def run_one_shot(workspace, source_file, baseline_file, fingerprint, reference):
    """The sanctioned baseline: one prompt, no loop, no feedback."""
    from speedproof.verifyperf.verify import _capture

    original = (workspace / source_file).read_text()
    try:
        reply = ask(BASELINE_PROMPT.format(source=original))
    except AgentError:
        return None, None
    candidate = extract_source(reply)
    if not candidate:
        return None, None
    (workspace / source_file).write_text(candidate)
    try:
        digest = _capture(workspace, source_file, "checksum")
        correct = digest == reference
        if not correct:
            return None, False
        result = measure(workspace, source_file, repetitions=2,
                         fingerprint=fingerprint, baseline=baseline_file)
        return result.net, True
    except MeasurementError:
        return None, None
    finally:
        (workspace / source_file).write_text(original)
