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
