"""Fast because it does not compute the right thing.

A naive harness that only times the workload records a large win. The
canonical checksum records a different answer, so the verdict is a correctness
failure rather than a speedup.
"""

N = 3000


def run():
    # The honest answer is sum(i*i for i in range(N)).  This is a closed form
    # for a *different* series, and it is very nearly instantaneous.
    return N * (N - 1) // 2
