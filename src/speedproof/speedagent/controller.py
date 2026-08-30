"""Driving the loop, and deciding when it is finished.

The agent never decides. Three quarters of trajectories in the surveyed work
stop early with budget still available, and a model that has secured a
measurable win tends to stop rather than push for a larger one, so the stopping
rule lives here.

Nothing the agent produces is trusted further than a patch. It cannot measure,
cannot see whether its answer matched, and cannot reach the tree its work is
judged in -- it writes into a hard-linked copy and the harness reads the copy.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from speedproof.speedagent.loop import (
    PATIENCE,
    ROUNDS,
    EditError,
    Round,
    Trajectory,
    apply_edits,
    build_prompt,
    parse_edits,
    patch_fingerprint,
)
from speedproof.speedagent.profile import Profile
from speedproof.speedagent.trajectory import RoundRecord, TrajectoryRecord
from speedproof.speedagent.workspace import Workspace, WorkspaceError


class ModelUnavailable(Exception):
    """Raised when the model could not be reached or its reply not read."""


def ask(prompt: str, timeout: int = 900) -> str:
    """Put one question to the model."""
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json"],
        input=prompt.encode(),
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise ModelUnavailable(proc.stderr.decode(errors="replace")[-300:])
    try:
        payload = json.loads(proc.stdout.decode())
    except json.JSONDecodeError as exc:
        raise ModelUnavailable(f"the reply was not readable: {exc}") from exc
    reply = payload.get("result") or payload.get("content") or ""
    if not reply:
        raise ModelUnavailable("the reply was empty")
    return reply


@dataclass
class Judgement:
    """What the harness made of one attempt."""

    net_ir: int | None = None
    import_cost: int | None = None
    equivalent: bool | None = None
    rejected: str | None = None


def run(
    workspace: Workspace,
    target: Path | str,
    judge,
    task: str,
    baseline_ir: int,
    profile: Profile | None = None,
    rounds: int = ROUNDS,
    patience: int = PATIENCE,
    use_profile: bool = True,
    use_history: bool = True,
    ask_model=ask,
    record: TrajectoryRecord | None = None,
) -> Trajectory:
    """Iterate on one file until the controller decides to stop.

    ``judge`` takes the workspace and returns a Judgement. It is passed in so
    the loop cannot measure anything itself, and so the ablations can hold
    everything else fixed.

    ``record``, when given, is filled in as the run proceeds rather than
    assembled from it afterwards. The convention for publishing these requires
    that, and it is also the only way the record survives a run that ends
    badly: a reconstruction needs the run to have finished.
    """
    original = workspace.read(target)
    trajectory = Trajectory(task=task, baseline_ir=baseline_ir)
    seen: set[str] = set()
    barren = 0

    for number in range(1, rounds + 1):
        prompt = build_prompt(
            source=workspace.read(target),
            path=str(target),
            profile=profile if use_profile else None,
            trajectory=trajectory if use_history else None,
        )
        try:
            reply = ask_model(prompt)
        except ModelUnavailable as exc:
            trajectory.stopped_because = f"the model was unavailable: {exc}"
            break
        trajectory.exchanges.append(
            {"round": number, "prompt": prompt, "reply": reply}
        )
        entry = RoundRecord(
            round=number, prompt=prompt, reply=reply,
            profile_shown=bool(use_profile and profile and not profile.empty),
            history_shown=bool(use_history and trajectory.rounds),
        )
        if record is not None:
            record.rounds.append(entry)
            record.model_calls += 1

        this_round = Round(number)
        edits = parse_edits(reply)
        this_round.edits = len(edits)

        try:
            apply_edits(workspace, target, edits)
        except (EditError, WorkspaceError) as exc:
            this_round.rejected = str(exc).splitlines()[0][:90]
            entry.edits_proposed = len(edits)
            entry.rejected = this_round.rejected
            trajectory.rounds.append(this_round)
            workspace.write(target, original)
            # A round that produced nothing usable is a round that did not
            # improve. Counting only measured rounds would let a run where
            # every reply is unusable continue to the limit, asking the model
            # the same question and getting the same answer.
            barren += 1
            if barren >= patience:
                trajectory.stopped_because = f"no improvement in {patience} rounds"
                break
            continue

        this_round.patch = workspace.diff()
        marker = patch_fingerprint(this_round.patch)
        if marker in seen:
            # Measuring a repeat costs a Valgrind run to learn what is known.
            this_round.rejected = "this attempt was already tried"
            entry.rejected = this_round.rejected
            entry.patch = this_round.patch
            trajectory.rounds.append(this_round)
            workspace.write(target, original)
            barren += 1
            if barren >= patience:
                trajectory.stopped_because = f"no improvement in {patience} rounds"
                break
            continue
        seen.add(marker)

        verdict = judge(workspace)
        this_round.net_ir = verdict.net_ir
        this_round.import_cost = verdict.import_cost
        this_round.equivalent = verdict.equivalent
        this_round.rejected = verdict.rejected

        entry.edits_proposed = len(edits)
        entry.patch = this_round.patch
        entry.net_ir = verdict.net_ir
        entry.import_cost = verdict.import_cost
        entry.equivalent = verdict.equivalent
        entry.rejected = verdict.rejected
        if record is not None:
            record.measurements += 1

        previous_best = trajectory.best
        trajectory.rounds.append(this_round)
        workspace.write(target, original)

        improved = (
            this_round.accepted
            and (previous_best is None or this_round.net_ir < previous_best.net_ir)
        )
        barren = 0 if improved else barren + 1
        if barren >= patience:
            trajectory.stopped_because = f"no improvement in {patience} rounds"
            break
    else:
        trajectory.stopped_because = f"reached the limit of {rounds} rounds"

    # Leave the workspace holding the best attempt rather than the last one,
    # which is the difference between reporting what the agent found and
    # reporting where it happened to finish.
    if record is not None:
        record.close(
            stopped_because=trajectory.stopped_because,
            selected_round=trajectory.best.number if trajectory.best else None,
        )

    best = trajectory.best
    if best is not None:
        winning_reply = next(
            e["reply"] for e in trajectory.exchanges if e["round"] == best.number
        )
        workspace.write(target, original)
        apply_edits(workspace, target, parse_edits(winning_reply))
    return trajectory
