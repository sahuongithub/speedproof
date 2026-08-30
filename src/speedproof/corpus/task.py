"""What a corpus task is, and which ones this metric may legitimately judge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Categories of optimisation whose benefit instruction counting cannot see, or
#: reads with the wrong sign. Excluded at construction so that no task in the
#: corpus depends on an effect the measurement is blind to.
#:
#: Parallelism is the clearest case: Valgrind serialises threads, so a change
#: that genuinely scales across cores is recorded as a regression.
OUT_OF_SCOPE = frozenset(
    {
        "use_parallelization",
    }
)

#: Categories that are in scope but deserve a second look, because whether the
#: metric can see the benefit depends on what the change actually did. A layout
#: change that improves cache locality without removing work is invisible to an
#: instruction count; one that removes indirection is not.
NEEDS_REVIEW = frozenset(
    {
        "use_better_data_structure_and_layout",
        "use_lower_level_system",
    }
)


@dataclass(frozen=True)
class Task:
    """One optimisation a human made, recoverable from repository history."""

    task_id: str
    repo: str
    base_sha: str
    merge_sha: str
    patch: str
    classification: str
    difficulty: str
    merged_at: str
    benchmark_files: tuple[str, ...] = field(default=())

    @property
    def in_scope(self) -> bool:
        return self.classification not in OUT_OF_SCOPE

    @property
    def needs_review(self) -> bool:
        return self.classification in NEEDS_REVIEW

    @property
    def slug(self) -> str:
        """Filesystem-safe identifier."""
        return self.task_id.replace("/", "_")

    @classmethod
    def from_row(cls, row: dict) -> "Task":
        return cls(
            task_id=row["task_id"],
            repo=row["repo_name"],
            base_sha=row["pr_base_sha"],
            merge_sha=row["pr_merge_commit_sha"],
            patch=row["patch"],
            classification=row.get("classification", "uncategorized"),
            difficulty=row.get("difficulty", "unknown"),
            merged_at=row.get("pr_merged_at", ""),
            benchmark_files=tuple(row.get("benchmark_files", ())),
        )

    def to_row(self) -> dict:
        return {
            "task_id": self.task_id,
            "repo_name": self.repo,
            "pr_base_sha": self.base_sha,
            "pr_merge_commit_sha": self.merge_sha,
            "patch": self.patch,
            "classification": self.classification,
            "difficulty": self.difficulty,
            "pr_merged_at": self.merged_at,
            "benchmark_files": list(self.benchmark_files),
        }


def in_scope(tasks: list[Task]) -> list[Task]:
    """Drop tasks whose benefit this metric cannot legitimately judge."""
    return [t for t in tasks if t.in_scope]


def load_tasks(path: Path) -> list[Task]:
    """Read a task manifest."""
    payload = json.loads(Path(path).read_text())
    rows = payload["tasks"] if isinstance(payload, dict) else payload
    return [Task.from_row(r) for r in rows]


def save_tasks(tasks: list[Task], path: Path) -> None:
    """Write a task manifest, newest first."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(tasks, key=lambda t: t.merged_at, reverse=True)
    path.write_text(
        json.dumps({"tasks": [t.to_row() for t in ordered]}, indent=1) + "\n"
    )
