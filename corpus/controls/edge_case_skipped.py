"""Drops the guard that copes with an empty group."""
from _original import READINGS


def summarise(rows):
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(count * weight)
    return [(n, len(v), round(sum(v), 10)) for n, v in sorted(totals.items())]


def run():
    return [summarise(list(READINGS)), summarise([])[:1] or ["missing"]]
