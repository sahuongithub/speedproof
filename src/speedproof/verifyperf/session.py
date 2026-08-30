"""Making sure a cancelled run does not leave work behind.

``docker run --rm`` removes a container when the container exits, which is not
the same as when the caller does. Interrupt the harness and the container keeps
running: the measurement it was doing is discarded, but the process is still
there, still using a core.

That was observed here. A run cancelled on a timeout left a Valgrind process
running for a further eight minutes, competing with the run that replaced it
and roughly halving its speed.

The consequence is worth stating precisely, because it cuts both ways. A stray
process competing for CPU would corrupt a wall-clock measurement outright, and
it cannot change an instruction count at all -- it only made the run slower.
The harness is still expected to clean up after itself.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import uuid

#: Label applied to every container this process starts, so its own can be
#: told apart from a concurrent run's.
LABEL_KEY = "speedproof.session"

SESSION_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

_installed = False


def label_args() -> list[str]:
    """Docker arguments that tag a container as belonging to this process."""
    return ["--label", f"{LABEL_KEY}={SESSION_ID}"]


def _running(session: str) -> list[str]:
    from speedproof.verifyperf.callgrind import _docker

    probe = subprocess.run(
        [_docker(), "ps", "--quiet", "--filter", f"label={LABEL_KEY}={session}"],
        capture_output=True,
    )
    return probe.stdout.decode().split()


def cleanup(session: str | None = None, quiet: bool = True) -> int:
    """Stop containers left behind by ``session``, defaulting to this one."""
    from speedproof.verifyperf.callgrind import _docker

    session = session or SESSION_ID
    try:
        containers = _running(session)
    except Exception:  # pragma: no cover - docker unavailable at exit
        return 0
    for container in containers:
        subprocess.run(
            [_docker(), "kill", container], capture_output=True, check=False
        )
    if containers and not quiet:
        print(f"stopped {len(containers)} container(s) left by session {session}")
    return len(containers)


def install_cleanup() -> None:
    """Arrange for this process's containers to be stopped when it ends.

    Covers normal exit and the two signals a cancelled run actually arrives
    as. A hard kill cannot be caught, which is why ``cleanup`` can also be
    called with an explicit session id after the fact.
    """
    global _installed
    if _installed:
        return
    _installed = True

    atexit.register(cleanup)

    def _handler(signum, frame):
        cleanup()
        # Restore the default action and re-raise, so the exit status still
        # reports that the process was signalled rather than that it chose to
        # stop.
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except ValueError:  # pragma: no cover - not on the main thread
            pass
