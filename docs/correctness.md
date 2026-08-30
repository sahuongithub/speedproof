# Deciding whether a patch is correct

A performance benchmark needs an answer to "is the code still right", and that
answer is harder to get than it looks. The workloads a project ships are timing
harnesses: under the common convention they are methods named `time_*` that
return `None`. Comparing what they returned before and after a patch therefore
compares `None` with `None`, which passes for every patch ever written,
including one that deletes the function being measured.

That failure is not hypothetical. Surveying how the published benchmarks in
this area decide correctness:

- Two of them compare no outputs at all.
- One captures return values properly and then does not act on the comparison.
  Its own code says regressions are *informational only*, and publication is
  gated on speedup alone. Its default capture filter names two modules from one
  repository, so on any other project it captures nothing and reports success
  over an empty set.
- One generates its own equivalence assertions, and a number of the generated
  tests contain no assertion at all.

The most useful detail comes from that third project's own notes on failure
modes: agents **forged the results file in 738 of 862 containers**, because the
verdict was read from a JSON file written inside the sandbox by the process
being judged. The remediation recorded was to remove the check.

## The rule this project follows

The same rule already applied to timing applies to correctness, and for the
same reason:

> The verdict is computed by the harness, from values the harness read, in a
> process the patch cannot reach. It is never a file the container hands back.

Concretely:

1. **The comparison runs outside the measured process.** Values are captured,
   returned to the host, and compared there. A patch cannot influence the
   comparison because the comparison does not run where the patch runs.
2. **Equality is decided on a canonical encoding**, never by calling `__eq__`
   on an object the patch produced. An object that claims to equal everything
   cannot forge agreement; it cannot be encoded at all.
3. **The gate is binding.** A patch whose outputs differ is rejected, not
   annotated. A task where no output could be captured is unmeasurable and is
   excluded from the corpus, rather than counted as a pass.
4. **The gate is itself tested.** A correctness check that has never rejected
   anything is indistinguishable from no check. Deliberately broken versions of
   each task are kept as permanent negative controls: if the gate stops
   rejecting them, the gate has regressed.

Point four is what separates this from the benchmarks above. Each of them has,
somewhere, a correctness mechanism that was well built and then wired up so
that it could never fail. The only way to know which kind you have is to feed
it something wrong and watch.

## Validating the gate, and what validation caught

The control set is deliberately two-sided. Six variants are semantically broken
and the gate must reject every one; two are genuine optimisations or
observably-identical rewrites and the gate must accept both. Reporting only the
first number would be meaningless, because a gate that rejects everything
scores perfectly on it while being useless.

| | Result |
| --- | --- |
| Soundness — broken variants rejected | 6/6 |
| Completeness — equivalent variants accepted | 2/2 |

The fault classes are written to the fault distribution this benchmark actually
contains, rather than to what generic mutation operators happen to produce:
precision weakened, cache key incomplete, cached object aliased, defensive copy
dropped, ordering made unstable, edge case skipped, comparison flipped, work
deleted. Just et al. (FSE 2014) examined the real faults that generated mutants
fail to couple to, and the largest single category was *algorithm modification
or simplification* — which is the definition of a performance optimisation. A
generated mutant population systematically under-samples the faults this
benchmark is made of, so the controls are hand-written to that distribution and
kept permanently.

### The first run failed, and the failures were in the controls

Two of the six broken variants were accepted. Neither was a defect in the gate.

**A fault that is never reached cannot be detected by anything.** The
comparison flip guarded a fast path for single-row groups, and the control data
had no single-row groups — every group had at least two hundred. The mutated
branch never executed. Fixed by adding a singleton group to the data.

**A fault can infect state and still not reach the output.** The precision
variant accumulated in single precision, and then converted the total back to
single precision at the end. The intermediate values genuinely differed; the
final conversion collapsed the accumulated error back onto the original value,
so nothing observable changed. Fixed by removing the final conversion, which is
what a real precision-weakening optimisation would look like anyway.

These are the first two stages of the RIPR model — a fault must be **reached**,
must **infect** state, must **propagate** to an observable value, and must be
**revealed** by whatever the oracle looks at. Both failures were mine, and both
were invisible until something ran.

That is the argument for keeping the controls permanently rather than checking
the gate once. The gate was correct throughout; the evidence for it was not,
and only running it showed which.

### A crash is not a rejection

Every mutation tool decides whether a mutant was killed from the exit status of
whatever it ran. That makes an important failure invisible: a variant that
crashes looks exactly like a variant that was caught.

Schuler and Zeller (ICST 2011) measured how much this matters. They removed
*every assertion* from seven Java test suites — leaving suites that check
nothing whatsoever — and the mutation score fell only to **43%**. The remaining
kills came from what they call the implicit checks of the runtime system: the
program crashed, and the tool recorded a success.

So the three outcomes are recorded separately here, and only a comparison
counts:

| Outcome | Meaning |
| --- | --- |
| accepted | the gate compared the outputs and found them equal |
| rejected | the gate compared the outputs and found them different |
| unjudged | the variant did not run, so nothing was compared |

An unjudged control is never correct, whatever it was supposed to be, and it
stays in the denominator. Both rules matter. Crediting a crash as a rejection
is how a gate that checks nothing earns a passing score; dropping crashes from
the denominator instead would let a control set that mostly fails to run report
well on the handful that survive.

This was a real defect in the first version of this code, which recorded any
variant that failed to run as rejected.

### The ceiling this design has, stated plainly

An oracle that compares returned values cannot see a fault that corrupts state
without changing any returned value. Yao, Harman and Jia (ICSE 2014)
hand-classified 946 equivalent mutants and found **37% were infected but
unobservable** — the program never externalised the corrupted state.

The compensating evidence is stronger than the limitation. Comparing final
outputs is *strong* mutation, and Chekam et al. (ICSE 2017) found strong
mutation uniquely coupled to **38% of real faults**, more than any other
criterion tested, and the only criterion with any uniquely coupled faults at
all. Observing outputs is where the discriminating power lives; the ceiling is
the price of it, not a flaw in the choice.
