"""Deliberately broken optimisations, kept as permanent controls.

A correctness gate that has never rejected anything is indistinguishable from
no gate at all. Every published benchmark in this area has one that is absent,
unenforced, or vacuous, and in each case the code looked fine; what was missing
was evidence that it ever fired.

Ordinary benchmarks get that evidence for free. SWE-bench keeps a task only if
some test flips from failing to passing when the patch is applied, which proves
the tests notice that particular change. A performance benchmark cannot do
this: the base tree is already correct, so it passes the gate before and after.
There is no natural non-vacuity check, and seeded faults are therefore not an
optional extra here -- they are the only available demonstration that the gate
discriminates at all.

**Both directions are reported, always.** A gate judged only on what it rejects
is indistinguishable from one that rejects everything, so each control carries
a ground-truth verdict and the equivalent ones matter as much as the broken
ones. This follows the soundness and completeness axes of Jahangirova, Clark,
Harman and Tonella, "Test oracle assessment and improvement" (ISSTA 2016).

**Why these are hand-written rather than generated.** Just, Jalali, Inozemtseva,
Ernst, Holmes and Fraser (FSE 2014) found 73% of real faults coupled to
generated mutants, and examined the 27% that did not. The largest single
category was *algorithm modification or simplification* -- which is the
definition of a performance optimisation. Generic mutation operators
systematically under-sample exactly the fault distribution this benchmark is
made of, so the classes below are written to that distribution instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Truth(str, Enum):
    """What the gate is required to say about a control."""

    BROKEN = "broken"
    """Semantically different from the original. The gate MUST reject it."""

    EQUIVALENT = "equivalent"
    """A real optimisation, or a rewrite that changes nothing observable.
    The gate MUST accept it."""


class FaultClass(str, Enum):
    """The ways a plausible-looking optimisation goes wrong.

    Fixed so that coverage is auditable across tasks: each task instantiates
    the classes that apply to it and records why the others do not, which
    "we wrote some broken versions" can never support.
    """

    # Classes that generic mutation operators do produce, and which real
    # faults couple to most often (Just et al. 2014).
    COMPARISON_FLIP = "comparison_flip"
    """A boundary or comparison inverted in a guard selecting a fast path."""

    WORK_DELETED = "work_deleted"
    """A step removed that looked redundant and was not."""

    # Classes specific to optimisation, which generic operators do not reach.
    PRECISION_WEAKENED = "precision_weakened"
    """A cheaper numeric path that quietly loses accuracy."""

    CACHE_KEY_INCOMPLETE = "cache_key_incomplete"
    """Memoised on a key that omits something the result depends on."""

    CACHE_ALIASES = "cache_aliases"
    """A mutable object cached by reference, so one caller's change is seen
    by the next."""

    COPY_BECAME_ALIAS = "copy_became_alias"
    """A defensive copy dropped, so a later write reaches the caller's data.
    The classic optimisation bug in array and dataframe code."""

    ORDER_UNSTABLE = "order_unstable"
    """A stable order replaced by an unspecified one. Silent, plausible, and
    genuinely faster."""

    EDGE_CASE_SKIPPED = "edge_case_skipped"
    """Handling dropped for empty, singleton, or non-finite input."""

    EARLY_RETURN = "early_return"
    """A default or cached value returned on a path that should compute."""

    ITERATION_REDUCED = "iteration_reduced"
    """Fewer iterations or a looser tolerance in a converging computation."""


@dataclass(frozen=True)
class Control:
    """One deliberately broken or deliberately equivalent variant."""

    name: str
    fault: FaultClass | None
    truth: Truth
    source: str
    rationale: str
    """Why this is broken, or why it is genuinely equivalent. Recorded because
    a survivor has to be adjudicated by a person and the reasoning has to
    survive the person."""

    @property
    def must_be_rejected(self) -> bool:
        return self.truth is Truth.BROKEN


class Judgement(str, Enum):
    """How a control's fate was decided.

    The distinction is not bookkeeping. Schuler and Zeller (ICST 2011) removed
    every assertion from seven test suites and the mutation score only fell to
    43%, because mutants were still being killed by the runtime crashing rather
    than by anything checking the answer. A tool that decides kill or survive
    from an exit status alone cannot tell a gate that works from one that does
    not, so the two outcomes are recorded separately here and only ``REJECTED``
    counts as the gate having done its job.
    """

    ACCEPTED = "accepted"
    """The gate compared the outputs and found them equal."""

    REJECTED = "rejected"
    """The gate compared the outputs and found them different."""

    CRASHED = "crashed"
    """The variant did not run to completion, so the gate never judged it."""


@dataclass(frozen=True)
class ControlOutcome:
    """What the gate said about one control, and whether that was right."""

    control: Control
    judgement: Judgement
    detail: str = ""

    @property
    def rejected(self) -> bool:
        return self.judgement is Judgement.REJECTED

    @property
    def judged(self) -> bool:
        """Whether the gate actually rendered a verdict on this control."""
        return self.judgement is not Judgement.CRASHED

    @property
    def correct(self) -> bool:
        """A crash is never correct: nothing was checked.

        Counting a crash as a rejection is how a gate that checks nothing
        earns a passing score.
        """
        if not self.judged:
            return False
        return self.rejected == self.control.must_be_rejected

    @property
    def failure_kind(self) -> str | None:
        """How the gate was wrong, in the three ways that differ.

        Missing a broken variant means the gate is unsound: it would pass a
        wrong optimisation. Rejecting an equivalent one means it is
        incomplete: it would reject a real optimisation and cost a genuine
        result. A crash means the control never tested anything, which is a
        defect in the control rather than a measurement of the gate.
        """
        if self.correct:
            return None
        if not self.judged:
            return "unjudged"
        return "unsound" if self.control.must_be_rejected else "incomplete"


@dataclass(frozen=True)
class GateReport:
    """The two-sided result. Neither number means anything without the other."""

    outcomes: tuple[ControlOutcome, ...]

    @property
    def broken(self) -> tuple[ControlOutcome, ...]:
        return tuple(o for o in self.outcomes if o.control.must_be_rejected)

    @property
    def equivalent(self) -> tuple[ControlOutcome, ...]:
        return tuple(o for o in self.outcomes if not o.control.must_be_rejected)

    @property
    def unjudged(self) -> tuple[ControlOutcome, ...]:
        """Controls the gate never rendered a verdict on."""
        return tuple(o for o in self.outcomes if not o.judged)

    @property
    def soundness(self) -> float:
        """Fraction of broken variants the gate rejected *by comparing them*.

        Crashes stay in the denominator. Dropping them would let a control set
        that mostly fails to run report a high score.
        """
        broken = self.broken
        return sum(o.correct for o in broken) / len(broken) if broken else 1.0

    @property
    def completeness(self) -> float:
        """Fraction of equivalent variants the gate accepted."""
        equivalent = self.equivalent
        if not equivalent:
            return 1.0
        return sum(o.correct for o in equivalent) / len(equivalent)

    @property
    def passed(self) -> bool:
        """Both directions must be perfect. A gate is not partly trustworthy."""
        return all(o.correct for o in self.outcomes)

    def summary(self) -> str:
        broken, equivalent = self.broken, self.equivalent
        lines = [
            f"soundness    {sum(o.correct for o in broken)}/{len(broken)} "
            f"broken variants rejected by comparison",
            f"completeness {sum(o.correct for o in equivalent)}/{len(equivalent)} "
            f"equivalent variants accepted",
        ]
        if self.unjudged:
            lines.append(
                f"unjudged     {len(self.unjudged)} control(s) did not run, so "
                f"the gate never checked them"
            )
        for outcome in self.outcomes:
            if not outcome.correct:
                lines.append(
                    f"  {outcome.failure_kind.upper():10s} {outcome.control.name}: "
                    f"{outcome.control.rationale}"
                )
        return "\n".join(lines)
