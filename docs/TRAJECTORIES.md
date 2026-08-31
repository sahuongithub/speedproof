# Agent trajectories

Three agents were used to produce the result in the README. This page gives the
instructions that shape each of them, the feedback loop they sit inside, and a
representative trajectory for every one — including the rounds that were
refused.

The recorded runs are in [`eval/trajectories/`](../eval/trajectories/), one JSON
record and one readable page per task and arm. Nothing here is written by hand;
the pages are generated from the same records the evaluation reads.

---

## The three agents

All three receive the same brief and the same file. They differ only in what
else they are given and how many times they are allowed to act.

| Agent | Sees a profile | Rounds | Told the result of its own attempts |
| --- | --- | ---: | --- |
| `one_shot` | no | 1 | — |
| `one_shot_profile` | yes | 1 | — |
| `agent` | yes | up to 5 | yes, every round |

`one_shot` is the **simple baseline**: one prompt, one patch, no feedback. It is
what a person gets today from asking a model to make code faster. Every claim
about the loop is a claim about the difference between it and `agent`.

---

## The instructions that shape each agent

This is the complete brief, verbatim from
[`src/speedproof/speedagent/loop.py`](../src/speedproof/speedagent/loop.py). The
`{profile}` and `{history}` slots are what separates the three agents: `one_shot`
gets neither, `one_shot_profile` gets the profile, `agent` gets both.

```
You are making one Python file do less work, without changing what it computes.

It is measured by counting the machine instructions it retires. The count is
exact and reproduces to the instruction, so there is no noise to exploit and no
value in resubmitting an unchanged attempt.

{profile}
The file is `{path}`:

```python
{source}
```
{history}
What the harness checks, so that working around it is not possible:

* The results must be identical. They are compared by hashing a canonical
  encoding of what the code returns, computed outside the process you affect.
* Work moved into module import is not a saving. The cost of importing is
  measured separately and counted against you.
* Caching between calls is not a saving. Each measurement runs a fresh process.
* Deferring work is not a saving. The result is fully materialised inside the
  measured region.
* Make the code generally faster rather than faster on this particular input.
  A fast path that only fires on the measured case is not an optimisation.

Reply with one or more edits in exactly this form, and nothing else:

<<<<<<< SEARCH
the exact lines to replace
=======
what to replace them with
>>>>>>> REPLACE
```

Every closed route is named in the brief rather than left for the agent to
discover. An agent that has to guess where the boundary is will spend rounds
finding it, and a rejection it did not see coming teaches it nothing.

---

## What the agent can and cannot do

The agent proposes patches. **It never measures one.** Every number it sees is
produced by the harness, in a container the agent has no access to, and the
verdict on its work is reached the same way.

That separation is enforced by a test rather than by convention:
`tests/test_controller.py::test_the_agent_never_measures_anything` fails the
build if the controller module ever imports the measurement.

| Tool | Who runs it | What the agent learns |
| --- | --- | --- |
| edit application | harness | whether the edit matched; nothing else |
| correctness check | harness, outside the measured process | accepted, or *it computes different answers* |
| instruction count | harness, inside a sealed container | one integer |
| import-cost check | harness | whether the work moved instead of going away |
| duplicate check | harness | whether this exact patch was already measured |

---

## The feedback that shapes the next step

After each round the agent is given this block, and nothing else about its
performance. It is **ranked by result rather than chronological**, and every
round appears — accepted and refused alike:

```
What has already been tried, measured by the harness. The starting point is
33,757,056 instructions.
  round 1: 28,986,013 instructions (+14.1% against the starting point)
  round 3: 29,086,154 instructions (+13.8% against the starting point)
  round 2: rejected, it computes different answers
```

Two decisions are visible in that format.

**Every round is included, including the refusals.** An agent shown only its
successes cannot learn what the gate rejects. An agent shown only its last
attempt has no way to notice it is going in circles.

**It is ranked, not chronological.** The best attempt is at the top whether it
happened first or last, because the thing the agent needs to beat is the best
result so far, not the most recent one.

---

## Retries and stopping

The agent does not decide when it is finished. A separate controller does, and
it stops on whichever comes first:

- **five rounds**, or
- **two consecutive rounds with no improvement** (`PATIENCE = 2`).

Three quarters of trajectories in the published work this was built against stop
early with budget remaining, which is why the decision was taken away from the
agent.

A round can end in four ways. Only the first advances the work:

| Outcome | What happens | Costs a round |
| --- | --- | --- |
| accepted | measured, recorded, may become the best | yes |
| refused — different answers | reverted, reported to the agent | yes |
| refused — work moved into import | reverted, reported to the agent | yes |
| refused — the same patch as before | reverted, never measured | yes, deliberately |

The duplicate check is the one worth explaining. Re-measuring an identical patch
costs a full Valgrind run to learn something already known, so a repeat is
refused before measurement. This check had a real bug, recorded in the
changelog: it hashed the whole unified diff including the file modification
times, so two byte-identical patches written moments apart hashed differently
and the check silently stopped working. It passed on the author's laptop for the
entire build and failed the first time CI ran it on a slower machine.

**Human checkpoints.** There are none inside a run. A run is started by a person
and is otherwise unattended; no attempt is approved, edited, or rescued by hand.
The only human decisions are which task to run and when to stop the corpus.

---

## The recorded trajectories

All three are on the same task: `perf: add __slots__ to token classes` from
`pypa/packaging` at `e7f035135278`, workload
`benchmarks.markers.TimeMarkerSuite.time_constructor`.

Starting point **33,757,056** instructions. The maintainer's own patch reached
**32,740,814**, a 3.01% reduction — that is the bar.

| Trajectory | Result | Work removed | Rounds |
| --- | ---: | ---: | --- |
| [`one_shot`](../eval/trajectories/packaging_bce44a178e__one_shot.md) | 29,372,743 | 12.99% | 1 |
| [`one_shot_profile`](../eval/trajectories/packaging_bce44a178e__one_shot_profile.md) | 32,094,655 | 4.92% | 1 |
| [`agent`](../eval/trajectories/packaging_bce44a178e__agent.md) | **28,986,013** | **14.13%** | 3, kept round 1 |

Each page carries every round in order: the diff proposed, the count the harness
returned, the fraction of the expert's own reduction it achieved, and why the
run stopped.

**What the `agent` trajectory shows that a summary would not.** Its three rounds
measured 28,986,013, then 29,136,511, then 29,086,154. It found its best answer
first and got worse afterwards, so the controller kept round one. An agent judged
on where it finished would have lost a result it had already found — which is
why the best round is kept rather than the last.

**What `one_shot_profile` shows.** Giving the single-shot agent a profile made it
*worse*, not better — 4.92% against 12.99% without one. That matches the
published ablation the design was built against, and it is the reason the
profile is attached to the loop rather than offered to a single prompt.

---

## Regenerating them

```bash
uv run python -m speedproof.speedagent.cli corpus/manifests/packaging.json \
    --task packaging_bce44a178e --arm one_shot --arm one_shot_profile \
    --arm agent --rounds 3
```

Needs model access; nothing else in the repository does. Writes both the JSON
record and the readable page for each arm into `eval/trajectories/`.

The agent is a language model, so a fresh run proposes different patches and the
numbers will differ. The measurement of them will not.
