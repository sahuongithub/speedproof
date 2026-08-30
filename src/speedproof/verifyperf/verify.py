"""Comparing two versions of the same code.

A measurement on its own is not a claim. The claim is a comparison, and it only
means anything if three things hold at once: the two versions produce the same
answers, each measurement is stable enough to support the difference being
asserted, and the work genuinely fell rather than being displaced somewhere the
metric cannot see.

The verdict this module returns encodes all three. It is deliberately more
willing to say "I cannot tell" than to report a number.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from speedproof.verifyperf.callgrind import (
    IrMeasurement,
    MeasurementError,
    _docker,
    _install_harness_script,
    ensure_image,
    image_tag,
    measure,
    probe_environment,
)
from speedproof.verifyperf.fingerprint import Fingerprint
from speedproof.verifyperf.session import install_cleanup, label_args


class Verdict(str, Enum):
    """The outcome of comparing a candidate against a baseline."""

    IMPROVED = "improved"
    REGRESSED = "regressed"
    UNCHANGED = "unchanged"
    NOT_EQUIVALENT = "not_equivalent"
    UNSTABLE = "unstable"
    MEMORY_TRADE = "memory_trade"

    @property
    def is_accepted(self) -> bool:
        """Only an unambiguous improvement counts as a win."""
        return self is Verdict.IMPROVED


@dataclass(frozen=True)
class Variant:
    """One side of a comparison: a source tree and the workload to run in it."""

    repo: Path
    workload: Path

    def __post_init__(self) -> None:
        target = self.repo / self.workload
        if not target.is_file():
            raise FileNotFoundError(f"no workload at {target}")


@dataclass(frozen=True)
class Observation:
    """Everything recorded about one variant."""

    measurement: IrMeasurement
    checksum: str
    retained_blocks: int
    """Blocks still allocated when the workload returned.

    This is a retention figure, not a volume figure: a workload that allocates
    a million objects and frees them all reads as zero. It catches a candidate
    that holds on to memory the baseline did not, which is the shape of the
    compute-for-memory trade, but it says nothing about churn.
    """


@dataclass(frozen=True)
class Comparison:
    """A baseline, a candidate, and a verdict that accounts for both axes."""

    baseline: Observation
    candidate: Observation
    threshold: float
    tolerance: float

    @property
    def equivalent(self) -> bool:
        """Do both versions produce the same answer?"""
        return self.baseline.checksum == self.candidate.checksum

    @property
    def work_reduction(self) -> float:
        """Fraction of instructions removed. Negative means more work."""
        base = self.baseline.measurement.net
        if base <= 0:
            raise MeasurementError("baseline performs no measurable work")
        return (base - self.candidate.measurement.net) / base

    #: Below this many blocks, a retention difference is not worth reasoning
    #: about. Two workloads that each retain a few hundred blocks can differ by
    #: a large *fraction* while differing by nothing that matters, which turned
    #: a genuine 97% improvement into a spurious memory-trade flag the first
    #: time this ran.
    MIN_MEANINGFUL_BLOCKS = 4096

    @property
    def retained_delta(self) -> int:
        """Extra blocks the candidate holds at return, in absolute terms."""
        return self.candidate.retained_blocks - self.baseline.retained_blocks

    @property
    def allocation_change(self) -> float:
        """Fractional change in retained blocks. Positive means more held."""
        base = self.baseline.retained_blocks
        if base <= 0:
            return 0.0
        return (self.candidate.retained_blocks - base) / base

    @property
    def stable(self) -> bool:
        return (
            self.baseline.measurement.relative_spread <= self.tolerance
            and self.candidate.measurement.relative_spread <= self.tolerance
        )

    @property
    def verdict(self) -> Verdict:
        # Correctness first: a faster wrong answer is not an optimisation, and
        # nothing downstream is worth computing if the answers differ.
        if not self.equivalent:
            return Verdict.NOT_EQUIVALENT
        if not self.stable:
            return Verdict.UNSTABLE

        reduction = self.work_reduction
        if reduction >= self.threshold:
            # Instruction count rewards buying a saving with memory traffic.
            # rustc PR #77006 cut instructions by 83.9% and lost 14.5% on the
            # clock by doing exactly this, so a large allocation rise alongside
            # an instruction win is referred for review rather than accepted.
            if (
                self.allocation_change > self.threshold * 2
                and self.retained_delta > self.MIN_MEANINGFUL_BLOCKS
            ):
                return Verdict.MEMORY_TRADE
            return Verdict.IMPROVED
        if reduction <= -self.threshold:
            return Verdict.REGRESSED
        return Verdict.UNCHANGED

    def explain(self) -> str:
        """One line a human can act on."""
        v = self.verdict
        if v is Verdict.NOT_EQUIVALENT:
            return (
                "answers differ: baseline hashed "
                f"{self.baseline.checksum[:12]}, candidate "
                f"{self.candidate.checksum[:12]}"
            )
        if v is Verdict.UNSTABLE:
            worst = max(
                self.baseline.measurement.relative_spread,
                self.candidate.measurement.relative_spread,
            )
            return (
                f"measurements vary by up to {worst:.4%} of the net count, "
                f"above the {self.tolerance:.4%} needed to support a claim"
            )
        if v is Verdict.MEMORY_TRADE:
            return (
                f"work fell {self.work_reduction:.1%} but retained memory rose "
                f"{self.allocation_change:.1%} ({self.retained_delta:,} blocks); "
                "the saving may have been bought "
                "with memory traffic, which this metric cannot price"
            )
        if v is Verdict.IMPROVED:
            return (
                f"work fell {self.work_reduction:.1%} "
                f"({self.baseline.measurement.net:,} to "
                f"{self.candidate.measurement.net:,} instructions), "
                "answers identical"
            )
        if v is Verdict.REGRESSED:
            return f"work rose {-self.work_reduction:.1%}, answers identical"
        return (
            f"work changed {self.work_reduction:+.1%}, below the "
            f"{self.threshold:.0%} threshold"
        )


def _capture(
    repo: Path, workload: Path, mode: str, platform: str | None = None
) -> str:
    """Run one unmeasured mode of the inner runner and return its output."""
    ensure_image(platform=platform)
    repo = Path(repo).resolve()
    rel = workload.relative_to(repo) if workload.is_absolute() else workload
    script = f"""
