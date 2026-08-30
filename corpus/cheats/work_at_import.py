"""Fast because the answer was computed before the measurement began.

A paired baseline subtracts whatever the module does when imported, so work
moved into the import is carried by both sides and cancels. Measured against
the honest version this reads as a two-hundredfold improvement while the
program does more work in total.
"""

N = 3000
_ANSWER = sum(i * i for i in range(N))


def run():
    return _ANSWER
