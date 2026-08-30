"""Report a running mean and variance over a window."""

SERIES = [float((i * 37) % 101) for i in range(3000)]
WINDOW = 50


def run():
    out = []
    for i in range(WINDOW, len(SERIES)):
        window = SERIES[i - WINDOW:i]          # copies the window every step
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / len(window)
        out.append((round(mean, 9), round(var, 9)))
    return out
