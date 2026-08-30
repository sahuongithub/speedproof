"""Group readings by name and total each group."""

READINGS = [("beta", i % 7), ("alpha", i % 5), ("gamma", i % 3) ] * 400


def run():
    names = []
    for name, _ in READINGS:
        if name not in names:          # linear scan of a list, per row
            names.append(name)
    out = []
    for name in sorted(names):
        total = 0
        for other, value in READINGS:  # a full pass per distinct name
            if other == name:
                total += value
        out.append((name, total))
    return out
