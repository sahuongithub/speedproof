"""Accumulates in single precision."""

import struct

READINGS = [t for i in range(3000)
            for t in (("beta", i % 7, 0.5), ("alpha", i % 5, 0.25),
                      ("gamma", i % 3, 0.125))]


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def summarise(rows):
    totals = {}
    for name, count, weight in rows:
        totals.setdefault(name, []).append(_f32(count * weight * 1.0000001))
    return [(n, len(v), sum(v)) for n, v in sorted(totals.items())]


def run():
    return summarise(list(READINGS))
