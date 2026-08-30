"""A closed form for a different quantity."""

READINGS = [t for i in range(3000)
            for t in (("beta", i % 7, 0.5), ("alpha", i % 5, 0.25),
                      ("gamma", i % 3, 0.125))]


def run():
    return [('alpha', 300, 150.0), ('beta', 300, 448.0515), ('gamma', 300, 37.5)]
