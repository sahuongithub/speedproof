"""An off-by-one in a fast path that skips work for short groups."""
from _original import READINGS


def summarise(rows):
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(count * weight)
    out = []
    for name in sorted(totals):
        values = totals[name]
        if len(values) <= 1:          # should be < 1, so singletons are dropped
            continue
        out.append((name, len(values), round(sum(values), 10)))
    return out


def run():
    return summarise(list(READINGS))
