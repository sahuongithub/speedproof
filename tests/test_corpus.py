"""Corpus rules that must hold regardless of what has been ingested."""

import json
from pathlib import Path

from speedproof.corpus.task import (
    NEEDS_REVIEW,
    OUT_OF_SCOPE,
    Task,
    in_scope,
    load_tasks,
)

MANIFEST = Path(__file__).parent.parent / "corpus" / "manifests" / "xdsl.json"


def make(classification="remove_or_reduce_work", task_id="t1"):
    return Task(
        task_id=task_id,
        repo="example/project",
        base_sha="a" * 40,
        merge_sha="b" * 40,
        patch="",
        classification=classification,
        difficulty="easy",
        merged_at="2025-01-01T00:00:00Z",
    )


def test_parallelisation_is_never_in_scope():
    """Valgrind serialises threads, so a scaling win reads as a regression."""
    assert not make("use_parallelization").in_scope
    assert in_scope([make("use_parallelization")]) == []


def test_ordinary_work_reduction_is_in_scope():
    assert make("remove_or_reduce_work").in_scope


def test_layout_changes_are_flagged_for_review():
    task = make("use_better_data_structure_and_layout")
    assert task.in_scope
    assert task.needs_review


def test_review_and_exclusion_do_not_overlap():
    assert not (NEEDS_REVIEW & OUT_OF_SCOPE)


def test_manifest_contains_nothing_out_of_scope():
    if not MANIFEST.exists():
        return
    for task in load_tasks(MANIFEST):
        assert task.in_scope, f"{task.task_id} is {task.classification}"


def test_manifest_tasks_round_trip():
    if not MANIFEST.exists():
        return
    tasks = load_tasks(MANIFEST)
    assert tasks
    assert Task.from_row(tasks[0].to_row()) == tasks[0]
