"""A comprehension in place of a loop. Nothing observable changes."""
from _original import READINGS


def summarise(rows):
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(count * weight)
    return [
        (name, len(totals[name]), round(sum(totals[name]), 10))
        for name in sorted(totals)
    ]


def run():
    return summarise(list(READINGS))
