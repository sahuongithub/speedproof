"""Writing down what happened, while it happens.

The publishing convention for these artifacts is short and its most important
clause is that a trajectory must be "generated *with* the inference process,
not post-hoc". Reconstructing one from logs afterwards is detectable, and the
reconstruction is a claim about what happened rather than a record of it. So
this is written as the run proceeds and closed when it ends, including when it
ends badly.

Two layers, because the two audiences want different things and every good
published example separates them:

* a JSON record, complete, one file per task and arm, holding every exchange,
  every measurement and the rule by which an answer was chosen;
* a page of readable text per task, where each round is a card carrying the
  measurement, what the profile said, what the agent did about it, and whether
  the round was kept.

The JSON borrows its attribute names from the OpenTelemetry conventions for
generative-AI spans -- ``gen_ai.usage.input_tokens`` and the rest. Inventing
private names would cost the same and make the record readable only by this
project.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "speedproof-trajectory/1"

#: How much of a tool's output to keep inline. The rest goes to a file beside
#: it: reading is what makes these records unreadable, and the surveyed agents
#: spend thirty to forty thousand tokens per task on it.
INLINE_LIMIT = 2_000


@dataclass
class RoundRecord:
    """One turn, as it happened."""

    round: int
    prompt: str = ""
    reply: str = ""
    edits_proposed: int = 0
    patch: str = ""
    net_ir: int | None = None
    import_cost: int | None = None
    equivalent: bool | None = None
    rejected: str | None = None
    kept: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    profile_shown: bool = False
    history_shown: bool = False

    def card(self, baseline_ir: int, expert_ir: int | None) -> str:
        """This round as a few readable lines.

        The measurement, what was done, and whether it was kept, adjacent to
        each other. Separating them is what turns a trajectory into a wall of
        JSON: the adjacency is the causal claim.
        """
        if self.rejected:
            headline = f"rejected — {self.rejected}"
        elif self.net_ir is None:
            headline = "no measurement"
        else:
            change = (baseline_ir - self.net_ir) / baseline_ir if baseline_ir else 0
            headline = f"{self.net_ir:,} instructions ({change:+.1%})"
            if expert_ir:
                share = (
                    (baseline_ir - self.net_ir) / (baseline_ir - expert_ir)
                    if baseline_ir > expert_ir
                    else 0
                )
                headline += f", {share:.0%} of the expert's reduction"
        marks = []
        if self.profile_shown:
            marks.append("profile")
        if self.history_shown:
            marks.append("history")
        given = f"  shown: {', '.join(marks)}" if marks else ""
        kept = "  ← kept" if self.kept else ""
        return (
            f"### Round {self.number_label}{kept}\n\n"
            f"{headline}{given}\n\n"
            f"{self._what_changed()}\n"
        )

    @property
    def number_label(self) -> str:
        return str(self.round)

    def _what_changed(self) -> str:
        if not self.patch.strip():
            return "_No change was produced._"
        changed = [
            line for line in self.patch.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        shown = changed[:12]
        more = len(changed) - len(shown)
        body = "\n".join(shown)
        if more > 0:
            body += f"\n… and {more} more changed line(s)"
        return f"```diff\n{body}\n```"


@dataclass
class TrajectoryRecord:
    """One arm's attempt at one task, written as it goes."""

    task_id: str
    repo: str
    arm: str
    base_commit: str
    workload: str
    baseline_ir: int
    expert_ir: int | None = None
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str | None = None
    rounds: list[RoundRecord] = field(default_factory=list)
    selection_rule: str = ""
    selected_round: int | None = None
    stopped_because: str = ""
    model_calls: int = 0
    measurements: int = 0
    config: dict = field(default_factory=dict)

    def close(self, stopped_because: str, selected_round: int | None) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.stopped_because = stopped_because
        self.selected_round = selected_round
        for record in self.rounds:
            record.kept = record.round == selected_round

    # ------------------------------------------------------------------ json

    def to_json(self) -> dict:
        return {
            "schema": SCHEMA,
            "task": {
                "task_id": self.task_id,
                "repo": self.repo,
                "base_commit": self.base_commit,
                "workload": self.workload,
                "baseline_ir": self.baseline_ir,
                "expert_ir": self.expert_ir,
            },
            "arm": self.arm,
            "config": self.config,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "rounds": [
                {
                    "round": r.round,
                    "prompt": _clip(r.prompt),
                    "reply": _clip(r.reply),
                    "edits_proposed": r.edits_proposed,
                    "patch": r.patch,
                    "oracle": {
                        "net_ir": r.net_ir,
                        "import_cost": r.import_cost,
                        "equivalent": r.equivalent,
                        "rejected": r.rejected,
                    },
                    "shown": {
                        "profile": r.profile_shown,
                        "history": r.history_shown,
                    },
                    "gen_ai.usage.input_tokens": r.input_tokens,
                    "gen_ai.usage.output_tokens": r.output_tokens,
                    "kept": r.kept,
                }
                for r in self.rounds
            ],
            "selection": {
                "rule": self.selection_rule,
                "selected_round": self.selected_round,
                "final_round": self.rounds[-1].round if self.rounds else None,
                "stopped_because": self.stopped_because,
            },
            "cost": {
                "model_calls": self.model_calls,
                "measurements": self.measurements,
                "rounds": len(self.rounds),
            },
        }

    # ------------------------------------------------------------- readable

    def to_markdown(self) -> str:
        expert = (
            f"{self.expert_ir:,}" if self.expert_ir is not None else "not measured"
        )
        best = next((r for r in self.rounds if r.kept), None)
        outcome = (
            f"kept round {best.round}, {best.net_ir:,} instructions"
            if best and best.net_ir is not None
            else "nothing was kept"
        )
        lines = [
            f"# {self.task_id} — {self.arm}",
            "",
            f"- repository: `{self.repo}` at `{self.base_commit[:12]}`",
            f"- workload: `{self.workload}`",
            f"- starting point: **{self.baseline_ir:,}** instructions",
            f"- the maintainer's patch: **{expert}** instructions",
            f"- outcome: {outcome}",
            f"- stopped because: {self.stopped_because}",
            "",
            "Every measurement below was taken by the harness in a container "
            "the agent cannot reach. The agent proposed patches and was told "
            "the resulting count; it never measured anything itself.",
            "",
        ]
        for record in self.rounds:
            lines.append(record.card(self.baseline_ir, self.expert_ir))
        return "\n".join(lines)

    # ---------------------------------------------------------------- saving

    def write(self, directory: Path) -> tuple[Path, Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self.task_id}__{self.arm}"
        json_path = directory / f"{stem}.json"
        markdown_path = directory / f"{stem}.md"
        json_path.write_text(json.dumps(self.to_json(), indent=1) + "\n")
        markdown_path.write_text(self.to_markdown())
        return json_path, markdown_path


def _clip(text: str) -> str:
    """Keep the shape of a long exchange without keeping all of it."""
    if len(text) <= INLINE_LIMIT:
        return text
    kept = INLINE_LIMIT // 2
    return (
        text[:kept]
        + f"\n… {len(text) - INLINE_LIMIT:,} characters elided …\n"
        + text[-kept:]
    )
