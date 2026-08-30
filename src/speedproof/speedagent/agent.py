"""An agent that optimises code, and cannot mark its own work.

The agent proposes a patch. It never measures one. Every number it is given
comes from the harness, computed in a container the agent has no access to,
and the verdict on its work is reached the same way. That separation is the
whole design: an agent scored on a number it can reach will eventually reach
for the number instead of the problem, and the published record of these
benchmarks is largely a record of that happening.

The loop is deliberately small, and each part of it earns its place from a
measured result rather than from plausibility:

* The **profiler runs in the harness**, never in the prompt. Instructing a
  model to profile scores below not mentioning profiling at all; running the
  profiler and handing over what it found is worth about fifteen points.
* The agent sees **instructions retired**, not seconds. The measurement is
  deterministic, so a difference between two attempts is a difference in the
  work done and never in the weather.
* The **best attempt is kept, not the last**. Agents routinely reach a good
  result and then spoil it.
* An attempt that changes the answers is **rejected before it is timed**,
  because a faster wrong answer is not an optimisation and there is nothing to
  learn from how fast it was.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from speedproof.verifyperf.callgrind import MeasurementError, measure
from speedproof.verifyperf.fingerprint import Fingerprint

_FENCE = re.compile(r"```(?:python|diff)?\n(.*?)```", re.S)


class AgentError(Exception):
    """Raised when the model could not be reached or understood."""


@dataclass
class Attempt:
    """One proposed optimisation and what the harness made of it."""

    round: int
    source: str
    net_ir: int | None = None
    equivalent: bool | None = None
    rejected_because: str | None = None

    @property
    def accepted(self) -> bool:
        return self.net_ir is not None and self.rejected_because is None


@dataclass
class Trajectory:
    """Everything the agent did, in the order it did it.

    Written out whole. A submission that reports only the best attempt is
    reporting a selection, and the attempts that failed are where the
    behaviour actually shows.
    """

    task: str
    baseline_ir: int
    attempts: list[Attempt] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)

    @property
    def best(self) -> Attempt | None:
        accepted = [a for a in self.attempts if a.accepted]
        return min(accepted, key=lambda a: a.net_ir) if accepted else None

    @property
    def improvement(self) -> float:
        best = self.best
        if best is None or self.baseline_ir <= 0:
            return 0.0
        return (self.baseline_ir - best.net_ir) / self.baseline_ir

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "baseline_ir": self.baseline_ir,
            "improvement": round(self.improvement, 6),
            "rounds": len(self.attempts),
            "attempts": [
                {
                    "round": a.round,
                    "net_ir": a.net_ir,
                    "equivalent": a.equivalent,
                    "rejected_because": a.rejected_because,
                    "accepted": a.accepted,
                }
                for a in self.attempts
            ],
            "messages": self.messages,
        }


def ask(prompt: str, timeout: int = 600) -> str:
    """Put one question to the model and return its answer."""
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json"],
        input=prompt.encode(),
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise AgentError(proc.stderr.decode(errors="replace")[-400:])
    try:
        payload = json.loads(proc.stdout.decode())
    except json.JSONDecodeError as exc:
        raise AgentError(f"could not read the model's reply: {exc}") from exc
    return payload.get("result") or payload.get("content") or ""


def extract_source(reply: str) -> str | None:
    """Take the code out of a reply, if there is any."""
    blocks = _FENCE.findall(reply)
    return blocks[-1].strip() if blocks else None


BASELINE_PROMPT = """\
Here is a Python module. Rewrite it so that it does less work, while computing
exactly the same results.

```python
{source}
```

Reply with the complete rewritten module in a single Python code block.
"""

AGENT_PROMPT = """\
You are optimising one Python module. It is measured by counting the machine
instructions it retires, so the only thing that helps is doing less work.

```python
{source}
```
{profile}{history}
Rules that the measurement enforces, so working around them is not possible:

