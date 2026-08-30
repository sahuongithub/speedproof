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

## Materialising a task

Both sides are produced as git worktrees off one local clone, so the before and
after trees exist side by side and neither is a mutation of the other. The
patch is applied rather than the merge commit being checked out, because a
merge commit carries everything else that landed with it and the patch carries
only the change being measured.

Blobs are fetched on demand. The history is wanted for its commits, not for
every version of every file.
