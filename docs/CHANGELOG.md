# Improvement changelog

Every entry records what was tried, what it measured, and what was decided.
Experiments that were removed stay in the record, because what they ruled out
is part of the result — and because several of them were plausible enough that
a reader might otherwise try them.

## The arc, in one page

The project began as an agent that optimises code and became, mostly, the
instrument that judges one. That was not the plan; it is where the measurements
led.

**It started with a baseline that could not see the thing it was measuring.**
Counting instructions for a whole process is the obvious first move, and Python
spends 36.4 million of them starting up. Two workloads differing thirty-fold in
work differed by five per cent in total. Subtracting an empty run through the
identical wrapper recovered the real ratio, and that subtraction is the
foundation everything else rests on.

**Then the wrapper doing the subtracting turned out to matter.** A convenient
runner using `argparse` and `importlib` cost 191 million instructions and varied
by about 550 between repetitions. Constant overhead cancels in a subtraction;
its variance does not, and lands whole on the answer. Stripping the runner to
`sys.argv`, `compile` and `exec` dropped the baseline to 49 million and made
repeated measurements bit-identical.

**The same lesson then arrived twice more, in different clothes.** Measuring a
project's own benchmark against an empty baseline left the operation under study
at **0.086%** of what was measured, because the benchmark's class body builds a
500×500 tensor before the benchmark is called; pairing the baseline with the
workload fixed it. And collecting coverage before the import rather than after
attributed **6,652 of 6,700 lines** to every workload alike; starting after the
import left them sharing none. Three times, the fix was the same: exclude what
is common to everything, or the signal drowns in it.

**Then the paired baseline turned out to be somewhere to hide.** Work moved into
module import is carried by both sides and cancels exactly. A module
precomputing its answer read as a **200× improvement** while doing more work in
total. Measuring the import cost separately closed it.

**Meanwhile the correctness gate had never rejected anything, which is
indistinguishable from not having one.** Eight deliberately broken and
deliberately equivalent variants became permanent controls. The first run
accepted two of the six broken ones — and both failures were mine: one fault was
never reached, and the other infected state that never reached an output. The
gate was right all along and the evidence for it was wrong, which nothing but
running it would have shown.

**The agent was then built to published ablations rather than to intuition**,
and two of them reversed what had been planned. Iterating with measured feedback
is the effect, not the profiler. Correctness feedback alone makes results worse.

**And the instrument kept catching its author.** Of seven optimisations written
by hand for the demonstration, four were slower than the code they replaced, and
a fifth needed an import costing 7.6 million instructions against the 2.4
million it saved.

The tables below are the full record.


