# Improvement changelog

Every entry records what was tried, what it measured, and what was decided.
Experiments that were removed stay in the record, because what they ruled out
is part of the result.

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
