# The corpus

A task is a pair of commits from a real project: the state before a performance
change a human made, and that change as a patch. The repository supplies the
workload and the correctness tests, so nothing about a task is authored here.
That matters more than it sounds: a benchmark whose author also wrote the
answers is, in part, measuring itself.

## Where the tasks come from

Candidate optimisations are drawn from published mining of merged pull
requests. Each row carries the repository, the commit the change was based on,
the patch, and a classification of what kind of optimisation it is.

The first repository ingested is **xdslproject/xdsl** — a compiler framework
that is pure Python, has no compiled extensions, ships a benchmark suite, and
whose workloads are parsing, printing and rewriting: CPU-bound, deterministic,
free of input and output. That combination is unusually well suited to
measurement by instruction count.

## The funnel, measured

| Stage | Tasks |
| --- | ---: |
| Mined for this repository | 136 |
| Retrieved | 100 |
| Have a benchmark suite at the base commit | 100 |
| In scope for instruction counting | 96 |
| Patch applies cleanly at the base commit | **93** |

Four tasks were excluded as out of scope, all classified as parallelisation.
Valgrind serialises threads, so a change that genuinely scales across cores is
recorded as a regression; judging such a change by instruction count would not
be strict, it would be wrong. Three further tasks were dropped because the
recorded patch no longer applies at the commit it names.

The surviving 93 break down as:

| Classification | Tasks | Note |
| --- | ---: | --- |
| remove_or_reduce_work | 37 | |
| micro_optimizations | 19 | |
| use_better_algorithm | 18 | |
| use_higher_level_system | 6 | |
| cache_and_reuse | 6 | |
| use_lower_level_system | 4 | flagged for review |
| use_better_data_structure_and_layout | 4 | flagged for review |
| other | 2 | |

The two flagged categories are in scope but are read individually before use,
because whether the metric can see the benefit depends on what the change did.
Removing a layer of indirection shows up as fewer instructions; improving cache
locality without removing work does not show up at all.

## A repository having a benchmark suite is not enough

The obvious way to choose repositories is to look for one that ships a
benchmark suite, since that supplies workloads nobody involved in the
measurement wrote. It is the rule the published mining pipelines use, and it is
not sufficient.

A suite has to exist *at the commit each task is based on*, and it has to be
callable in memory. Checking that for xdsl produced an uncomfortable number:

| | Tasks |
| --- | ---: |
| Have some benchmark directory at the base commit | 96 |
| Have the modern suite, with workloads built in memory | **2** |
| Have only the older scripts, which walk files on disk and shell out to an external tool | 94 |

The suite was rewritten in 2025. Before that it was a command-line script that
parses whatever `.mlir` files it is pointed at, which is not a workload that can
be measured in a sealed container without also measuring the filesystem.

So the selection rule is stricter than "the project benchmarks itself":

> A task is usable when the project's own benchmark suite exists at that task's
> base commit, runs in memory, and exercises the code the patch changes.

The third clause matters as much as the first two. Checking which tasks patch
code that the lexer, parser or printer benchmarks actually execute found two of
ninety-three. A workload that does not run the changed lines measures nothing,
however carefully it is measured, so benchmark selection has to be driven by
coverage rather than by names.

## Materialising a task

Both sides are produced as git worktrees off one local clone, so the before and
after trees exist side by side and neither is a mutation of the other. The
patch is applied rather than the merge commit being checked out, because a
merge commit carries everything else that landed with it and the patch carries
only the change being measured.

Blobs are fetched on demand. The history is wanted for its commits, not for
every version of every file.

## Choosing repositories, and getting it wrong twice

Applying the stricter rule to eight candidates:

| Repository | Verdict | Suite since | Timed methods | Perf signal |
| --- | --- | --- | ---: | ---: |
| tobymao/sqlglot | usable | 2021-07 | 1 | 42 |
| networkx/networkx | usable | 2023-08 | 58 | 21 |
| pypa/packaging | usable | 2026-03 | 20 | 15 |
| Textualize/rich | usable | 2022-03 | 32 | 12 |
| xdslproject/xdsl | usable | 2023-03 | 60 | 11 |
| python-attrs/attrs | rejected | 2024-07 | 0 | 4 |
| more-itertools | rejected | — | 0 | 0 |
| pyparsing | rejected | — | 0 | 0 |

The perf-signal column is a prefilter count and not a count of genuine
optimisations. Matching keywords in commit subjects runs at roughly ten to
thirty per cent precision, because a project whose subject matter is
optimisation discusses optimising constantly without changing its own speed.
Around a hundred candidates is the right order of magnitude to start from for a
target of fifteen to twenty-five validated tasks.

The first version of this survey reported two usable repositories rather than
five, and both extra rejections were the gate's fault:

**Reading a checked-in file is not reaching outside the process.** `open(` was
treated as disqualifying, which rejected a repository for loading the sample
data sitting beside its own benchmarks. A fixed file inside a sealed container
is as deterministic as a string literal. What cannot be sealed is *discovering*
inputs at run time, or calling another program — so the check now names
`glob`, `subprocess`, `os.listdir` and their relatives, and leaves plain reads
alone.

**Recognising one benchmark convention rejects projects that use another.** The
check looked only for asv's `time_*` naming and so scored a repository with
forty-two performance commits as having no benchmarks at all, because it uses
pyperf. It now recognises asv, pytest-benchmark and pyperf.

Both are the same mistake in different clothes, and it is the mistake this
project is about: a gate tuned to reject will reject things it should not, and
the only way to know is to check its refusals as carefully as its acceptances.

## Coverage has to measure the call, not the import

The selector needs to know what each workload reaches. Collecting that turns
out to have the same trap as measuring instructions did, one level up.

The obvious implementation starts coverage, imports the benchmark module,
constructs the class and calls the method. It produces a map that is technically
correct and useless for discrimination, because everything a module does when
it is imported gets attributed to whichever workload happened to trigger it —
and in a suite where every module imports the same package, that is nearly
everything.

Measured on four xdsl benchmarks:

| | Coverage started before the import | Coverage started after |
| --- | ---: | ---: |
| Lines shared by all four workloads | 6,652 | **0** |
| Unique to `Lexer.time_constant_100` | 4 | 4 |
| Unique to `Parser.time_constant_100` | 511 | **762** |

Before the change the four workloads agreed on 6,652 of roughly 6,700 lines and
differed by as few as four. After it they share nothing, and each one's coverage
is the code it actually exercises: 88 lines for the lexer, 854 for the parser,
309 for the printer.

The consequence is that a patch to code which only runs at import is invisible
to this map. That is deliberate rather than a gap — the selector escalates such
patches to the whole suite by a separate rule, which is both simpler and safer
than trying to see them in coverage that cannot attribute them.

Coverage is collected per workload in its own process, and on the base tree
only. Sharing a process lets an earlier workload's imports make a later one
look as though it touches nothing, and the patched tree may not contain the
lines the patch removed, which would misalign the diff's line numbers.
