"""Run the demonstration: five attempted optimisations, judged twice."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speedproof.hackguard")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--no-colour", action="store_true")
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(),
        help="the checkout to write the cases into",
    )
    args = parser.parse_args(argv)

    from speedproof.hackguard.demo import CASES_DIR, render, run_demo
    from speedproof.verifyperf.callgrind import measure, probe_environment

    workspace = args.repo.resolve()
    colour = sys.stdout.isatty() and not args.no_colour

    outcomes = run_demo(workspace, repetitions=args.repetitions)
    honest = measure(
        workspace, CASES_DIR / "honest.py", repetitions=args.repetitions,
        fingerprint=probe_environment(workspace),
        baseline=CASES_DIR / "honest_baseline.py",
    )
    print(render(outcomes, honest.net, colour=colour))
    return 0 if all(o.correct for o in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
