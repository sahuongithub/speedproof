"""Rebuilds a list by copying it on every iteration: quadratic in n."""

N = 3000


def run():
    out = []
    for i in range(N):
        out = out + [i * i]
    return sum(out)
