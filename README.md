# speedproof

Deterministic verification of code-performance improvements.

A performance claim is only as good as the measurement behind it. Wall-clock
benchmarking is noisy enough that published speedups are routinely smaller than
the measurement bias that produced them, and an optimising agent that is scored
on wall clock has a large and well-documented menu of ways to move the number
without doing the work.

This project takes the opposite approach: count retired instructions, in a
container the code under test cannot configure, with the counter outside the
interpreter entirely. The result is an integer rather than an interval, it
reproduces exactly, and it costs nothing to run.

## Status

Early. The measurement core works and is bit-reproducible; the corpus, the
gaming detector and the agent are not built yet.

## What works today

```
uv run pytest -q                    # unit tests
```

Measuring a workload, net of interpreter startup:

```python
from pathlib import Path
from speedproof.verifyperf.callgrind import measure, probe_environment

repo = Path.cwd()
fp = probe_environment(repo)
m = measure(repo, Path("corpus/examples/linear_sum.py"), repetitions=5, fingerprint=fp)
m.assert_stable()
print(m.net, m.deterministic)
```

## Requirements

Docker. Nothing else — the measurement image is built on first use and pins its
base by digest, because a moving base image would silently change every count.
