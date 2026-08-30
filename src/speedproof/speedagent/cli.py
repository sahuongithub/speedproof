"""Run the baseline and the agent over the same tasks and report both."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from speedproof.speedagent.agent import optimise
from speedproof.speedagent.evaluate import (
    TASKS,
    Comparison,
    Results,
    run_one_shot,
)
from speedproof.verifyperf.callgrind import measure, probe_environment
from speedproof.verifyperf.verify import _capture

TASK_DIR = Path("corpus/agent")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speedagent")
    parser.add_argument("--task", action="append", help="run only these tasks")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("eval/agent-results.json"))
    parser.add_argument("--trajectories", type=Path, default=Path("eval/trajectories"))
    parser.add_argument("--no-profile", action="store_true",
                        help="withhold the profile, to measure what it is worth")
    parser.add_argument("--no-history", action="store_true",
                        help="withhold measured feedback, likewise")
    args = parser.parse_args(argv)

    workspace = Path.cwd()
    tasks = args.task or list(TASKS)
    fingerprint = probe_environment(workspace)
    print(f"environment {fingerprint}\n", file=sys.stderr)

    results = Results()
    for task in tasks:
        source = TASK_DIR / f"{task}.py"
        baseline_file = TASK_DIR / f"{task}_baseline.py"
        if not (workspace / source).is_file():
            print(f"  {task}: no such task", file=sys.stderr)
            continue

        reference = _capture(workspace, source, "checksum")
        start = measure(workspace, source, repetitions=2,
                        fingerprint=fingerprint, baseline=baseline_file)
        comparison = Comparison(task=task, baseline_ir=start.net)

        one_shot_ir, correct = run_one_shot(
            workspace, source, baseline_file, fingerprint, reference
        )
        comparison.one_shot_ir = one_shot_ir
        comparison.one_shot_correct = correct

        profile = None  # filled by the harness when a profile is available
        trajectory = optimise(
            workspace, source, baseline_file, task,
            rounds=args.rounds, profile=profile, fingerprint=fingerprint,
            reference_checksum=reference,
            use_profile=not args.no_profile,
            use_history=not args.no_history,
        )
        best = trajectory.best
        comparison.agent_ir = best.net_ir if best else None
        comparison.agent_rounds = len(trajectory.attempts)
        comparison.trajectory = trajectory.to_dict()
        results.comparisons.append(comparison)
        print(comparison.line(), flush=True)

        args.trajectories.mkdir(parents=True, exist_ok=True)
        (args.trajectories / f"{task}.json").write_text(
            json.dumps(trajectory.to_dict(), indent=1) + "\n"
        )

    print()
    print(results.summary())
    results.write(args.out)
    print(f"\nwrote {args.out} and {args.trajectories}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
