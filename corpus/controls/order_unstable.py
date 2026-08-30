"""Drops the sort. Genuinely faster; the order is now arbitrary."""
from _original import READINGS


def summarise(rows):
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(count * weight)
    return [(n, len(v), round(sum(v), 10)) for n, v in totals.items()]


def run():
    return summarise(list(READINGS))
