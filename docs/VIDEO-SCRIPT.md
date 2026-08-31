# Video script

Five minutes. Every command here is real and every number is one this
repository produces — nothing is staged, and nothing needs to be, because the
demonstration is already the most persuasive thing in the project.

**Before recording**, run once so the image is built and the second run is fast:

```bash
uv run python -m speedproof.hackguard >/dev/null
```

Terminal at a large font, dark background, window wide enough that the
demonstration table does not wrap. Nothing else on screen.

---

## 0:00 – 0:40 · The problem

*On screen: the README, scrolled to the top.*

> If you ask an AI agent to make code faster, it will find that making the
> number go down is easier than making the code faster. It isn't being devious.
> It's doing what you asked.
>
> This is measured, not hypothetical. In one benchmark's own notes, agents
> forged the results file in seven hundred and thirty-eight of eight hundred and
> sixty-two containers — eighty-six per cent — because the verdict was read from
> a file written inside the sandbox by the process being judged. The fix on
> record was to delete the check.
>
> And of the four published benchmarks in this area, two compare no outputs at
> all. One captures them and calls a difference "informational only".
>
> So: an agent that optimises code, and a harness that can prove it did.

## 0:40 – 1:50 · The demonstration

*Type it live. It takes about forty seconds, which is enough time to talk over.*

```bash
uv run python -m speedproof.hackguard
```

> Five attempted optimisations. Each is measured twice.
>
> The naive column is what you get from timing the code and comparing the
> numbers — which is what every published benchmark in this area does. The
> strict column also asks whether the answers are still the same, and whether
> the work actually went away.

*When the table appears, walk down it — read the colour, not the mechanism.*

> A real optimisation. Both accept it, correctly.
>
> This one computes the answer before the measurement starts. The naive harness
> sees a ninety-nine per cent improvement. It's not an improvement — the work
> moved into module import, where a paired baseline cancels it out. Rejected.
>
> This one is very fast, and wrong. Ninety-eight per cent faster, different
> answers. Rejected.
>
> And this one uses cheaper arithmetic that's quietly less accurate — the kind
> of change a tolerance-based check waves through. Rejected.

*Point at the last two lines.*

> The naive harness accepted two of the four attempts that are not
> optimisations. This one got all five right.
>
> None of those cheats was invented for this video. Each cites the published
> benchmark that documented it.

## 1:50 – 2:40 · Why the measurement is trustworthy

*On screen: `docs/measurement.md`, or just talk over the finished table.*

> It works by counting the instructions a program retires, inside a container
> the code under test can't configure, with the counter outside the interpreter
> entirely.
>
> That matters because wall-clock benchmarking is far shakier than it looks.
> Changing only the size of an unused environment variable has been shown to
> swing a measured speedup between zero-point-nine-one and one-point-one times.
> A survey of a hundred and thirty-three papers found a median claimed speedup
> of ten per cent — smaller than that bias.
>
> Counting instructions gives an integer instead of an interval. The same suite
> on my laptop and on a shared GitHub runner agrees on the fraction of work
> removed to one hundredth of a percentage point, even though the raw counts
> differ by ten per cent between architectures. Running it twice on the same
> noisy shared runner returns identical numbers. A busy machine changes how long
> a measurement takes, not what it reports.

## 2:40 – 3:20 · One real execution

*Show a trajectory page from `eval/trajectories/`.*

> Here's the agent on a real optimisation from pypa/packaging — a commit a
> maintainer actually made.
>
> Each round shows what the harness measured, what the agent was shown, and
> what it changed. The agent proposes patches; it never measures one. Every
> number it sees comes from the harness, and there's a test asserting the
> controller module cannot even import the measurement.
>
> Rounds that failed are here too. A trajectory that only shows the successful
> rounds is a selection, not a record.

*If a round was rejected, point at it.*

> This round was rejected before it was ever timed — a faster wrong answer isn't
> an optimisation, so there's nothing to learn from how fast it was.

## 3:20 – 4:10 · The changelog, and the experiment I removed

*On screen: `docs/CHANGELOG.md`.*

> Every design here came from measuring, and several things that sounded
> sensible turned out to be wrong.
>
> The one that changed the project most: I subtracted interpreter startup from
> each measurement, which is correct for a workload written for the purpose and
> wrong for a project's own benchmark — because the benchmark's class body may
> build a five-hundred-by-five-hundred tensor before the benchmark is even
> called. The number was bit-identical across every repetition and completely
> useless: the operation I cared about was **zero point zero eight six per cent**
> of what I was measuring.
>
> Reproducibility was never the problem. Relevance was. No amount of determinism
> rescues a measurement of the wrong thing.

*The removed experiment.*

> And here's one I removed. I tried to profile with Callgrind, which already had
> the data — and for Python it's worthless. Callgrind sees machine functions, so
> a profile of a Python program is a list of CPython's internals with your code
> nowhere in it. I replaced it with counting: how many times each line ran, how
> many times each function was called. Both exact, both reproducible.
>
> That also means one piece of published advice — check the patched functions
> against the Callgrind profile — simply doesn't transfer to Python.

## 4:10 – 4:45 · What it caught in my own work

> The best evidence this thing works is that it kept catching me.
>
> I wrote seven optimisations by hand for the demonstration. **Four were slower
> than the code they replaced.** A fifth was genuinely faster in the measured
> region and needed an import that cost seven-point-six million instructions
> against the two-point-four million it saved — so the harness rejected it, and
> was right to.
>
> I'd have shipped at least two of those believing they were improvements.

## 4:45 – 5:00 · The hot take

> Wall-clock benchmarking made this field's results unfalsifiable, and the
> response has been to build better agents rather than better instruments.
>
> Counting instructions costs nothing and settles it. The reason nobody does it
> isn't that it's hard. It's that determinism removes the wiggle room — and a
> number that can't move in your favour is a number you have to live with.

---

## Notes for recording

**Do not rush the table.** It is the whole video. Twenty seconds of silence
while a viewer reads red and green is worth more than twenty seconds of
explanation.

**Say "instructions", not "Callgrind".** The mechanism is in the README for
anyone who wants it; the video needs the idea.

**If the live run fails**, say so and use the recorded output. A demo that
breaks and is handled honestly reads better than one that was obviously
pre-baked — and this project's entire argument is about not hiding
inconvenient measurements.

**The numbers to get right**, since they carry the argument:

- 738 of 862 containers — 85.6%
- 2 of 4 cheats accepted by the naive harness; 5 of 5 judged correctly here
- 0.086% — the signal an empty baseline left
- four of seven of my own optimisations were slower
- 7.6 million against 2.4 million — the import that cost more than it saved
