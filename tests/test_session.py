"""A cancelled run must not leave containers behind."""

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