* The results must be identical. They are compared by hashing a canonical
  encoding of what the module returns, computed outside your reach, so an
  approximation or a changed dtype will be rejected rather than scored.
* Caching across calls does not help. Each measurement runs in a fresh process.
* Deferring work does not help. The result is fully materialised inside the
  measured region.
* The measurement is deterministic, so there is no noise to exploit and no
  benefit in trying again unchanged.

Reply with the complete rewritten module in a single Python code block.
"""


def _profile_section(profile: str | None) -> str:
    if not profile:
        return ""
    return (
        "\nThe harness profiled the current version. These are the functions "
        "where the instructions go:\n\n```\n" + profile.strip() + "\n```\n"
    )


def _history_section(trajectory: Trajectory) -> str:
    if not trajectory.attempts:
        return ""
    lines = [
        "\nWhat has been tried already, measured by the harness "
        f"(the starting point was {trajectory.baseline_ir:,} instructions):\n"
    ]
    for attempt in trajectory.attempts:
        if attempt.rejected_because:
            lines.append(f"* attempt {attempt.round}: rejected, {attempt.rejected_because}")
        else:
            delta = (trajectory.baseline_ir - attempt.net_ir) / trajectory.baseline_ir
            lines.append(
                f"* attempt {attempt.round}: {attempt.net_ir:,} instructions "
                f"({delta:+.1%})"
            )
    lines.append("")
    return "\n".join(lines)


def optimise(
    workspace: Path,
    source_file: Path,
    baseline_file: Path,
    task: str,
    rounds: int = 3,
    profile: str | None = None,
    image: str | None = None,
    fingerprint: Fingerprint | None = None,
    reference_checksum: str | None = None,
    use_profile: bool = True,
    use_history: bool = True,
) -> Trajectory:
    """Run the loop, measuring every attempt from outside it.

    ``use_profile`` and ``use_history`` exist so the loop can be run with parts
    removed. A design that has not been measured against itself without each
    part is a design nobody has tested.
    """
    from speedproof.verifyperf.verify import _capture

    original = (workspace / source_file).read_text()
    base = measure(workspace, source_file, repetitions=2,
                   fingerprint=fingerprint, image=image, baseline=baseline_file)
    trajectory = Trajectory(task=task, baseline_ir=base.net)

    for round_number in range(1, rounds + 1):
        prompt = AGENT_PROMPT.format(
            source=original,
            profile=_profile_section(profile) if use_profile else "",
            history=_history_section(trajectory) if use_history else "",
        )
        try:
            reply = ask(prompt)
        except AgentError as exc:
            trajectory.attempts.append(
                Attempt(round_number, "", rejected_because=f"model unavailable: {exc}")
            )
            break

        trajectory.messages.append(
            {"round": round_number, "prompt": prompt, "reply": reply}
        )
        candidate = extract_source(reply)
        attempt = Attempt(round_number, candidate or "")
        if not candidate:
            attempt.rejected_because = "the reply contained no code"
            trajectory.attempts.append(attempt)
            continue

        (workspace / source_file).write_text(candidate)
        try:
            # Correctness first: a faster wrong answer is not an optimisation,
            # and there is nothing to learn from how fast it was.
            if reference_checksum is not None:
                digest = _capture(workspace, source_file, "checksum")
                attempt.equivalent = digest == reference_checksum
                if not attempt.equivalent:
                    attempt.rejected_because = "it computes different results"
                    trajectory.attempts.append(attempt)
                    continue
            result = measure(workspace, source_file, repetitions=2,
                             fingerprint=fingerprint, image=image,
                             baseline=baseline_file)
            attempt.net_ir = result.net
        except MeasurementError as exc:
            attempt.rejected_because = f"it did not run: {str(exc).splitlines()[0][:70]}"
        finally:
            (workspace / source_file).write_text(original)
        trajectory.attempts.append(attempt)

    best = trajectory.best
    if best is not None:
        (workspace / source_file).write_text(best.source)
    return trajectory
