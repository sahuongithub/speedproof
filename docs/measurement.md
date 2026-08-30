# How a measurement is taken

The number this project reports is the count of instructions retired while
executing a workload, minus the count retired while executing an empty
workload through the identical wrapper.

## Why subtract a baseline

Starting CPython and reaching the first line of user code costs tens of
millions of instructions. A workload doing a few million instructions of real
work is a rounding error next to it. Measured without subtraction, two
variants that differ by a factor of thirty in the work they perform differ by
about five per cent in their totals — which is the difference between a result
and a non-result.

## Why the wrapper has to be thin

Constant overhead cancels in the subtraction. Its *variance* does not: it lands
whole on the net figure. An earlier version of the runner used `argparse`,
`importlib`, `json` and `pathlib`, which cost about 155 million instructions and
carried a few hundred instructions of run-to-run jitter from filesystem stats
and path scanning. Replacing all of it with `sys.argv`, `compile` and `exec`
dropped the baseline to about 49 million and made repeated measurements
bit-identical.

Measured on aarch64, CPython 3.12.14, Valgrind 3.24.0:

| runner                          | baseline Ir | repeated measurements |
| ------------------------------- | ----------- | --------------------- |
| argparse + importlib + json     | 191,077,557 | spread of ~550        |
| sys.argv + compile + exec       |  49,428,920 | bit-identical         |

## The five determinism controls

1. `PYTHONHASHSEED=0` — removes hash-order variation.
2. `gc.disable()` — the collector's scheduling otherwise makes the count depend
   on allocation history rather than on work performed.
3. A warm bytecode cache — the first execution of any Python file pays an extra
   compilation that would otherwise land entirely in the first repetition.
4. `--cache-sim=no --branch-sim=no` — count instructions, nothing else.
5. Baseline subtraction, as above.

## What this metric cannot see

Instruction count is a faithful proxy for work done, and an unfaithful proxy
for elapsed time. It is blind, and sometimes actively misleading, for
optimisations whose benefit is cache locality, branch prediction, vectorisation,
system-call or I/O batching, or parallelism — Valgrind serialises threads, so a
genuine scaling improvement reads as a regression. Garbage-collection pressure
is excluded too, since the collector is disabled for determinism.

Every one of those categories is filtered out of the corpus at construction
time, so no task depends on an effect the metric cannot measure.

## Instruction count is a direction, not a factor

Instruction count systematically overstates how much faster an algorithmic
change makes something. It prices every instruction as if it were executed
serially, while the hardware retires several per cycle — and the loops that
naive code spends its time in are exactly the ones a processor pipelines well.
A measured replacement of a linear list scan by a set lookup came to 33,243x on
instructions against 2,558x on the clock: the right direction, overstated
thirteenfold.

So the benchmark asks "did the work fall by at least this much", which
instruction counting answers exactly, and never "how many times faster is it",
which it answers badly. `improves_on(baseline, threshold)` is the supported
comparison. `work_ratio_to` exists for diagnostics and is not a speedup.

## The second axis: allocation volume

`sys.getallocatedblocks()`, read after a `gc.collect()`, is bit-reproducible
and free. It is worth recording on every measurement because it catches the one
failure mode instruction counting actively rewards: trading computation for
memory. The clearest published case is rustc PR #77006, which cut instructions
by 83.9% and made the compiler 14.5% slower on the clock, because the change
bought its instruction saving with memory traffic.

A patch that lowers instructions while raising allocations is flagged for
review rather than accepted.

## Correlation between instruction count and elapsed time

No published study measures this for Python, so this project generates one:
paired before/after optimisations measured both ways, on one machine and one
architecture. Across twelve pairs the log-log Pearson correlation is 0.998 with
a Spearman rank correlation of 0.874; excluding the memory-locality cases,
which the metric is known to be blind to, rank correlation rises to 0.976.

The same corpus scored by counting executed bytecodes instead of machine
instructions gives a Pearson correlation of -0.185 — not a weaker signal but an
anti-correlated one. Bytecode counting is not a usable substitute.

These are self-generated numbers on a small sample and one architecture. They
establish direction and identify the failure modes; they are not a substitute
for a published study, and the write-up says so.

## Running on more than one architecture

Counts are reproducible within an architecture and are not portable between
them: the instruction stream differs, and libraries that dispatch on detected
CPU features may select different code paths. So a second architecture is used
to check that *verdicts* agree, never that numbers match, and a `Fingerprint`
refuses a comparison whose two sides came from different machines.

One warning, learned by walking into it. `docker build --platform` does not
fail when the daemon cannot honour it — without buildx configured it quietly
produces an image for the host architecture instead. An amd64 image built this
way on an arm64 host is an arm64 image with a misleading tag, and measuring
with it would compare an architecture against itself and report perfect
agreement. The builder now inspects what it actually produced and refuses to
continue on a mismatch.
