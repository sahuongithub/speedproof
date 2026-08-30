"""Judging an attempt, on the other side of the firewall.

The loop holds a reference to this and calls it. That is the only thing it can
do with a measurement: ask for one. It cannot build the command, cannot read
the container, cannot see the reference the answer is compared against, and
cannot influence any of it, because none of that lives where the loop runs.

The order of the checks is the order in which failing them matters. Equivalence
first, because a faster wrong answer is not an optimisation and there is
nothing to learn from how fast it was. Then whether the work went away rather
than moving into the import, since a paired baseline subtracts what a module
does when it loads and would otherwise pay for hiding work there. Only then the
count.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from speedproof.corpus.variants import Prepared
from speedproof.speedagent.controller import Judgement
from speedproof.speedagent.workspace import Workspace
from speedproof.verifyperf.callgrind import MeasurementError, measure

#: How much the whole program's work may rise while the measured region falls
#: before the saving is treated as work that moved rather than went away. A
#: little slack, because an import that grows by a few thousand instructions
#: while the region drops by a million is not hiding anything.
IMPORT_SLACK = 0.5


@dataclass
class TaskJudge:
    """Measures an attempt against the task it belongs to.

    Holds everything needed to measure and nothing the agent may see. In
    particular the reference digest stays here: an agent told what the answer
    hashes to has been handed a way to satisfy the check without computing it.
    """

    prepared: Prepared
    #: What the code did before the agent touched it, so an attempt can be
    #: checked for having moved work into the import rather than removed it.
    baseline_net: int
    baseline_import: int | None = None
    repetitions: int = 2
    #: Counted so a trajectory can report what it cost in measurement, which
    #: is the honest denominator for any claim that the loop was worth it.
    measurements: int = 0

    def __call__(self, workspace: Workspace) -> Judgement:
        from speedproof.verifyperf.canon import checksum
        from speedproof.verifyperf.verify import _capture

        prepared = self.prepared
        self.measurements += 1

        if prepared.reference is not None:
            try:
                digest = _capture(
                    workspace.root, prepared.workload, "checksum",
                    prepared.platform,
                )
            except Exception as exc:
                return Judgement(
                    rejected=f"it did not run: {str(exc).splitlines()[0][:70]}"
                )
            if digest == checksum(None):
                # Nothing comparable came back. Unknown, not equal: reporting
                # that as agreement is the vacuous check this project exists
                # to avoid.
                pass
            elif digest != prepared.reference:
                return Judgement(
                    equivalent=False, rejected="it computes different answers"
                )

        try:
            result = measure(
                workspace.root,
                prepared.workload,
                repetitions=self.repetitions,
                fingerprint=prepared.fingerprint,
                platform=prepared.platform,
                image=prepared.image,
                baseline=prepared.workload_baseline,
            )
        except MeasurementError as exc:
            return Judgement(
                rejected=f"it did not run: {str(exc).splitlines()[0][:70]}"
            )

        if not result.deterministic:
            # Two identical runs disagreeing means something in the attempt is
            # not reproducible, and a count that moves is not a count.
            return Judgement(
                rejected=(
                    f"it did not measure the same twice "
                    f"(spread {result.spread:,})"
                )
            )

        if moved_into_import(
            self.baseline_net, self.baseline_import,
            result.net, result.import_cost,
        ):
            return Judgement(
                net_ir=result.net,
                import_cost=result.import_cost,
                equivalent=True,
                rejected=(
                    "the work moved into module import rather than going away"
                ),
            )

        return Judgement(
            net_ir=result.net,
            import_cost=result.import_cost,
            equivalent=True,
        )


def moved_into_import(
    baseline_net: int,
    baseline_import: int | None,
    attempt_net: int,
    attempt_import: int | None,
) -> bool:
    """Whether a saving is work that moved rather than work that went away.

    A paired baseline subtracts whatever a module does when it loads, so an
    attempt that precomputes its answer at import is carried on both sides and
    cancels exactly. Measured on a module doing this, the region's count fell
    by 99.5% while the program did more work in total.
    """
    if baseline_import is None or attempt_import is None:
        return False
    saved = baseline_net - attempt_net
    if saved <= 0:
        return False
    added = attempt_import - baseline_import
    return added > saved * IMPORT_SLACK
