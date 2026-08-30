"""Identity of the environment a measurement was taken in.

Instruction counts are reproducible to the instruction on one environment, and
are *not* portable across architectures or interpreter builds.  Every
measurement therefore carries a fingerprint, and comparing two measurements
with different fingerprints is refused rather than warned about.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Fingerprint:
    """Everything that can change an instruction count without the code changing."""

    arch: str
    image_digest: str
    python_version: str
    valgrind_version: str
    libc: str

    @property
    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]

    def assert_comparable(self, other: "Fingerprint") -> None:
        """Raise unless two measurements may legitimately be compared."""
        if self.digest != other.digest:
            mine, theirs = asdict(self), asdict(other)
            differing = [k for k in mine if mine[k] != theirs[k]]
            raise IncomparableEnvironments(
                "refusing to compare measurements taken in different "
                f"environments; differing fields: {', '.join(differing)}"
            )

    def __str__(self) -> str:
        return f"{self.arch}/{self.python_version}/vg{self.valgrind_version}@{self.digest}"


class IncomparableEnvironments(Exception):
    """Raised when two measurements cannot be meaningfully compared."""
