"""Summarise a table of readings. The original, correct implementation."""

# A singleton group is included deliberately. Without one, a fault in the
# short-group fast path is never reached, and a gate that cannot see an
# unreached fault has not been tested by it.
READINGS = [
    ("beta", 3, 0.1), ("alpha", 1, 0.2), ("beta", 2, 0.3),
    ("alpha", 4, 0.4), ("gamma", 5, 0.5), ("alpha", 2, 0.6),
] * 200 + [("solo", 7, 0.7)]


def summarise(rows):
    totals = {}
    for name, count, weight in rows:
        if name not in totals:
            totals[name] = []
        totals[name].append(count * weight)
    out = []
    for name in sorted(totals):
        values = totals[name]
        out.append((name, len(values), round(sum(values), 10)))
    return out


def run():
    return summarise(list(READINGS))
