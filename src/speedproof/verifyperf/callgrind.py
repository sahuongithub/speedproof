"""Host-side driver for deterministic instruction counting.

The measurement runs inside a container that the code under test never gets to
configure.  The host builds the command, the container counts the
instructions, and the number comes back as a plain integer.

Determinism depends on five controls, all applied here rather than left to the
workload:

1. ``PYTHONHASHSEED=0``      -- removes hash-order variation
2. ``gc.disable()``          -- applied by the inner runner
3. a warm ``__pycache__``    -- one discarded run before any counted run
4. ``--cache-sim=no --branch-sim=no`` -- count instructions only
5. baseline subtraction      -- removes interpreter startup, which is roughly
   36 million instructions and would otherwise dominate a small workload

Without (5) a thirty-fold difference in the work performed reads as a five per
cent difference in the total.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from speedproof.verifyperf.fingerprint import Fingerprint

# python:3.12-slim, pinned.  The tag moves; the digest does not, and a moving
# base image would silently change every count in the corpus.
BASE_IMAGE = (
    "python@sha256:"
    "09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217"
)
IMAGE_TAG = "speedproof/measure:0.1.0"

#: Architectures the harness knows how to measure on. Counts are reproducible
#: within one of these and are not comparable between them: the instruction
#: stream differs, and libraries that dispatch on detected CPU features may
#: select different code paths.
ARCHITECTURES = ("linux/arm64", "linux/amd64")

_SUMMARY = re.compile(rb"^summary:\s+(\d+)", re.MULTILINE)
_VG_VERSION = re.compile(r"valgrind-([\d.]+)")

class MeasurementError(Exception):
    """Raised when a measurement cannot be completed or trusted."""


@dataclass(frozen=True)
class IrMeasurement:
    """A deterministic instruction count for one workload."""

    total: int
    baseline: int
    fingerprint: Fingerprint
    repetitions: int
    raw_totals: tuple[int, ...] = field(default=())

    @property
    def net(self) -> int:
        """Instructions attributable to the workload itself."""
        return self.total - self.baseline

    @property
    def spread(self) -> int:
        """Difference between the largest and smallest repetition."""
        return max(self.raw_totals) - min(self.raw_totals) if self.raw_totals else 0

    @property
    def deterministic(self) -> bool:
        """True when every repetition returned exactly the same count."""
        return len(set(self.raw_totals)) <= 1

    @property
    def relative_spread(self) -> float:
        """Spread as a fraction of the net count -- the number that matters.

        Constant wrapper overhead cancels in the subtraction, but its variance
        does not: it lands whole on the net figure.  A workload whose net count
        is small relative to the spread cannot support a claim.
        """
        return self.spread / self.net if self.net > 0 else float("inf")

    def assert_stable(self, tolerance: float = 1e-4) -> None:
        """Raise unless repetitions agree closely enough to support a claim."""
        if self.relative_spread > tolerance:
            raise MeasurementError(
                f"instruction count is not stable enough to compare: spread "
                f"{self.spread:,} over net {self.net:,} "
                f"({self.relative_spread:.2%} > {tolerance:.2%}). "
                f"Repetitions: {self.raw_totals}"
            )

    def work_ratio_to(self, other: "IrMeasurement") -> float:
        """Ratio of instructions retired -- NOT a speedup factor.

        Instruction count systematically overstates the magnitude of
        algorithmic wins, because it prices every instruction as if it were
        serial while the hardware retires several per cycle. A measured
        replacement of a list scan by a set lookup came to 33,243x on
        instructions against 2,558x on the clock: right direction, thirteenfold
        overstatement.

        Use this to establish *that* work fell and by at least how much. Never
        quote it as "n times faster"; for that, use the wall-clock arm.
        """
        self.fingerprint.assert_comparable(other.fingerprint)
        if self.net <= 0:
            raise MeasurementError(
                "net instruction count is not positive; the workload does less "
                "work than the empty baseline, which means the baseline is wrong"
            )
        return other.net / self.net

    def improves_on(self, baseline: "IrMeasurement", threshold: float = 0.05) -> bool:
        """True when this measurement retires at least ``threshold`` less work.

        This is the valid comparison: a direction and a floor. The benchmark
        asks "did the work fall by at least five per cent", which instruction
        counting answers exactly, rather than "how much faster is it", which it
        answers badly.
        """
        self.fingerprint.assert_comparable(baseline.fingerprint)
        if baseline.net <= 0:
            raise MeasurementError("baseline net instruction count is not positive")
        return (baseline.net - self.net) / baseline.net >= threshold


def _docker() -> str:
    exe = shutil.which("docker")
    if exe is None:
        raise MeasurementError("docker is not on PATH")
    return exe


def image_tag(platform: str | None = None) -> str:
    """Tag for the measurement image, kept separate per architecture."""
    if platform is None:
        return IMAGE_TAG
    if platform not in ARCHITECTURES:
        raise MeasurementError(
            f"unknown platform {platform!r}; expected one of {ARCHITECTURES}"
        )
    return f"{IMAGE_TAG}-{platform.split('/')[-1]}"


def ensure_image(rebuild: bool = False, platform: str | None = None) -> None:
    """Build the measurement image if it is not already present."""
    docker = _docker()
    tag = image_tag(platform)
    if not rebuild:
        probe = subprocess.run(
            [docker, "image", "inspect", tag],
            capture_output=True,
        )
        if probe.returncode == 0:
            return

    dockerfile = f"""
