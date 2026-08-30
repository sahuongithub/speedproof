import pytest

from speedproof.verifyperf.fingerprint import Fingerprint, IncomparableEnvironments

BASE = dict(
    arch="aarch64",
    image_digest="09f7da3bc1047",
    python_version="3.12.12",
    valgrind_version="3.24.0",
    libc="glibc-2.36",
)


def test_identical_environments_compare():
    Fingerprint(**BASE).assert_comparable(Fingerprint(**BASE))


def test_different_architecture_is_refused():
    other = Fingerprint(**{**BASE, "arch": "x86_64"})
    with pytest.raises(IncomparableEnvironments, match="arch"):
        Fingerprint(**BASE).assert_comparable(other)


def test_different_python_build_is_refused():
    other = Fingerprint(**{**BASE, "python_version": "3.13.0"})
    with pytest.raises(IncomparableEnvironments, match="python_version"):
        Fingerprint(**BASE).assert_comparable(other)


def test_digest_is_stable_and_short():
    assert Fingerprint(**BASE).digest == Fingerprint(**BASE).digest
    assert len(Fingerprint(**BASE).digest) == 16
