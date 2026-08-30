"""Stops copying the caller's list, then sorts it in place."""
from _original import READINGS


def summarise(rows):
    rows.sort()                      # the caller's list is now reordered
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(count * weight)
    return [(n, len(v), round(sum(v), 10)) for n, v in sorted(totals.items())]


def run():
    data = list(READINGS)
    summarise(data)
    return data[:3]                  # observably mutated
