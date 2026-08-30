"""A cancelled run must not leave containers behind."""

from pathlib import Path

import signal

from speedproof.verifyperf import session


def test_every_container_is_labelled_with_this_session():
    args = session.label_args()
    assert args[0] == "--label"
    assert args[1] == f"{session.LABEL_KEY}={session.SESSION_ID}"


def test_the_session_id_identifies_this_process():
    """Two concurrent runs must not clean up each other's containers."""
    import os

    assert session.SESSION_ID.startswith(f"{os.getpid()}-")


def test_cleanup_is_installed_only_once():
    session._installed = False
    session.install_cleanup()
    first = signal.getsignal(signal.SIGTERM)
    session.install_cleanup()
    assert signal.getsignal(signal.SIGTERM) is first


def test_interrupt_and_terminate_are_both_handled():
    """A cancelled run arrives as one of these two, not as a clean exit."""
    session._installed = False
    session.install_cleanup()
    for sig in (signal.SIGINT, signal.SIGTERM):
        assert signal.getsignal(sig) not in (signal.SIG_DFL, signal.SIG_IGN)


def test_a_relative_mount_is_refused_with_a_useful_message():
    """Docker reads a relative source as a named volume and complains about
    invalid characters, which does not obviously mean 'use an absolute path'."""
    import pytest

    from speedproof.verifyperf.callgrind import MeasurementError, _run_in_container

    with pytest.raises(MeasurementError, match="nothing to mount"):
        _run_in_container(Path("does/not/exist"), "true")
