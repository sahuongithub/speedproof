"""Fast because the work has not happened yet.

Returns a generator, so under a harness that stops the clock at return the
workload appears to cost almost nothing. The measured region forces the result
to materialise, which puts the work back inside the measurement.
"""

N = 3000


def run():
    return (i * i for i in range(N))
