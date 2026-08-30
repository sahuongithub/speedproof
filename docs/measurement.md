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

## Two ways to exclude interpreter startup

**Baseline subtraction** is the default. Measure the workload, measure an empty
workload through the identical wrapper, subtract. It needs nothing beyond
Valgrind, and it is exact whenever the workload is large next to the roughly 49
million instructions Python spends starting up.

It degrades when the workload is small, because the net figure is then the
difference between two numbers near fifty million, and a few instructions of
wrapper jitter become a large fraction of the answer.

**Region counting** is the alternative for that case. The workload marks its own
region with `speedproof.verifyperf.region.counted()`, and Callgrind is started
with `--instr-atstart=no` so that only the marked block is counted. Interpreter
startup never enters the number and the wrapper's size stops mattering. The
cost is a compiled shim in the image — Callgrind's controls are magic
instruction sequences rather than a callable library, so they have to be
wrapped in C and reached through ctypes — which is why this is not the default.

The shim is a no-op outside Valgrind, so a workload written against it runs
normally during development.

## Cross-architecture result

The suite was run natively on both architectures: arm64 in a container on an
Apple M1, and x86_64 on a shared GitHub-hosted runner (AMD EPYC 7763, Azure,
kernel 6.17). The runner is noisy, shared, and entirely outside the author's
control, which is the point.

| | arm64 | x86_64 | difference |
| --- | ---: | ---: | ---: |
| baseline, net instructions | 95,363,971 | 104,849,717 | +9.9% |
| candidate, net instructions | 2,511,929 | 2,754,627 | +9.7% |
| work removed | 97.37% | 97.37% | +0.01 pp |

Three things hold, and each is worth stating separately.

**Counts are not portable.** The same source needs about ten per cent more
instructions on x86_64 than on arm64. This is expected — different instruction
sets do the same work in a different number of steps — and it is why a
`Fingerprint` refuses a comparison whose two sides came from different
machines.

**Ratios are portable.** The fraction of work removed agrees to within a
hundredth of a percentage point, because the architectural difference is
common to both sides of the comparison and divides out.

**Verdicts are portable.** All four cases, one genuine improvement and three
cheats, received the same verdict on both architectures.

**Checksums are identical.** The canonical encoding depends only on the values
computed, so correctness transfers exactly across architectures even though
counts do not.

The determinism claim also survived contact with shared infrastructure: running
the entire suite twice on the same runner returned identical counts for every
case. A noisy machine changes how long the measurement takes and not what it
reports.

## The baseline has to be paired with the workload

Subtracting an empty script removes interpreter startup. That is the right
baseline for a workload written for the purpose, and the wrong one for a
benchmark taken from a project.

A benchmark class under the usual convention builds its inputs when the class
is defined, so importing the module does the work before the benchmark is ever
called. Measuring one xdsl lexer benchmark against an empty baseline gave a net
of **27,142,094,479 instructions**, almost all of which was constructing a
500x500 tensor at class scope. The number was bit-identical across repetitions
and across two source trees, so it was perfectly reproducible -- and useless,
because the operation under study was a fraction of a per cent of it. An
optimisation that halved the lexer would have moved that total by less than the
threshold for calling anything a change.

The fix is to generate the workload as a pair. Both files import the same
module, construct the same object and run the same `setup()`; only one of them
calls the benchmark. Everything the import does is common to both and subtracts
away exactly, leaving the call being studied.

Measured, on the same benchmark and the same task:

| | Instructions |
| --- | ---: |
| Workload total | 27,192,889,049 |
| Paired baseline (same imports, no call) | 27,169,550,349 |
| **Net, the lexing itself** | **23,338,700** |
| Net against an empty baseline instead | 27,142,094,479 |

The operation under study was **0.086%** of what the empty baseline reported.
Everything else was the module building its inputs. Both figures are
bit-identical across repetitions; the difference between them is not precision
but relevance, and no amount of reproducibility rescues a number that is
measuring the wrong thing.

This is the same principle as the thin wrapper, one level up. There, the
runner's own imports had to be small because their *variance* landed on the net
figure. Here, the benchmark module's imports can be arbitrarily large so long
as they appear identically on both sides of the subtraction.

## The agent's workspace

The agent edits its own tree, never the corpus checkout. Three separate reasons,
and the third is the one that matters: a failed run would otherwise leave the
tree modified so the next task starts from something other than the commit it
names; two tasks could not run at once; and an agent editing a file the harness
later reads has, in a small way, reached the thing that judges it.

The copy is made with hard links, so it costs no new space at all -- measured on
a corpus tree, the tree alone and the tree plus its clone both come to 8 MB --
and takes under half a second. That matters because a built pandas checkout runs
to hundreds of megabytes and the agent may touch three files in it.

Breaking the link on write is the part that has to be right. Opening a
hard-linked file and writing to it modifies every name that file has, including
the corpus's own, silently and with no error, corrupting subsequent measurements
rather than failing them. Every write therefore goes to a new file which is
renamed into place, so the original is untouched by construction rather than by
care. Writes to the generated workload, to git metadata, or to any path
resolving outside the workspace are refused.

## Where a paired baseline can hide work

Pairing the baseline with the workload is what makes the measurement about the
benchmarked call rather than about importing a module. It is also somewhere to
hide. Work moved into the import is carried by both sides of the subtraction
and cancels exactly, so an optimisation that computes its answer before the
measurement begins is not merely under-penalised — it is invisible.

Measured on a module that precomputes its result at import:

| | net Ir | import cost |
| --- | ---: | ---: |
| honest | 1,334,809 | 492,817 |
| precomputed at import | **6,585** | **1,878,686** |

That reads as a two-hundredfold improvement. The program does more work in
total: 1,885,271 instructions against 1,827,626.

So every measurement now records what the module costs merely to import,
obtained by running an empty script through the same wrapper, and a saving in
the measured region is credited only when the program as a whole also does less
work. A change that makes the import itself cheaper still counts — that is real
work — and a comparison where either side did not report an import cost returns
unknown rather than assuming the work stayed put.

This is the failure that the surveyed literature reports as the most common
by a wide margin: of eighteen hacks found in one manual review, fourteen were
caching or persistent state, and import-time effects are noted as surviving
even harnesses that run each repetition in a fresh process.
