"""A real optimisation: setdefault instead of a membership test.

Fewer dictionary lookups, identical results. The gate must accept this, or it
would reject the very thing the benchmark exists to measure.
"""
from _original import READINGS


def summarise(rows):
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(count * weight)
    out = []
    for name in sorted(totals):
        values = totals[name]
        out.append((name, len(values), round(sum(values), 10)))
    return out


def run():
    return summarise(list(READINGS))
