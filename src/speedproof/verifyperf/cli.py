"""Command line entry point.

Runs the declared comparisons and prints a report. With ``--json`` it writes a
machine-readable record instead, which is what continuous integration stores so
that results from different architectures can be checked against each other.
"""

from __future__ import annotations

import argparse
import json
import platform as _platform
import sys
from dataclasses import asdict
from pathlib import Path

from speedproof.verifyperf.verify import Variant, compare

#: The comparisons the project asserts. Each is a baseline, a candidate, and
#: the verdict that must come back; a run that disagrees with any of these is a
#: failure, whether it disagrees favourably or not.
SUITE = [
    (
        "honest algorithmic win",
        "corpus/examples/quadratic_concat.py",
        "corpus/examples/linear_sum.py",
        "improved",
    ),
    (
        "cheat: fast but wrong answer",
        "corpus/examples/linear_sum.py",
        "corpus/cheats/wrong_answer.py",
        "not_equivalent",
    ),
    (
        "cheat: cached across runs",
        "corpus/examples/linear_sum.py",
        "corpus/cheats/memoised_across_runs.py",
        "regressed",
    ),
    (
        "cheat: work deferred to a generator",
        "corpus/examples/list_squares.py",
        "corpus/cheats/deferred_work.py",
        "regressed",
    ),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speedproof")
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(), help="source tree to measure in"
    )
    parser.add_argument(
        "--platform",
        default=None,
        choices=["linux/arm64", "linux/amd64"],
        help="architecture to measure on; defaults to the host's",
    )
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--json", type=Path, help="write a machine-readable record here")
    parser.add_argument(
        "--skip-controls",
        action="store_true",
        help="do not validate the correctness gate first (not for CI)",
    )
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    records = []
    failures = 0

    print(f"speedproof  repo={repo}  host={_platform.machine()}", file=sys.stderr)

    # The gate is validated before it is used. A correctness check that has
    # never rejected anything is indistinguishable from no check, so the
    # controls run first and a failure here stops everything: any measurement
    # taken with an unvalidated gate is unsupported.
    control_record = None
    if not args.skip_controls:
        from speedproof.hackguard.controls import validate_gate

        report = validate_gate(repo, platform=args.platform)
        print(report.summary())
        control_record = {
            "soundness": report.soundness,
            "completeness": report.completeness,
            "passed": report.passed,
            "controls": [
                {
                    "name": o.control.name,
                    "truth": o.control.truth.value,
                    "fault": o.control.fault.value if o.control.fault else None,
                    "rejected": o.rejected,
                    "correct": o.correct,
                    "failure_kind": o.failure_kind,
                }
                for o in report.outcomes
            ],
        }
        if not report.passed:
            print(
                "\nthe correctness gate did not judge its own controls "
                "correctly; no measurement below would be supported",
                file=sys.stderr,
            )
            if args.json:
                args.json.parent.mkdir(parents=True, exist_ok=True)
                args.json.write_text(
                    json.dumps({"gate": control_record, "cases": []}, indent=2) + "\n"
                )
            return 1
        print()

    for name, base, cand, expected in SUITE:
        result = compare(
            Variant(repo, Path(base)),
            Variant(repo, Path(cand)),
            repetitions=args.repetitions,
            platform=args.platform,
        )
        actual = result.verdict.value
        ok = actual == expected
        failures += not ok

        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
        print(f"        verdict {actual}" + ("" if ok else f" (expected {expected})"))
        print(f"        {result.explain()}")

        records.append(
            {
                "case": name,
                "baseline_workload": base,
                "candidate_workload": cand,
                "expected": expected,
                "verdict": actual,
                "agrees": ok,
                "work_reduction": round(result.work_reduction, 6),
                "baseline_net_ir": result.baseline.measurement.net,
                "candidate_net_ir": result.candidate.measurement.net,
                "baseline_checksum": result.baseline.checksum,
                "candidate_checksum": result.candidate.checksum,
                "baseline_deterministic": result.baseline.measurement.deterministic,
                "candidate_deterministic": result.candidate.measurement.deterministic,
                "fingerprint": asdict(result.baseline.measurement.fingerprint),
            }
        )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"gate": control_record, "cases": records}, indent=2) + "\n"
        )
        print(f"\nwrote {args.json}", file=sys.stderr)

    print(f"\n{len(SUITE) - failures}/{len(SUITE)} cases agree with expectation")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
