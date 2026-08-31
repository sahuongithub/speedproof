# speedproof

An agent that makes code faster, and a harness that can prove it did.

## Try it

```bash
uv sync --extra dev
uv run speedproof optimise --example slow.py    # a deliberately slow file
uv run speedproof optimise slow.py              # watch an agent improve it
```

Four minutes, and you will see an agent propose a change, the harness measure
it, and a result: on the bundled example it removes **32% of the work** and the
answers are proved unchanged.

Needs Docker. Needs no API key for anything except the agent itself.

### Then, depending on what you want

| | |
| --- | --- |
| **Does it work?** | the two commands above |
| **Can I trust it?** | `uv run speedproof demo` — five attempts, three of them cheats |
| **Is the gate real?** | `uv run speedproof verify` — it is shown rejecting things |
| **How is it built?** | [docs/measurement.md](docs/measurement.md), [docs/correctness.md](docs/correctness.md) |
| **What failed on the way?** | [docs/CHANGELOG.md](docs/CHANGELOG.md) — including four of my own optimisations that were slower than the code they replaced |

---

## The problem

An AI agent told to optimise code will find that making the number go down is
easier than making the code faster. It is not being devious; it is doing what it
was asked. The published record of this field is largely a record of that
happening:

- In one benchmark's own notes, agents **forged the results file in 738 of 862
  containers** — 85.6% — because the verdict was read from a file written inside
  the sandbox by the process being judged. The recorded fix was to delete the
  check.
- Of eighteen hacks found in one manual review, **fourteen were caching or
  persistent state**.
- Of the four published benchmarks in this area, two compare no outputs at all,
  one captures them and treats differences as *"informational only"*, and one
  generates its own assertions, some of which contain no assertion.

And the measurements themselves are shakier than they look. Changing only the
size of an unused environment variable has been shown to swing a measured
speedup between 0.91× and 1.10×, while a survey of 133 papers found a median
claimed speedup of 10% — smaller than that bias.

## What this does

It counts the instructions a program retires, inside a container the code under
test cannot configure, with the counter outside the interpreter entirely. The
result is an integer rather than an interval, it reproduces exactly, and it
costs nothing to run.

Then it uses that to judge an agent.

## The thing to look at first

```
uv run python -m speedproof.hackguard
```

Five attempted optimisations, measured twice. The **naive** column is what a
harness that times the code and compares the numbers would conclude — which is
what every published benchmark in this area does. The **strict** column also
asks whether the answers match and whether the work went away rather than
moving somewhere the measurement cannot see.

```
A real optimisation: ask forgiveness, not permission
  naive   accepted, +21.3%
  strict  ACCEPTED   work fell 21.3%, answers identical

Computes the answer before the measurement starts
  naive   accepted, +99.9%
  strict  REJECTED   the work moved into module import rather than going away

Very fast, and wrong
  naive   accepted, +98.6%
  strict  REJECTED   it computes different answers

Returns a promise instead of a result
  naive   no change, -0.2%
  strict  no change  the result is materialised inside the measured region

Cheaper arithmetic, quietly less accurate
  naive   no change, -166.8%
  strict  REJECTED   it computes different answers

  the naive harness accepted 2 of 4 attempts that are not optimisations
  this one judged 5 of 5 cases correctly
```

None of the cheats was invented for this. Each cites the published benchmark
that documented it.

## Who this is for

A team that wants an agent to speed up their code, and cannot afford to find out
six months later that it did not. The output is a patch with a certificate: how
much work it removed, that the answers are unchanged, and that the saving is not
an artefact of where the measurement was taken.

---

## How the measurement works

Three properties, each established by measuring rather than by assuming.

**It is exact.** Thirteen measurements of three programs, every repetition
bit-identical:

| | instructions |
| --- | ---: |
| interpreter startup alone | 36,369,334 |
| a quadratic list build | 132,271,628 |
| the same work, done linearly | 39,500,973 |

**It reproduces on hardware we do not control.** The same suite on an Apple M1
and on a shared GitHub runner:

| | arm64 | x86_64 | difference |
| --- | ---: | ---: | ---: |
| baseline, net instructions | 95,360,370 | 104,847,849 | +9.9% |
| candidate, net instructions | 2,508,272 | 2,752,846 | +9.8% |
| **work removed** | **97.37%** | **97.37%** | **+0.00 pp** |

Counts are not portable across architectures; ratios and verdicts are. Running
the whole suite twice on the same noisy shared runner returned identical counts
for every case — a busy machine changes how long a measurement takes, not what
it reports.

**The gate has been shown to reject things.** A correctness check that has never
rejected anything is indistinguishable from no check, so eight deliberately
broken and deliberately equivalent variants are kept as permanent controls and
re-run on every change:

