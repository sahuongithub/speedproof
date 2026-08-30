"""The region counter must be harmless when nothing is counting."""

from speedproof.verifyperf.region import counted, is_counting


def test_counting_is_off_outside_the_measurement_image():
    assert is_counting() is False


def test_the_block_still_runs_when_not_counted():
    """A workload using counted() must behave identically during development."""
    seen = []
    with counted():
        seen.append("ran")
    assert seen == ["ran"]


def test_exceptions_propagate_out_of_the_block():
    try:
        with counted():
            raise ValueError("boom")
    except ValueError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("the exception was swallowed")
