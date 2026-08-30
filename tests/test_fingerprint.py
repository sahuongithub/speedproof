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


def test_image_digest_is_part_of_identity():
    """Counts shift slightly between image rebuilds, so the image is identity."""
    other = Fingerprint(**{**BASE, "image_digest": "different0000000"})
    with pytest.raises(IncomparableEnvironments, match="image_digest"):
        Fingerprint(**BASE).assert_comparable(other)


def test_architectures_are_never_silently_comparable():
    """A cross-architecture comparison must fail loudly, not average away.

    Counts are reproducible within an architecture and are not portable
    between them, so agreement across architectures is asserted on verdicts
    and never on numbers.
    """
    arm = Fingerprint(**BASE)
    x86 = Fingerprint(**{**BASE, "arch": "x86_64"})
    assert arm.digest != x86.digest
    with pytest.raises(IncomparableEnvironments):
        arm.assert_comparable(x86)


def test_ensure_image_names_the_image_on_every_path():
    """A builder that returns the tag only when it builds is a trap.

    Callers pass the return value straight back in as ``image=``; returning
    None for an image that already exists silently selects the default one,
    which is how a project's dependencies went missing from a measurement.
    """
    import inspect

    from speedproof.verifyperf import callgrind

    source = inspect.getsource(callgrind.ensure_image)
    returns = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("return")
    ]
    assert returns, "ensure_image should return the tag it ensured"
    assert all(r != "return" for r in returns), (
        f"ensure_image has a bare return: {returns}"
    )
