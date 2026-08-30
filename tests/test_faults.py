"""The control set's own rules."""

from speedproof.hackguard.controls import CONTROLS
from speedproof.hackguard.faults import (
    Control,
    ControlOutcome,
    FaultClass,
    GateReport,
    Truth,
)


def outcome(truth, rejected, name="c"):
    return ControlOutcome(
        Control(name, None, truth, "x.py", "because"), rejected
    )


def test_both_directions_are_represented():
    """A set with no equivalent controls cannot detect an over-strict gate."""
    assert any(c.truth is Truth.BROKEN for c in CONTROLS)
    assert any(c.truth is Truth.EQUIVALENT for c in CONTROLS)


def test_every_control_records_why():
    """A survivor is adjudicated by a person; the reasoning must outlive them."""
    for control in CONTROLS:
        assert control.rationale.strip()
        assert (control.fault is None) == (control.truth is Truth.EQUIVALENT)


def test_missing_a_broken_variant_is_unsound():
    report = GateReport((outcome(Truth.BROKEN, rejected=False),))
    assert report.outcomes[0].failure_kind == "unsound"
    assert report.soundness == 0.0
    assert not report.passed


def test_rejecting_an_equivalent_variant_is_incomplete():
    """Distinct from unsoundness: this rejects a real optimisation."""
    report = GateReport((outcome(Truth.EQUIVALENT, rejected=True),))
    assert report.outcomes[0].failure_kind == "incomplete"
    assert report.completeness == 0.0
    assert not report.passed


def test_a_gate_that_rejects_everything_scores_perfectly_on_soundness():
    """Which is exactly why soundness alone is not evidence of anything."""
    report = GateReport((
        outcome(Truth.BROKEN, rejected=True),
        outcome(Truth.EQUIVALENT, rejected=True),
    ))
    assert report.soundness == 1.0
    assert report.completeness == 0.0
    assert not report.passed


def test_both_directions_must_be_perfect_to_pass():
    report = GateReport((
        outcome(Truth.BROKEN, rejected=True),
        outcome(Truth.EQUIVALENT, rejected=False),
    ))
    assert report.passed


def test_fault_classes_cover_optimisation_specific_faults():
    """Generic mutation operators do not produce these."""
    for name in ("PRECISION_WEAKENED", "CACHE_KEY_INCOMPLETE",
                 "COPY_BECAME_ALIAS", "ORDER_UNSTABLE"):
        assert hasattr(FaultClass, name)
