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
