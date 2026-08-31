# Reproducing this

Every number in the README came from a command in this file. The timings below
were measured by running these steps on a clean clone, not estimated.

## What you need

**Docker, and nothing else.** The measurement image is built on first use. Its
base is pinned by digest rather than by tag, because a moving base image would
silently change every count in this repository.

`uv` if you have it; the commands below use it. Everything works with `pip` and
a virtual environment too — see the last section.

No API key is required for anything in this file. The parts that call a model
are marked, and they are not needed to check any measurement.

## The short version

```bash
git clone <this repository> && cd speedproof
uv sync --extra dev
uv run pytest -q                            #  ~1 second, 206 tests
uv run python -m speedproof.hackguard       # ~55 seconds the first time
```

The second command runs the test suite. The third prints the table at the top of
the README: five attempted optimisations, each judged as a harness that only
times the code would judge it, and again with the answers and the import cost
checked.

Measured on a clean clone: **54 seconds**, most of it building the image and
installing Valgrind. Subsequent runs take about 40 seconds, nearly all of it
Valgrind, which costs twenty to a hundred times native speed and is the price of
a count that does not move.

It exits non-zero if any case is judged wrongly, so it is also a regression test
for the gates.

### What you should see

```
  the naive harness accepted 2 of 4 attempts that are not optimisations
  this one judged 5 of 5 cases correctly
```

If the second line says anything other than 5 of 5, something is wrong and the
run has told you so rather than printing a number anyway.

## Checking the correctness gate separately

```bash
uv run python -m speedproof.verifyperf.cli
```

This validates the gate against its permanent controls before measuring
anything, then runs the comparison suite. Expect:

```
soundness    6/6 broken variants rejected by comparison
completeness 2/2 equivalent variants accepted
```

Both numbers matter. A gate that rejected everything would score 6/6 on the
first and 0/2 on the second.

The controls live in `corpus/controls/`. They are ordinary Python files and are
meant to be read: six are broken in ways that a timing-only harness would accept,
and two are real optimisations that a gate tuned too tightly would wrongly
reject.

Takes about **70 seconds** with the image already built, again mostly
Valgrind. That figure and every other timing here was measured on a clean clone
rather than estimated; the first estimate for this one was three minutes and was
wrong, which is the sort of thing a reproduction guide exists to catch.

## Checking that a measurement is exact

```bash
uv run python - <<'PY'
from pathlib import Path
from speedproof.verifyperf.callgrind import measure, probe_environment

here = Path.cwd()
fingerprint = probe_environment(here)
print(fingerprint)
for name in ("quadratic_concat", "linear_sum"):
    m = measure(here, Path(f"corpus/examples/{name}.py"),
                repetitions=5, fingerprint=fingerprint)
    print(f"{name:18s} net={m.net:>12,}  "
          f"{'bit-identical' if m.deterministic else f'spread {m.spread}'}")
PY
```

Five repetitions of each. Both should report `bit-identical`. The absolute
numbers will differ from the README's if your architecture differs from the
machine those were taken on — that is expected and is why the harness records a
fingerprint and refuses to compare measurements across differing ones.

## Reproducing the cross-architecture result

The README reports the same suite on arm64 and on x86_64, agreeing to 0.01
percentage points on the fraction of work removed while the raw counts differ by
about ten per cent. To see that yourself you need both architectures. The
GitHub Actions workflow in `.github/workflows/verify.yml` runs it on x86_64 and
asserts that a second run returns identical counts; on an arm64 machine, running
the commands above gives you the other half.

If you have only one architecture, the claim you can check locally is the one
that matters more: that repeated runs on a deliberately noisy machine return the
same integer.

## Running the agent (needs a model)

This is the only part that needs model access, and it is not needed to check any
measurement above.

```bash
uv run python -m speedproof.speedagent.cli corpus/manifests/packaging.json \
    --task packaging_bce44a178e --arm one_shot --arm agent --rounds 3
```

It clones the target repository on first use. Each round is a model call, a
correctness check and a measurement, so a three-round run on one task takes
**fifteen to thirty minutes** — the measurement dominates.

Trajectories are written to `eval/trajectories/` as a JSON record and a readable
page per task and arm, including the rounds that failed.

## Running the corpus

```bash
uv run python -m speedproof.corpus.cli corpus/manifests/packaging.json --limit 3
```

Reports what happened to each candidate: whether a workload reached the changed
lines, whether the maintainer's own patch passes the gate, and how much work it
removed. Most candidates do not survive, and the distribution of reasons is in
`docs/corpus.md`.

Cloning is on first use and cached under `corpus/repos/`. pypa/packaging is
small; the pandas manifest needs a build of about four minutes per task.

## Versions, runtime and cost

**Cost: nothing, except the agent.** The measurement, the cheat suite, the
correctness gate, the corpus mining and the cross-architecture check use no paid
service of any kind. They run on a laptop and on a free CI runner. The only part
that costs money is the model call inside the agent, and it is not needed to
check any measurement in this repository.

| | |
| --- | --- |
| measurement image base | `python@sha256:09f7da3b…f5d85217`, pinned by digest |
| Python, host | 3.12 or later |
| Docker | 29.7.1 (any recent version; colima works) |
| `uv` | 0.12.1 (optional — see below) |
| architectures verified | arm64 (Apple M1) and x86_64 (GitHub runner) |

Counts are not portable across architectures; ratios and verdicts are, which is
why the environment fingerprint is recorded with every measurement and a
cross-fingerprint comparison is refused rather than reported.

| Step | Command | Runtime |
| --- | --- | --- |
| test suite | `uv run pytest -q` | ~4 min, first run longer while the image builds |
| the demonstration | `uv run speedproof demo` | ~40 s |
| gate validation | `uv run python -m speedproof.verifyperf.cli` | ~3 min |
| one file, end to end | `uv run speedproof optimise slow.py` | ~4 min (needs a model) |
| baseline vs solution | the `--arm one_shot --arm agent` command above | 15-30 min (needs a model) |
| corpus, 3 candidates | `uv run python -m speedproof.corpus.cli … --limit 3` | ~6 min |

The measurement dominates every figure above. Valgrind costs twenty to a hundred
times native speed, and that is the price of the count being exact.

**Data.** None needs downloading. The corpus manifests are checked in, and the
repositories they name are cloned on first use into `corpus/repos/`.
pypa/packaging is small; the pandas manifest needs a build of about four minutes
per task.

## Without uv

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m speedproof.hackguard
```

Python 3.12 or later. The measurement runs in a container, so the version of
Python you drive it with matters much less than the one inside the image, which
is pinned.

## If something fails

**`docker is not on PATH`** — the measurement needs a container runtime. Nothing
in this repository measures anything without one, deliberately: a measurement
taken in an environment the code under test can configure is not a measurement.

**`nothing to mount at ...`** — a path was passed that does not exist. On macOS,
note that the system temporary directory is not visible inside the container by
default; workspaces are created under `~/.speedproof/` for that reason.

**`asked for a amd64 image and got arm64`** — the Docker daemon ignored
`--platform`, which it does silently when buildx is not configured. The harness
refuses rather than continuing, because a cross-architecture comparison made
that way would compare an architecture against itself and report perfect
agreement.

**A measurement reports a spread instead of `bit-identical`** — something in the
environment is not reproducible. The run says so rather than averaging it away.

## What is checked in, and what is not

Checked in: the code, the tests, the corpus manifests, the controls, and the
demonstration cases.

Not checked in: cloned repositories, built trees, and measurement outputs. They
are large, they are regenerable by the commands above, and a repository that
carries its own results invites the question of whether the results came from
the code.
