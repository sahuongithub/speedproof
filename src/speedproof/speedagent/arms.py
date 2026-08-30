"""Running each way of answering a task, on identical terms.

A task is prepared once -- checked out, built, profiled, its workload chosen --
and then several arms answer it. Everything that could differ between them
other than the thing being compared is held fixed by construction rather than
by discipline: the same tree, the same workload, the same oracle, the same
model, and the same brief on the first turn.

That last one is not a detail. The surveyed literature reports self-correction
results being inflated by giving the iterating arm a better prompt than the
baseline it is compared against, so the loop's first turn and the one-shot arm
are the same text, produced by the same function. If the loop wins, it wins
because it iterated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from speedproof.corpus.variants import Prepared, measure_tree
from speedproof.speedagent.controller import ModelUnavailable, ask
from speedproof.speedagent.controller import run as run_loop
from speedproof.speedagent.judge import TaskJudge
from speedproof.speedagent.loop import (
    EditError,
    Trajectory,
    apply_edits,
    build_prompt,
    parse_edits,
)
from speedproof.speedagent.profile import Profile
from speedproof.speedagent.workspace import Workspace, WorkspaceError


#: The arms, and what each one isolates.
#:
#: Four arms cannot answer the question. Comparing a loop that sees a profile
#: against a single prompt that does not confounds iterating with being told
#: where the work is, and the two genuinely dissociate: in the surveyed
#: ablation, giving a non-iterating agent profiler access *lowered* its score,
#: from 20.6 to 17.6, while the same profile inside a loop raised it to 36.3.
#:
#: ``base``              the code as it stood, which every score is relative to
#: ``human``             the maintainer's own patch, the target
#: ``one_shot``          one prompt, no profile, no feedback
#: ``one_shot_profile``  one prompt with the profile, isolating the profile
#: ``best_of``           several independent one-shots, the best kept
#: ``agent_no_profile``  the loop with only the measurement fed back
#: ``agent``             the loop with the profile as well
ARMS = (
    "base",
    "human",
    "one_shot",
    "one_shot_profile",
    "best_of",
    "agent_no_profile",
    "agent",
)


@dataclass
class ArmRun:
    """What one arm achieved on one task, and what it cost to find out."""

    arm: str
    net_ir: int | None = None
    rejected: str | None = None
    model_calls: int = 0
    measurements: int = 0
    rounds: int = 0
    patch: str = ""
    trajectory: dict | None = None

    @property
    def produced_something(self) -> bool:
        return self.net_ir is not None


def _target_file(prepared: Prepared) -> str | None:
    """The file an arm is asked to change.

    The maintainer's patch names it. Where a patch touches several files the
    first is used and the rest are left alone, which understates what an arm
    could do and is the conservative direction: an arm that is not allowed to
    change a file cannot be credited for changing it.
    """
    return prepared.changed_files[0] if prepared.changed_files else None


def run_one_shot(
    prepared: Prepared,
    judge: TaskJudge,
    profile: Profile | None = None,
    ask_model=ask,
    name: str | None = None,
) -> ArmRun:
    """One prompt, no loop, no feedback. The first baseline the brief allows.

    Run twice: once without the profile and once with it. The pair isolates
    what the profile is worth to an agent that cannot iterate, which is not the
    same as what it is worth inside a loop and has been measured to differ in
    sign.
    """
    result = ArmRun(arm=name or ("one_shot_profile" if profile else "one_shot"))
    target = _target_file(prepared)
    if target is None:
        result.rejected = "the task names no file to change"
        return result

    with Workspace.clone(prepared.trees.base) as workspace:
        prompt = build_prompt(
            source=workspace.read(target), path=target, profile=profile
        )
        try:
            reply = ask_model(prompt)
        except ModelUnavailable as exc:
            result.rejected = f"the model was unavailable: {exc}"
            return result
        result.model_calls = 1

        try:
            apply_edits(workspace, target, parse_edits(reply))
        except (EditError, WorkspaceError) as exc:
            result.rejected = str(exc).splitlines()[0][:90]
            result.trajectory = {
                "arm": result.arm,
                "exchanges": [{"round": 1, "prompt": prompt, "reply": reply}],
                "rounds": [{"round": 1, "rejected": result.rejected}],
                "stopped_because": result.rejected,
            }
            return result

        result.patch = workspace.diff()
        verdict = judge(workspace)
        result.measurements = 1
        result.net_ir = verdict.net_ir
        result.rejected = verdict.rejected
        result.trajectory = {
            "arm": result.arm,
            "exchanges": [{"round": 1, "prompt": prompt, "reply": reply}],
            "rounds": [{
                "round": 1,
                "patch": result.patch,
                "net_ir": verdict.net_ir,
                "import_cost": verdict.import_cost,
                "equivalent": verdict.equivalent,
                "rejected": verdict.rejected,
            }],
            "stopped_because": "one attempt, by design",
        }
    return result


def run_agent(
    prepared: Prepared,
    judge: TaskJudge,
    profile: Profile | None = None,
    rounds: int = 5,
    use_profile: bool = True,
    use_history: bool = True,
    ask_model=ask,
) -> ArmRun:
    """The loop."""
    result = ArmRun(arm="agent" if use_profile else "agent_no_profile")
    target = _target_file(prepared)
    if target is None:
        result.rejected = "the task names no file to change"
        return result

    base_net = judge.baseline_net
    with Workspace.clone(prepared.trees.base) as workspace:
        trajectory: Trajectory = run_loop(
            workspace,
            target,
            judge=judge,
            task=prepared.task.task_id,
            baseline_ir=base_net,
            profile=profile,
            rounds=rounds,
            use_profile=use_profile,
            use_history=use_history,
            ask_model=ask_model,
        )
        best = trajectory.best
        result.rounds = len(trajectory.rounds)
        result.model_calls = len(trajectory.exchanges)
        result.measurements = judge.measurements
        result.trajectory = trajectory.to_dict()
        if best is None:
            result.rejected = trajectory.stopped_because or "no attempt was accepted"
        else:
            result.net_ir = best.net_ir
            result.patch = best.patch
    return result


def run_best_of(
    prepared: Prepared,
    judge: TaskJudge,
    attempts: int,
    profile: Profile | None = None,
    ask_model=ask,
) -> ArmRun:
    """Independent one-shot attempts, the best of them kept.

    The control that decides whether the loop is feedback or merely compute. It
    gets the same number of model calls the loop is allowed, the same brief and
    the same profile -- withholding any of those would confound the comparison
    with the thing being tested.

    It is chosen by the oracle, which is more than the loop gets: the loop must
    decide what to keep from measurements it has already spent its budget on,
    while this arm sees every attempt scored before choosing. That asymmetry
    favours the control, and it is left in place deliberately. A loop that
    beats a control given an advantage has beaten it clearly.
    """
    result = ArmRun(arm=f"best_of_{attempts}")
    target = _target_file(prepared)
    if target is None:
        result.rejected = "the task names no file to change"
        return result

    exchanges = []
    attempts_made: list[dict] = []
    scored: list[tuple[int, str, str]] = []
    for attempt in range(1, attempts + 1):
        with Workspace.clone(prepared.trees.base) as workspace:
            prompt = build_prompt(
                source=workspace.read(target), path=target, profile=profile
            )
            try:
                reply = ask_model(prompt)
            except ModelUnavailable:
                break
            result.model_calls += 1
            exchanges.append({"round": attempt, "prompt": prompt, "reply": reply})

            try:
                apply_edits(workspace, target, parse_edits(reply))
            except (EditError, WorkspaceError):
                continue

            patch = workspace.diff()
            verdict = judge(workspace)
            result.measurements += 1
            attempts_made.append({
                "round": attempt, "patch": patch, "net_ir": verdict.net_ir,
                "import_cost": verdict.import_cost,
                "equivalent": verdict.equivalent, "rejected": verdict.rejected,
            })
            if verdict.net_ir is not None and verdict.rejected is None:
                scored.append((verdict.net_ir, patch, reply))

    result.trajectory = {
        "arm": result.arm,
        "exchanges": exchanges,
        "rounds": attempts_made,
        "stopped_because": f"{len(exchanges)} independent attempts, by design",
    }
    if not scored:
        result.rejected = "no attempt was accepted"
        return result
    best_ir, best_patch, _ = min(scored, key=lambda item: item[0])
    result.net_ir = best_ir
    result.patch = best_patch
    return result
