"""Find every word in the corpus starting with each prefix."""

WORDS = [f"word{i:05d}" for i in range(2000)] + ["alpha", "beta", "gamma"]
PREFIXES = ["word001", "word012", "alpha", "zzz"]


def run():
    out = {}
    for prefix in PREFIXES:
        found = []
        for word in WORDS:
            if word[:len(prefix)] == prefix:   # slices a new string per word
                found.append(word)
        out[prefix] = sorted(found)
    return out