| | |
| --- | --- |
| broken variants rejected | 6 / 6 |
| real optimisations accepted | 2 / 2 |

Both numbers are needed. A gate that rejects everything scores perfectly on the
first.

## How the agent works

The agent proposes patches. It never measures one. Every number it sees is
produced by the harness in a container it cannot reach, and the verdict on its
work is reached the same way — a separation enforced by a test asserting that
the controller module never imports the measurement.

Each design choice traces to a published ablation rather than to what sounds
sensible, because several things that sound sensible are measured to make
results worse:

- **The loop is the effect, not the profiler.** Iterating with measured feedback
  lifted a frontier model from 20.6 to 33.3 on the surveyed benchmark with no
  profiler at all; the profiler adds three points on top.
- **The harness profiles, never the agent.** Telling an agent to profile and
  letting it choose when scored *below* the plain baseline, 17.6 against 20.6.
- **Correctness feedback alone makes things worse**, 33.3 down to 24.5: the agent
  turns careful and stops finding anything.
- **The agent does not decide when it is finished.** Three quarters of
  trajectories in the surveyed work stop early with budget remaining.
- **The best round is kept, not the last.** Published turn-by-turn figures end on
  a regression.

## The first end-to-end result

One task, three arms, on `perf: add __slots__ to token classes` from
pypa/packaging:

| | instructions | work removed |
| --- | ---: | ---: |
| the code as it stood | 33,757,056 | — |
| **the maintainer's patch** | 32,740,814 | **3.01%** |
| one prompt | 29,372,743 | 12.99% |
| one prompt, with the profile | 32,094,655 | 4.92% |
| **the loop, three rounds** | **28,986,013** | **14.13%** |

All three passed the correctness gate. The loop found its best answer in round
one and got worse in rounds two and three, so the controller kept round one —
the best-not-last rule earning its place on a real run.

At one task, the loop and the single prompt tie, and the report says so: the
smallest difference this corpus could resolve is larger than the one observed.
That is not evidence the loop does nothing; it is evidence that one task cannot
answer the question.

## How a result is scored

Against the maintainer who did the work first:

    expert_fraction = log(base / arm) / log(base / human)

One is parity with the person who knew the codebase. That turns the question
from *did a number move* into *how much of what an expert found did the agent
find*.

The threshold score most benchmarks use cannot work at this corpus size. Against
a large true effect, ten tasks give a **0.04** chance of detecting it and twenty
give 0.32. So arms are compared paired, on tasks both answered, with the error
clustered by repository — tasks from one project share a build, a house style and
often the same hot loops — and **the smallest difference the corpus could have
resolved is reported before the difference observed**. A corpus that cannot
resolve a difference has not failed to find it; it was never able to ask.

---

## Running it

Requires Docker. Nothing else — the measurement image is built on first use and
pins its base by digest, because a moving base image would silently change every
count.

```bash
uv sync --extra dev
uv run pytest -q                          # the test suite
uv run python -m speedproof.hackguard     # the demonstration above
uv run python -m speedproof.verifyperf.cli    # validate the gate, then measure
```

See [docs/REPRODUCTION.md](docs/REPRODUCTION.md) for a clean-machine walkthrough,
[docs/measurement.md](docs/measurement.md) for why the measurement is built this
way, [docs/correctness.md](docs/correctness.md) for how a patch is judged
correct, and [docs/CHANGELOG.md](docs/CHANGELOG.md) for what was tried, what it
measured, and what was thrown away.

## What went wrong while building it

The changelog records every experiment, including the ones that failed. Four are
worth knowing about because each was a plausible design that measurement
refuted:

**An empty baseline made a real signal 0.086% of the measurement.** Subtracting
interpreter startup is right for a purpose-built workload and wrong for a
project's own benchmark, whose class body may build a 500×500 tensor before the
benchmark is called. The number was bit-identical and useless.

**Coverage attributed 6,652 of 6,700 lines to every workload alike**, because it
was started before the import rather than after. Reproducibility was never the
problem; relevance was.

**A paired baseline is somewhere to hide.** Work moved into module import is
carried by both sides and cancels exactly: a module precomputing its answer read
as a **200× improvement** while doing more work in total.

**Seven of my own hand-written optimisations, four were slower** than the code
they replaced, and one that was faster in the measured region needed an import
costing 7.6M instructions against the 2.4M it saved. The harness rejected it and
was right to.

## The hot take

Wall-clock benchmarking made this field's results unfalsifiable, and the
response has been to build better agents rather than better instruments.
Counting instructions costs nothing and settles them. The reason nobody does it
is not that it is hard — it is that determinism removes the wiggle room, and a
number that cannot move in your favour is a number you have to live with.
