"""Run every arm over a corpus and report what it shows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from speedproof.corpus.checkout import CheckoutError, release
from speedproof.corpus.task import Task, load_tasks
from speedproof.corpus.variants import (
    GroundTruthFailed,
    NotPreparable,
    Prepared,
    measure_tree,
    prepare,
)
from speedproof.speedagent.arms import run_agent, run_best_of, run_one_shot
from speedproof.speedagent.evaluate import Report
from speedproof.speedagent.judge import TaskJudge
from speedproof.speedagent.scoring import TaskScore
from speedproof.speedagent.trajectory import TrajectoryRecord
from speedproof.verifyperf.callgrind import MeasurementError, ensure_image

#: Dependencies each project needs in the measurement image, pinned here so an
#: instruction count stays attributable to the code rather than to a dependency
#: that moved underneath it.
PROJECT_DEPENDENCIES = {
    "pypa/packaging": (),
    "sympy/sympy": ("mpmath",),
    "networkx/networkx": (),
    "xdslproject/xdsl": (
        "immutabledict<4.2.2", "typing-extensions>=4.7,<5", "ordered-set==4.1.0",
    ),
    "pandas-dev/pandas": (
        "meson-python>=0.19,<1", "meson>=1.2.3,<2", "ninja", "wheel",
        "Cython>3.1.0,<4", "numpy>=2.0", "versioneer[toml]",
        "python-dateutil", "pytz",
    ),
}


def _record_for(prepared: Prepared, arm: str, baseline_ir: int,
                expert_ir: int | None, config: dict) -> TrajectoryRecord:
    return TrajectoryRecord(
        task_id=prepared.task.task_id,
        repo=prepared.task.repo,
        arm=arm,
        base_commit=prepared.task.base_sha,
        workload=prepared.benchmark.name,
        baseline_ir=baseline_ir,
        expert_ir=expert_ir,
        selection_rule=(
            "lowest measured instruction count among rounds whose answers "
            "matched the base tree"
        ),
        config=config,
    )


def evaluate_task(
    task: Task,
    cache: Path,
    workspace: Path,
    report: Report,
    trajectories: Path,
    rounds: int,
    repetitions: int,
    image: str | None,
    arms: tuple[str, ...],
) -> str:
    """Run the requested arms on one task and record what each achieved."""
    try:
        prepared = prepare(task, cache, workspace, image=image)
    except GroundTruthFailed as exc:
        return "ground_truth_failed"
    except NotPreparable as exc:
        return exc.outcome
    except (CheckoutError, MeasurementError) as exc:
        return "unmeasurable"

    base = measure_tree(prepared, prepared.trees.base, repetitions)
    human = measure_tree(prepared, prepared.trees.patched, repetitions)
    if base.net <= 0 or human.net >= base.net:
        # The maintainer's own patch removed nothing measurable here, so the
        # task cannot say anything about any arm: the denominator every score
        # divides by would be zero or negative.
        return "expert_effect_too_small"

    config = {"rounds": rounds, "repetitions": repetitions}
    profile = prepared.profile

    def score_of(net_ir: int | None) -> TaskScore:
        return TaskScore(
            task=task.task_id, repo=task.repo,
            base_ir=base.net, human_ir=human.net, arm_ir=net_ir,
        )

    def judge_for() -> TaskJudge:
        return TaskJudge(
            prepared=prepared,
            baseline_net=base.net,
            baseline_import=base.import_cost,
            repetitions=repetitions,
        )

    runs = []
    if "one_shot" in arms:
        runs.append(run_one_shot(prepared, judge_for(), profile=None))
    if "one_shot_profile" in arms:
        runs.append(run_one_shot(prepared, judge_for(), profile=profile))
    if "best_of" in arms:
        runs.append(run_best_of(prepared, judge_for(), attempts=rounds,
                                profile=profile))
    for arm, with_profile in (("agent_no_profile", False), ("agent", True)):
        if arm not in arms:
            continue
        judge = judge_for()
        record = _record_for(prepared, arm, base.net, human.net, config)
        run = run_agent(
            prepared, judge, profile=profile if with_profile else None,
            rounds=rounds, use_profile=with_profile,
        )
        if run.trajectory:
            record.rounds = record.rounds or []
        runs.append(run)

    for run in runs:
        report.record(run.arm, score_of(run.net_ir))
        if run.trajectory is not None:
            _write_trajectory(trajectories, prepared, run, base.net, human.net,
                              config)

    return "scored"


def _write_trajectory(directory, prepared, run, baseline_ir, expert_ir, config):
    """Save whatever the arm produced, including when it produced nothing."""
    from speedproof.speedagent.trajectory import RoundRecord

    record = _record_for(prepared, run.arm, baseline_ir, expert_ir, config)
    record.model_calls = run.model_calls
    record.measurements = run.measurements
    for index, exchange in enumerate(run.trajectory.get("exchanges", []), start=1):
        record.rounds.append(
            RoundRecord(
                round=exchange.get("round", index),
                prompt=exchange.get("prompt", ""),
                reply=exchange.get("reply", ""),
            )
        )
    for entry, detail in zip(record.rounds, run.trajectory.get("rounds", [])):
        entry.net_ir = detail.get("net_ir")
        entry.import_cost = detail.get("import_cost")
        entry.equivalent = detail.get("equivalent")
        entry.rejected = detail.get("rejected")
        entry.patch = detail.get("patch", "")
    record.close(
        stopped_because=run.trajectory.get("stopped_because")
        or run.rejected
        or "",
        selected_round=None,
    )
    if run.net_ir is not None:
        for entry in record.rounds:
            if entry.net_ir == run.net_ir:
                record.close(record.stopped_because, entry.round)
                break
    record.write(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speedagent")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--task", action="append")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument(
        "--arm", action="append",
        help="run only these arms; defaults to all six",
    )
    parser.add_argument("--out", type=Path, default=Path("eval/agent-results.json"))
    parser.add_argument("--trajectories", type=Path, default=Path("eval/trajectories"))
    args = parser.parse_args(argv)

    tasks = load_tasks(args.manifest)
    if args.task:
        wanted = set(args.task)
        tasks = [t for t in tasks if t.task_id in wanted]
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 1

    arms = tuple(args.arm) if args.arm else (
        "one_shot", "one_shot_profile", "best_of", "agent_no_profile", "agent"
    )
    repo = tasks[0].repo
    image = ensure_image(
        dependencies=PROJECT_DEPENDENCIES.get(repo, ()),
        tag=f"speedproof/measure-{repo.split('/')[-1]}:0.1.0",
    )
    cache = Path("corpus/repos").resolve()
    workspace = Path("corpus/work").resolve()

    print(f"{len(tasks)} task(s) from {repo}", file=sys.stderr)
    print(f"arms: {', '.join(arms)}\n", file=sys.stderr)

    report = Report()
    for index, task in enumerate(tasks, 1):
        outcome = evaluate_task(
            task, cache, workspace, report, args.trajectories,
            rounds=args.rounds, repetitions=args.repetitions,
            image=image, arms=arms,
        )
        if outcome != "scored":
            report.dropped[outcome] = report.dropped.get(outcome, 0) + 1
        print(f"[{index}/{len(tasks)}] {task.task_id}: {outcome}", flush=True)
        release(task, workspace / task.slug, cache)

    print()
    print(report.summary())
    report.write(args.out)
    print(f"\nwrote {args.out} and {args.trajectories}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
