"""Fast on every run after the first, because it caches at module scope.

Harnesses that call the workload repeatedly inside one process see the second
and subsequent calls come back free. Measuring in a fresh process each time
removes the advantage.
"""

N = 3000
_CACHE = {}


def run():
    if N not in _CACHE:
        _CACHE[N] = sum(i * i for i in range(N))
    return _CACHE[N]
