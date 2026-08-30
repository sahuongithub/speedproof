"""Paired baseline: the same imports, none of the work."""

READINGS = [t for i in range(3000)
            for t in (("beta", i % 7, 0.5), ("alpha", i % 5, 0.25),
                      ("gamma", i % 3, 0.125))]


def run():
    return None
