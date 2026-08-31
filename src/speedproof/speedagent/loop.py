"""The optimisation loop.

Every part of this is shaped by a published ablation rather than by what sounds
sensible, because several of the things that sound sensible are measured to
make results worse.

**Iterating with measured feedback is the whole effect.** In the one study that
separates the parts, adding a loop that reports the measurement lifted a
frontier model from 20.6 to 33.3 on the benchmark's headline score, with no
profiler and no tests involved. The profiler adds three points on top of that.
The loop is not the delivery mechanism for the clever part; it is the clever
part.

**The harness profiles, never the agent.** Telling the agent to profile and
letting it choose when scored *below* the plain baseline -- 17.6 against 20.6 --
because an agent that profiles for itself optimises what it measured rather
than what the task is. The same paper's harness-run profiling scored 36.3.

**Correctness feedback alone makes it worse.** Feeding back test results
without profiling dropped that score from 33.3 to 24.5: the agent becomes
careful and stops finding anything. The two are not additive and are not
separable; they are only worth having together.

**The agent does not decide when it is finished.** Three quarters of
trajectories in the surveyed work stop early with budget remaining, and once a
model has secured a measurable win it tends to stop rather than push. The
controller decides.

**The best attempt is kept, not the last.** Published turn-by-turn figures show
speedups of 1.32, 1.77, 3.71, 4.16, 3.94 -- the last turn is a regression, and
an agent judged on where it finished would lose most of what it found.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from speedproof.speedagent.profile import Profile
from speedproof.speedagent.workspace import Workspace, WorkspaceError

#: Rounds to run. The surveyed loop uses five, and its turn-by-turn figures
#: still improve at the fifth.
ROUNDS = 5

#: Stop after this many rounds that fail to beat the best so far. The surveyed
#: loop has no such rule, because its measurements carry noise and a flat round
#: might be luck; ours are exact, so a round that does not improve is a round
#: that did not improve.
PATIENCE = 2

_SEARCH_REPLACE = re.compile(
    r"<<<<<<+ SEARCH\s*\n(.*?)\n?=======\s*\n(.*?)\n?>>>>>>+ REPLACE",
    re.S,
)


class EditError(Exception):
    """Raised when an edit cannot be applied to the file it names."""


@dataclass(frozen=True)
class Edit:
    """One search-and-replace, as the model was asked to express it."""

    find: str
    replace: str

    def apply_to(self, text: str) -> str:
        """Apply this edit, tolerating the ways models get whitespace wrong.

        Models routinely reproduce a block with its shared indentation
        stripped, or with trailing whitespace altered. An applier that insists
        on an exact match rejects edits whose intent is unambiguous, and the
        surveyed failure rates for this format run between two and thirteen per
        cent even for frontier models -- high enough that being strict costs
        more than being careful.
        """
        if self.find in text:
            return text.replace(self.find, self.replace, 1)

        relaxed = self._match_ignoring_indent(text)
        if relaxed is not None:
            return relaxed
        raise EditError(
            "the text to replace does not appear in the file:\n"
            + self.find[:200]
        )

    def _match_ignoring_indent(self, text: str) -> str | None:
        find_lines = self.find.splitlines()
        if not find_lines:
            return None
        stripped = [line.strip() for line in find_lines]
        haystack = text.splitlines(keepends=True)
        bare = [line.strip() for line in text.splitlines()]

        for start in range(len(bare) - len(stripped) + 1):
            if bare[start:start + len(stripped)] != stripped:
                continue
            # Re-indent the replacement by the difference between what the
            # file has and what the model sent.
            original = haystack[start]
            indent = original[: len(original) - len(original.lstrip())]
            model_indent = find_lines[0][: len(find_lines[0]) - len(find_lines[0].lstrip())]
            shifted = []
            for line in self.replace.splitlines():
                if line.startswith(model_indent) and model_indent:
                    line = indent + line[len(model_indent):]
                elif line.strip():
                    line = indent + line.lstrip()
                shifted.append(line)
            return "".join(
                haystack[:start] + [l + "\n" for l in shifted] + haystack[start + len(stripped):]
            )
        return None


def parse_edits(reply: str) -> list[Edit]:
    """Read every search-and-replace block out of a reply."""
    return [
        Edit(find=found.strip("\n"), replace=replaced.strip("\n"))
        for found, replaced in _SEARCH_REPLACE.findall(reply)
    ]


@dataclass
class Round:
    """One turn: what was proposed, and what the harness made of it."""

    number: int
    edits: int = 0
    net_ir: int | None = None
    import_cost: int | None = None
    equivalent: bool | None = None
    rejected: str | None = None
    patch: str = ""

    @property
    def accepted(self) -> bool:
        return self.net_ir is not None and self.rejected is None

    def summarise(self, baseline_ir: int) -> str:
        """One line, for the history the next round is shown."""
        if self.rejected:
            return f"round {self.number}: rejected, {self.rejected}"
        if self.net_ir is None:
            # Neither measured nor refused. Reported as unknown rather than
            # raising, since this text goes into the next round's prompt and a
            # bookkeeping gap should not end a run.
            return f"round {self.number}: no measurement was returned"
        change = (baseline_ir - self.net_ir) / baseline_ir if baseline_ir else 0
        return (
            f"round {self.number}: {self.net_ir:,} instructions "
            f"({change:+.1%} against the starting point)"
        )


@dataclass
class Trajectory:
    """Every round, in order, kept whole.

    Reporting only the best round would be reporting a selection. The rounds
    that failed are where the behaviour shows, and they are what a reader needs
    to judge whether the loop is doing anything.
    """

    task: str
    baseline_ir: int
    rounds: list[Round] = field(default_factory=list)
    exchanges: list[dict] = field(default_factory=list)
    stopped_because: str = ""

    @property
    def best(self) -> Round | None:
        accepted = [r for r in self.rounds if r.accepted]
        return min(accepted, key=lambda r: r.net_ir) if accepted else None

    @property
    def improvement(self) -> float:
        best = self.best
        if best is None or self.baseline_ir <= 0:
            return 0.0
        return (self.baseline_ir - best.net_ir) / self.baseline_ir

    def history(self) -> str:
        """What has been tried, ranked, for the next prompt.

        Ranked rather than chronological, and every round included: an agent
        shown only its last attempt has no way to see that it is going round in
        circles, and one shown only its successes cannot learn what was
        rejected.
        """
        if not self.rounds:
            return ""
        accepted = sorted(
            (r for r in self.rounds if r.accepted), key=lambda r: r.net_ir
        )
        rejected = [r for r in self.rounds if not r.accepted]
        lines = [
            "What has already been tried, measured by the harness. The "
            f"starting point is {self.baseline_ir:,} instructions."
        ]
        for round_ in accepted:
            lines.append("  " + round_.summarise(self.baseline_ir))
        for round_ in rejected:
            lines.append("  " + round_.summarise(self.baseline_ir))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "baseline_ir": self.baseline_ir,
            "improvement": round(self.improvement, 6),
            "stopped_because": self.stopped_because,
            "rounds": [
                {
                    "round": r.number,
                    "edits": r.edits,
                    "net_ir": r.net_ir,
                    "import_cost": r.import_cost,
                    "equivalent": r.equivalent,
                    "rejected": r.rejected,
                    "accepted": r.accepted,
                    "patch": r.patch,
                }
                for r in self.rounds
            ],
            "exchanges": self.exchanges,
        }


def patch_fingerprint(patch: str) -> str:
    """Identify a patch by what it changes, so the same one is not measured twice.

    An agent that repeats an attempt has stalled, and measuring it again costs a
    Valgrind run to learn what is already known.

    The header lines are excluded, and that is the whole difficulty. A unified
    diff names each file with a path and a modification time, so two byte-identical
    changes written a moment apart hash differently. The failure is invisible on a
    fast machine, where both writes land inside the same timestamp granularity, and
    appears on a slower one -- which is how this survived locally and was caught by
    continuous integration.
    """
    content = "\n".join(
        line for line in patch.splitlines()
        if not line.startswith(("--- ", "+++ ", "diff ", "index "))
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


#: The task, stated once. Both the baseline and the agent see this same text on
#: their first turn, so a difference between them is the loop and not the
#: wording -- the surveyed literature warns that self-correction results are
#: routinely inflated by giving the iterating arm a better prompt.
BRIEF = """\
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
"""


def build_prompt(
    source: str,
    path: str,
    profile: Profile | None = None,
    trajectory: Trajectory | None = None,
) -> str:
    """Assemble the turn's prompt from what the harness knows."""
    profile_text = ""
    if profile is not None and not profile.empty:
        profile_text = (
            "The harness profiled it. These counts are exact:\n\n```\n"
            + profile.render()
            + "\n```\n"
        )
    history_text = ""
    if trajectory is not None and trajectory.rounds:
        history_text = "\n" + trajectory.history() + "\n"
    return BRIEF.format(
        profile=profile_text, path=path, source=source, history=history_text
    )


def apply_edits(workspace: Workspace, relative: Path | str, edits: list[Edit]) -> str:
    """Apply every edit to one file, or none of them.

    A file left half-edited would parse differently and measure differently,
    which is worse than an attempt that plainly failed.
    """
    if not edits:
        raise EditError("the reply contained no edits")
    text = workspace.read(relative)
    for edit in edits:
        text = edit.apply_to(text)
    workspace.write(relative, text)
    return text
