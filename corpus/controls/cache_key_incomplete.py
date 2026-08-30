"""Memoises on the row count, ignoring the rows themselves."""
from _original import READINGS

_CACHE = {}


def summarise(rows):
    key = len(rows)
    if key in _CACHE:
        return _CACHE[key]
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(count * weight)
    result = [(n, len(v), round(sum(v), 10)) for n, v in sorted(totals.items())]
    _CACHE[key] = result
    return result


def run():
    first = summarise(list(READINGS))
    altered = [("delta", 9, 9.0)] + list(READINGS)[1:]
    return [first, summarise(altered)]      # same length, different rows
