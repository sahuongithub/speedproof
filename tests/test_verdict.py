"""The verdict logic, exercised without touching Docker."""

import pytest

from speedproof.verifyperf.callgrind import IrMeasurement
from speedproof.verifyperf.fingerprint import Fingerprint
from speedproof.verifyperf.verify import Comparison, Observation, Verdict

FP = Fingerprint(
    arch="aarch64",
    image_digest="09f7da3bc1047",
    python_version="3.12.14",
    valgrind_version="3.24.0",
    libc="glibc-2.36",
)


def obs(net, checksum="same", allocations=1000, spread=0):
    total = net + 1_000_000
    totals = (total,) if spread == 0 else (total, total + spread)
    return Observation(
        measurement=IrMeasurement(
            total=total,
            baseline=1_000_000,
            fingerprint=FP,
            repetitions=len(totals),
            raw_totals=totals,
        ),
        checksum=checksum,
        retained_blocks=allocations,
    )


def cmp_(baseline, candidate, threshold=0.05, tolerance=1e-4):
    return Comparison(baseline, candidate, threshold, tolerance)


def test_real_improvement_is_accepted():
    c = cmp_(obs(1_000_000), obs(500_000))
    assert c.verdict is Verdict.IMPROVED
    assert c.verdict.is_accepted
    assert c.work_reduction == pytest.approx(0.5)


def test_a_faster_wrong_answer_is_not_an_optimisation():
    c = cmp_(obs(1_000_000, checksum="abc"), obs(1_000, checksum="def"))
    assert c.verdict is Verdict.NOT_EQUIVALENT
    assert not c.verdict.is_accepted
    assert "answers differ" in c.explain()


def test_correctness_is_checked_before_stability():
    """A wrong answer is reported as wrong, not as unmeasurable."""
    c = cmp_(obs(1_000_000, checksum="abc"), obs(1_000, checksum="def", spread=99_999))
    assert c.verdict is Verdict.NOT_EQUIVALENT


def test_noise_larger_than_the_claim_blocks_the_claim():
    c = cmp_(obs(1_000_000), obs(900_000, spread=5_000))
    assert c.verdict is Verdict.UNSTABLE
    assert "vary" in c.explain()


def test_buying_speed_with_memory_is_flagged_not_accepted():
    c = cmp_(obs(1_000_000, allocations=10_000), obs(300_000, allocations=100_000))
    assert c.verdict is Verdict.MEMORY_TRADE
    assert not c.verdict.is_accepted
    assert "memory traffic" in c.explain()


def test_a_small_allocation_rise_does_not_block_a_real_win():
    c = cmp_(obs(1_000_000, allocations=1_000), obs(300_000, allocations=1_020))
    assert c.verdict is Verdict.IMPROVED


def test_a_large_fraction_of_a_tiny_number_does_not_block_a_real_win():
    """The first real run flagged a genuine 97% win because two workloads that
    each retained a few hundred blocks differed by 30% of almost nothing."""
    c = cmp_(obs(1_000_000, allocations=400), obs(30_000, allocations=525))
    assert c.verdict is Verdict.IMPROVED


def test_regression_is_named():
    c = cmp_(obs(1_000_000), obs(2_000_000))
    assert c.verdict is Verdict.REGRESSED


def test_change_below_threshold_is_unchanged():
    c = cmp_(obs(1_000_000), obs(980_000))
    assert c.verdict is Verdict.UNCHANGED
    assert "below the" in c.explain()


#: Starting Python and doing nothing, which every measurement carries.
STARTUP = 1_000_000


def obs_with_import(net, import_cost, checksum="same", allocations=1000):
    """An observation that also reports what its module costs to import.

    The three counts nest: the empty baseline is Python starting, the paired
    baseline adds what the module does when imported, and the total adds the
    benchmarked call on top of that.
    """
    baseline = STARTUP + import_cost
    total = baseline + net
    return Observation(
        measurement=IrMeasurement(
            total=total, baseline=baseline, fingerprint=FP,
            repetitions=1, raw_totals=(total,),
            empty_baseline=STARTUP,
        ),
        checksum=checksum,
        retained_blocks=allocations,
    )


def test_work_moved_into_the_import_is_not_an_improvement():
    """Measured on a real module: precomputing at import cut the net count
    99.5% while the program did more work in total."""
    c = cmp_(obs_with_import(1_000_000, 100_000),
             obs_with_import(5_000, 1_200_000))
    assert c.verdict is Verdict.WORK_MOVED
    assert not c.verdict.is_accepted
    assert "moved into the import" in c.explain()


def test_a_real_improvement_survives_the_import_check():
    """The import is unchanged and the work genuinely went away."""
    c = cmp_(obs_with_import(1_000_000, 100_000),
             obs_with_import(400_000, 100_000))
    assert c.verdict is Verdict.IMPROVED


def test_a_cheaper_import_is_still_an_improvement():
    """Making the import itself cheaper is real work, not a trick."""
    c = cmp_(obs_with_import(1_000_000, 500_000),
             obs_with_import(400_000, 200_000))
    assert c.verdict is Verdict.IMPROVED


def test_without_an_import_cost_the_check_cannot_run():
    """A comparison that cannot see the import cannot rule out the work having
    moved there, so total_work_change is unknown rather than zero."""
    c = cmp_(obs(1_000_000), obs(400_000))
    assert c.total_work_change is None
    assert c.verdict is Verdict.IMPROVED
