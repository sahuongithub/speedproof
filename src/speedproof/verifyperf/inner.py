"""Runs inside the measurement container.  Never import this from the host.

Everything in the measured path is deliberately minimal.  The wrapper's own
imports are counted along with the workload's, and they are subtracted away by
the empty baseline -- but only their *mean* is subtracted, not their variance.
A wrapper that imports argparse, importlib, json and pathlib costs roughly 155
million instructions and carries a few hundred instructions of run-to-run
jitter from filesystem stats and path scanning; that jitter lands directly on
the net figure.  So the measured path uses ``sys.argv``, ``compile`` and
``exec`` and nothing else, which keeps the baseline near the cost of starting
Python at all.

Two modes, deliberately separated:

``measure``
    Execute the workload under Callgrind.  Output is forced to materialise so
    that a patch cannot defer work past the measured region, but nothing else
    is computed here.

``checksum``
    Execute the workload without Callgrind and print a canonical hash of its
    result.  Correctness is decided here, outside the measured region, so the
    cost of checking never enters the number being compared.
"""

import gc
import sys


def _load_and_run(path):
    """Compile and execute ``path``, then call its ``run()``.

    Uses ``compile``/``exec`` rather than importlib: the import system stats
    directories, consults finders and mutates ``sys.modules``, all of which
    cost instructions that vary slightly between runs.
    """
    with open(path, "rb") as handle:
        source = handle.read()
    namespace = {"__name__": "_sp_workload", "__file__": path}
    exec(compile(source, path, "exec"), namespace)
    run = namespace.get("run")
    if run is None:
        raise SystemExit(f"{path} defines no run() function")
    return run()


def _force(value):
    """Materialise a lazily-produced result and return a cheap size proxy.

    Defeats the "return a generator so the work happens after measurement"
    strategy.  Kept deliberately cheap so it contributes an almost constant
    number of instructions to both sides of a comparison.
    """
    if value is None:
        return 0
    if type(value) in (int, float, bool):
        return 1
    if type(value) in (str, bytes, bytearray, list, tuple, set, frozenset, dict):
        return len(value)
    if hasattr(value, "__iter__"):
        total = 0
        for _ in value:
            total += 1
        return total
    return 1


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("measure", "checksum", "alloc"):
        raise SystemExit("usage: inner.py {measure|checksum|alloc} <workload.py>")
    mode, path = sys.argv[1], sys.argv[2]

    # The collector's scheduling would otherwise make the instruction count
    # depend on allocation history rather than on the work performed.
    gc.disable()

    if mode == "alloc":
        # Allocation volume is the second axis, and it is exactly the thing
        # instruction count rewards and wall clock punishes: a patch that
        # trades compute for memory looks like a large win on Ir alone.
        # gc.collect() before the reading is required, or the baseline drifts.
        gc.collect()
        before = sys.getallocatedblocks()
        result = _load_and_run(path)
        _force(result)
        sys.stdout.write(str(sys.getallocatedblocks() - before) + "\n")
        return 0

    result = _load_and_run(path)

    if mode == "measure":
        _force(result)
        return 0

    # Only the unmeasured path pays for hashlib and the canonical encoder.
    from speedproof.verifyperf.canon import checksum

    sys.stdout.write(checksum(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
