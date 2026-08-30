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
