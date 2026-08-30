"""The permanent control set, and the run that validates the gate against it."""

from __future__ import annotations

from pathlib import Path

from speedproof.hackguard.faults import (
    Control,
    ControlOutcome,
    FaultClass,
    GateReport,
    Truth,
)

CONTROL_DIR = Path("corpus/controls")
ORIGINAL = "_original.py"

CONTROLS: tuple[Control, ...] = (
    Control(
        "precision_weakened", FaultClass.PRECISION_WEAKENED, Truth.BROKEN,
        "precision_weakened.py",
        "sums in single precision, so the totals differ in their last digits",
    ),
    Control(
        "order_unstable", FaultClass.ORDER_UNSTABLE, Truth.BROKEN,
        "order_unstable.py",
        "drops the sort, so the rows come back in an arbitrary order",
    ),
    Control(
        "comparison_flip", FaultClass.COMPARISON_FLIP, Truth.BROKEN,
        "comparison_flip.py",
        "an off-by-one in a fast path silently discards single-row groups",
    ),
    Control(
        "cache_key_incomplete", FaultClass.CACHE_KEY_INCOMPLETE, Truth.BROKEN,
        "cache_key_incomplete.py",
        "memoises on the row count, so different data of the same size "
        "returns the first answer",
    ),
    Control(
        "copy_became_alias", FaultClass.COPY_BECAME_ALIAS, Truth.BROKEN,
        "copy_became_alias.py",
        "sorts the caller's list in place instead of copying it",
    ),
    Control(
        "edge_case_skipped", FaultClass.EDGE_CASE_SKIPPED, Truth.BROKEN,
        "edge_case_skipped.py",
        "drops the guard for an empty input",
    ),
    Control(
        "genuinely_faster", None, Truth.EQUIVALENT,
        "genuinely_faster.py",
        "a real optimisation: fewer dictionary lookups, identical results. "
        "Rejecting this would reject what the benchmark exists to measure",
    ),
    Control(
        "rewritten_identically", None, Truth.EQUIVALENT,
        "rewritten_identically.py",
        "a comprehension in place of a loop, observably identical",
    ),
)


def validate_gate(
    root: Path = Path.cwd(),
    image: str | None = None,
    platform: str | None = None,
) -> GateReport:
    """Run every control past the gate and record whether it judged correctly.

    The gate here is the equivalence half: capture what the workload returned,
    encode it canonically on the host, and compare. A control is 'rejected'
    when its encoding differs from the original's.
    """
    from speedproof.verifyperf.verify import _capture

    tree = (root / CONTROL_DIR).resolve()
    reference = _capture(tree, Path(ORIGINAL), "checksum", platform)

    outcomes = []
    for control in CONTROLS:
        try:
            digest = _capture(tree, Path(control.source), "checksum", platform)
            rejected = digest != reference
            detail = f"{digest[:12]} vs {reference[:12]}"
        except Exception as exc:
            # A control that cannot run has not been judged, and counting it
            # either way would be a guess.
            rejected = True
            detail = f"could not be evaluated: {exc}"
        outcomes.append(ControlOutcome(control, rejected, detail))
    return GateReport(tuple(outcomes))
