"""Same result as quadratic_concat, computed in one pass."""

N = 3000


def run():
    return sum(i * i for i in range(N))