set -e
cd /tmp
{_install_harness_script()}
cp /work/{rel} /tmp/workload.py
export PYTHONPATH=/tmp/harness:/work
python3 /tmp/harness/speedproof/verifyperf/inner.py {mode} /tmp/workload.py
"""
    install_cleanup()
    proc = subprocess.run(
        [_docker(), "run", "--rm", "-i", "--network", "none"]
        + label_args()
        + (["--platform", platform] if platform else [])
        + [
            "-v", f"{repo}:/work:ro",
            "-e", "PYTHONHASHSEED=0",
            "-e", "PYTHON_JIT=0",
            image_tag(platform), "bash", "-s",
        ],
        input=script.encode(),
        capture_output=True,
        timeout=900,
    )
    if proc.returncode != 0:
        raise MeasurementError(
            f"{mode} run failed:\n" + proc.stderr.decode(errors="replace")[-2000:]
        )
    out = proc.stdout.decode().strip().splitlines()
    if not out:
        raise MeasurementError(f"{mode} run produced no output")
    return out[-1].strip()


def observe(
    variant: Variant,
    repetitions: int = 5,
    fingerprint: Fingerprint | None = None,
    platform: str | None = None,
) -> Observation:
    """Measure one variant on both axes and record what it computed."""
    fingerprint = fingerprint or probe_environment(variant.repo, platform)
    return Observation(
        measurement=measure(
            variant.repo, variant.workload, repetitions, fingerprint, platform
        ),
        checksum=_capture(variant.repo, variant.workload, "checksum", platform),
        retained_blocks=int(
            _capture(variant.repo, variant.workload, "alloc", platform)
        ),
    )


def compare(
    baseline: Variant,
    candidate: Variant,
    threshold: float = 0.05,
    tolerance: float = 1e-4,
    repetitions: int = 5,
    platform: str | None = None,
) -> Comparison:
    """Compare two variants and return a verdict that accounts for both axes.

    ``threshold`` is the fraction of work that must be removed before a change
    counts as an improvement. ``tolerance`` is how much run-to-run variation,
    as a fraction of the net count, a measurement may show and still support a
    claim.
    """
    fingerprint = probe_environment(baseline.repo, platform)
    return Comparison(
        baseline=observe(baseline, repetitions, fingerprint, platform),
        candidate=observe(candidate, repetitions, fingerprint, platform),
        threshold=threshold,
        tolerance=tolerance,
    )