| Stage | What was tried, and why | Evidence | Decision |
| --- | --- | --- | --- |
| Baseline measurement | Count instructions for the whole process under Callgrind, the obvious first approach. | Interpreter startup is 36.4M instructions. Two workloads differing 30-fold in work differed by 5% in total. First run also came in 62% high from bytecode compilation. | Rejected. Whole-process counting cannot see a workload smaller than Python's own startup. |
| Baseline subtraction | Subtract an empty workload run through the identical wrapper. | Recovered the true ratio: 95,902,294 against 3,131,639 net instructions, bit-identical across five repetitions. | Kept. This is the foundation everything else rests on. |
| Thick wrapper | First runner used `argparse`, `importlib`, `json`, `pathlib`, `typing` for a clean interface. | Baseline rose to 191,077,557 and repetitions varied by ~550 instructions. | Removed. Constant overhead cancels in subtraction; its *variance* does not, and lands whole on the net figure. |
| Thin wrapper | `sys.argv`, `compile`, `exec`, nothing else. Heavy imports deferred to the unmeasured paths. | Baseline fell to 49,428,920. Repetitions bit-identical for both workloads. | Kept. |
| Instruction ratio as a speedup | Report the ratio of net counts as "n times faster". | Published measurement: a list-scan to set-lookup change is 33,243x on instructions against 2,558x on the clock. | Removed. Instruction count prices every instruction as serial while hardware retires several per cycle. The metric answers "did work fall by at least X", not "how much faster". |
| Retained blocks as a second axis | `sys.getallocatedblocks()` after `gc.collect()`, to catch a saving bought with memory traffic (the rustc #77006 pattern: -83.9% instructions, +14.5% wall clock). | Bit-reproducible, effectively free. | Kept, with a correction below. |
| Relative-only memory rule | Flag when retained blocks rise by more than twice the improvement threshold. | **Flagged a genuine 97.4% improvement as a memory trade on its first real run.** Both variants retained only a few hundred blocks, so a trivial absolute difference was a 30.8% relative one. | Revised. A retention difference must now also exceed 4,096 blocks in absolute terms. Lesson: a gate tuned only on ratios will fire on noise whenever the denominator is small. |

## Detector results on the cheat corpus

Each cheat is a patch that a harness measuring only elapsed time would accept.

| Case | Verdict | Why |
| --- | --- | --- |
| Honest algorithmic win | improved | Work fell 97.4%, answers identical. Accepted. |
| Fast but wrong answer | not_equivalent | Canonical hashes differ. Correctness is checked before anything else. |
| Cached across runs | regressed | A fresh process per measurement makes the cache worthless; the lookup costs 5.5% more. |
| Work deferred to a generator | regressed | Forcing the result inside the measured region puts the work back, plus generator overhead: 67.6% more. |

## Corpus construction

| Stage | What was tried, and why | Evidence | Decision |
| --- | --- | --- | --- |
| Repository selection by benchmark suite | Follow the published rule: pick repositories that ship a benchmark suite, so workloads come from the project rather than from us. | xdsl qualifies, and 96 of its 100 retrieved tasks are in scope with 93 applying cleanly. | Kept as a first filter. |
| Assuming the suite is usable | Take "the repository has a benchmark suite" to mean the tasks have workloads. | **Only 2 of 96 have a suite that runs in memory.** The other 94 have a command-line script that walks `.mlir` files on disk and shells out to an external tool; the suite was rewritten in 2025. | Rejected. A suite has to exist at the base commit of each task and be callable without a filesystem, not merely exist in the project today. |
| Matching benchmarks to patches by name | Assume the lexer, parser and printer benchmarks cover changes to lexer, parser and printer code. | 2 of 93 tasks patch source those benchmarks name-match. | Rejected. Selection has to be driven by coverage: a workload that does not execute the changed lines measures nothing, however well it is measured. |
| Second repository | `pypa/packaging`: pure Python, 1.6 MB, and it already pins `PYTHONHASHSEED=0` in its own benchmark configuration. | Benchmark suite added 2026-03; 22 `perf:` commits after that date, 15 of them changing the library rather than the test harness. | Adopted. The surviving commits are exactly the kind this metric reads well: adding `__slots__`, precompiling a pattern, caching a lookup. |

## Measuring a project's own benchmarks

| Stage | What was tried, and why | Evidence | Decision |
| --- | --- | --- | --- |
| Empty baseline on a corpus workload | Reuse the baseline that worked for purpose-built workloads: subtract an empty script to remove interpreter startup. | Net of **27,142,094,479** instructions for lexing 100 operations. Bit-identical across repetitions and across two source trees, and almost entirely a 500x500 tensor built at class-definition time. | Rejected. Perfectly reproducible and measuring the wrong thing. An optimisation halving the lexer would have moved this by less than the threshold for calling anything a change. |
| Paired baseline | Generate the workload twice, identical but for the benchmark call, so the import cost appears on both sides and subtracts away exactly. | Net falls to **23,338,700**, still bit-identical. The operation under study was 0.086% of what the empty baseline reported. | Kept. Reproducibility was never the problem; relevance was. |
| Discovery by import | Import each benchmark module to enumerate its methods. | Importing runs the class body, which is the expensive part -- the same 27 billion instructions, paid during discovery. | Rejected in favour of parsing the source. 52 benchmarks found in the xdsl suite without executing any of them. |

## Validating the correctness gate

| Stage | What was tried, and why | Evidence | Decision |
| --- | --- | --- | --- |
| One-sided validation | Report what fraction of broken variants the gate rejects. | A gate that rejects everything scores 100%. The number cannot distinguish a strong gate from a useless one. | Rejected. Both directions are reported as a pair: broken variants rejected, and real optimisations accepted. |
| Generated mutants alone | Use a mutation tool's stock operators to produce the broken variants. | Just et al. (FSE 2014) found the largest class of real faults that couple to no generated mutant is algorithm modification or simplification — which is what a performance optimisation is. | Rejected as the primary instrument. Controls are hand-written to the fault distribution this benchmark contains: precision, caching, aliasing, ordering, edge cases. |
| First validation run | Run the eight controls past the gate. | **2 of 6 broken variants were accepted.** Both were defects in the controls, not the gate: one fault was never reached, because the data contained no single-row group for its fast path to mishandle; the other infected state and then converted the result back to single precision, collapsing the error before it reached the output. | Controls corrected; gate unchanged. Second run: 6/6 rejected, 2/2 accepted. The lesson is that the gate was right all along and the evidence for it was wrong, which nothing but running it would have shown. |
| Crash counted as rejection | Record a control that fails to run as rejected, on the reasoning that it did not pass. | Schuler and Zeller removed every assertion from seven test suites and the mutation score fell only to 43%, because crashes were being counted as kills. The first version of this code had the same defect. | Fixed. Accepted, rejected and unjudged are recorded separately; only a comparison counts as the gate working, and unjudged controls stay in the denominator so a set that mostly fails to run cannot score well on the remainder. |
| Coverage started before the import | Start coverage, import the benchmark module, construct, call. The obvious order. | Four xdsl workloads shared **6,652 of ~6,700** covered lines and differed by as few as four, because every module's import-time execution was attributed to whichever workload triggered it. | Rejected. Coverage now starts after the import and construction, so it records the call and nothing else: the same four workloads then share **zero** lines. Patches to import-time code are handled by a separate escalation rule rather than by coverage that cannot attribute them. |
| First corpus run | Run the pipeline end to end across two repositories. | xdsl: 0 of 25 validated, and only 1 of 25 measurable at all — nineteen tasks predate any callable benchmark. packaging: 1 of 6 validated, 3 of 6 measurable. The validated task reproduces `perf: add __slots__ to token classes` at **+3.01%**, deterministic, outputs unchanged. | Pipeline kept; xdsl retired as a source. The difference is not the pipeline but the repositories: a project can have benchmarks and have optimisation commits without the two ever meeting, which is what the earlier survey could not detect. |
| Paired baseline alone | Subtract a baseline carrying the same imports, so the measurement is of the benchmarked call. | Correct, and a hiding place: a module precomputing its answer at import had both sides carry the cost, cancelling exactly. Measured, that reads as a **200x improvement** — net Ir 1,334,809 to 6,585 — while the program does *more* total work, 1,827,626 to 1,885,271. | Kept, with the hole closed. Every measurement now records the module's import cost, and a saving is credited only when the whole program does less work. A cheaper import still counts; an unknown import cost returns unknown rather than assuming the work stayed put. |

## The main failure mode

Not the agent's — the instrument's.

A measurement can be perfectly reproducible and measure the wrong thing, and
nothing about the reproducibility warns you. Every serious error in this project
had that shape. The empty baseline gave bit-identical numbers across every
repetition while the operation under study was 0.086% of them. The coverage map
was exact and attributed almost every line to every workload. The paired
baseline cancelled the import so precisely that moving work into it registered
as a two-hundredfold win.

In each case the number was stable, the code was correct, and the conclusion was
false. That combination is why the field's published results are worth
doubting: a wall-clock harness is *less* precise than any of these and is
trusted more, because precision is the property people check for and relevance
is not.

The practical consequence is that every gate in this project has to be shown
firing. A check that has never rejected anything and a check that cannot reject
anything look identical from the outside, which is why the controls are
permanent, re-run on every change, and reported in both directions.

## The hot take

Wall-clock benchmarking made this field's results unfalsifiable, and the
response has been to build better agents rather than better instruments.

Counting instructions costs nothing and settles it. The reason nobody does it is
not that it is hard — it is that determinism removes the wiggle room, and a
number that cannot move in your favour is a number you have to live with.