FROM {BASE_IMAGE}
RUN apt-get update \\
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends valgrind \\
 && rm -rf /var/lib/apt/lists/*
ENV PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=0 PYTHON_JIT=0
WORKDIR /work
"""
    build = subprocess.run(
        [docker, "build"]
        + (["--platform", platform] if platform else [])
        + ["-t", tag, "-"],
        input=dockerfile.encode(),
        capture_output=True,
    )
    if build.returncode != 0:
        raise MeasurementError(
            "could not build the measurement image:\n"
            + build.stderr.decode(errors="replace")[-2000:]
        )

    if platform is not None:
        _assert_image_architecture(tag, platform)


def _assert_image_architecture(tag: str, platform: str) -> None:
    """Confirm the image really is for the architecture that was requested.

    ``docker build --platform`` does not fail when the daemon cannot honour it;
    without buildx configured it quietly produces an image for the host
    architecture instead. An unnoticed mismatch is worse than a build error,
    because a cross-architecture comparison would then be comparing one
    architecture against itself and reporting perfect agreement.
    """
    wanted = platform.split("/")[-1]
    probe = subprocess.run(
        [_docker(), "image", "inspect", tag, "--format", "{{.Architecture}}"],
        capture_output=True,
    )
    built = probe.stdout.decode().strip()
    if built != wanted:
        raise MeasurementError(
            f"asked for a {wanted} image and got {built}. The Docker daemon "
            "ignored --platform, which it does silently when buildx is not "
            "available. Measuring with this image would compare an "
            "architecture against itself. Install buildx, or run the "
            f"{wanted} measurements on {wanted} hardware."
        )


def _run_in_container(
    repo: Path, script: str, timeout: int = 900, platform: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_docker(), "run", "--rm", "-i", "--network", "none"]
        + (["--platform", platform] if platform else [])
        + [
            "-v", f"{repo}:/work:ro",
            "-e", "PYTHONHASHSEED=0",
            "-e", "PYTHON_JIT=0",
            "-e", "PYTHONPATH=/work/src",
            image_tag(platform), "bash", "-s",
        ],
        input=script.encode(),
        capture_output=True,
        timeout=timeout,
    )


def probe_environment(repo: Path, platform: str | None = None) -> Fingerprint:
    """Read the identity of the measurement environment from inside it."""
    ensure_image(platform=platform)
    script = r"""
set -e
python3 - <<'PY'
import json, platform, sys
print(json.dumps({
    "arch": platform.machine(),
    "python_version": platform.python_version(),
    "libc": "-".join(x for x in platform.libc_ver() if x) or "unknown",
}))
PY
valgrind --version
"""
    proc = _run_in_container(repo, script, platform=platform)
    if proc.returncode != 0:
        raise MeasurementError(proc.stderr.decode(errors="replace")[-2000:])

    lines = [ln for ln in proc.stdout.decode().splitlines() if ln.strip()]
    info = json.loads(lines[0])
    match = _VG_VERSION.search(lines[-1])
    return Fingerprint(
        arch=info["arch"],
        image_digest=BASE_IMAGE.split(":")[-1][:16],
        python_version=info["python_version"],
        valgrind_version=match.group(1) if match else "unknown",
        libc=info["libc"],
    )


def measure(
    repo: Path,
    workload: Path,
    repetitions: int = 3,
    fingerprint: Fingerprint | None = None,
    platform: str | None = None,
) -> IrMeasurement:
    """Count the instructions ``workload`` executes, net of interpreter startup.

    ``workload`` is a path relative to ``repo`` naming a file that defines
    ``run()``.  It is executed inside the container; nothing it does can reach
    the counter, which lives outside the interpreter entirely.
    """
    ensure_image(platform=platform)
    fingerprint = fingerprint or probe_environment(repo, platform)
    rel = workload.relative_to(repo) if workload.is_absolute() else workload

    script = f"""
set -e
cd /tmp
cp -r /work/src /tmp/src
cat > /tmp/noop.py <<'NOOP_EOF'
def run():
    return None
NOOP_EOF
cp /work/{rel} /tmp/workload.py
export PYTHONPATH=/tmp/src
run() {{
  valgrind --tool=callgrind --cache-sim=no --branch-sim=no \\
           --callgrind-out-file=/tmp/cg.out \\
           python3 /tmp/src/speedproof/verifyperf/inner.py measure "$1" >/dev/null 2>/tmp/vg.log
  grep -m1 '^summary:' /tmp/cg.out | awk '{{print $2}}'
}}
# Warm the bytecode cache for both scripts; the first execution of any Python
# file costs an extra compilation that would otherwise land in run one.
python3 /tmp/src/speedproof/verifyperf/inner.py measure /tmp/noop.py     >/dev/null || \
  {{ echo "warm-up of the empty baseline failed" >&2; exit 3; }}
python3 /tmp/src/speedproof/verifyperf/inner.py measure /tmp/workload.py >/dev/null || \
  {{ echo "warm-up of the workload failed" >&2; exit 4; }}
echo "BASELINE $(run /tmp/noop.py)"
for _ in $(seq {repetitions}); do echo "TOTAL $(run /tmp/workload.py)"; done
"""
    proc = _run_in_container(repo, script, platform=platform)
    if proc.returncode != 0:
        raise MeasurementError(
            "measurement failed inside the container:\n"
            + proc.stderr.decode(errors="replace")[-2000:]
        )

    baseline = 0
    totals: list[int] = []
    for line in proc.stdout.decode().splitlines():
        if line.startswith("BASELINE "):
            baseline = int(line.split()[1])
        elif line.startswith("TOTAL "):
            totals.append(int(line.split()[1]))

    if not totals or baseline == 0:
        raise MeasurementError(
            "the container produced no usable counts; stdout was:\n"
            + proc.stdout.decode()[-1000:]
        )

    return IrMeasurement(
        total=min(totals),
        baseline=baseline,
        fingerprint=fingerprint,
        repetitions=len(totals),
        raw_totals=tuple(totals),
    )
