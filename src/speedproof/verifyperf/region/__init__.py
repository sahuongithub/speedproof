"""Counting only a marked region, rather than subtracting a baseline.

Baseline subtraction is the default because it needs nothing beyond Valgrind
itself: measure the workload, measure an empty workload through the same
wrapper, subtract. It is exact when the workload is large relative to the
roughly 49 million instructions Python spends starting up.

It degrades when the workload is small. A net count of a hundred thousand
instructions is the difference between two numbers near fifty million, so a
handful of instructions of wrapper jitter is a large fraction of the answer.

This module is the alternative for that case. The workload marks its own region
and Callgrind counts only what happens inside it, so interpreter startup never
enters the number and the wrapper's size stops mattering. The cost is a
compiled shim in the image, which is why it is not the default.

    from speedproof.verifyperf.region import counted

    data = build_input()        # not counted
    with counted():
        result = candidate(data)
"""

from speedproof.verifyperf.region.counter import counted, is_counting

__all__ = ["counted", "is_counting"]
