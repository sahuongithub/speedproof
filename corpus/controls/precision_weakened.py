"""Accumulates in single precision. Faster, and wrong in the last digits."""
import struct
from _original import READINGS


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def summarise(rows):
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(_f32(count * weight))
    return [
        (n, len(v), round(sum(v), 10)) for n, v in sorted(totals.items())
    ]


def run():
    return summarise(list(READINGS))
