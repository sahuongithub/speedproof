"""How the result is reported, and what it refuses to overclaim."""

from speedproof.speedagent.evaluate import Report
from speedproof.speedagent.scoring import TaskScore


def score(task, repo, arm_ir, base=1000, human=500):
    return TaskScore(task=task, repo=repo, base_ir=base, human_ir=human, arm_ir=arm_ir)


def populated():
    report = Report()
    # The agent does a little better than the one-shot on every task.
    for i in range(8):
        repo = f"repo{i % 4}"
        report.record("agent", score(f"t{i}", repo, 600))
        report.record("one_shot", score(f"t{i}", repo, 700))
    return report


def test_arms_are_compared_only_on_tasks_both_answered():
    report = Report()
    report.record("agent", score("t1", "r", 600))
    report.record("agent", score("t2", "r", 600))
    report.record("one_shot", score("t1", "r", 800))
    assert report.compare("agent", "one_shot").tasks == 1


def test_the_comparison_reports_how_many_repositories_it_spans():
    """Twenty tasks from three projects are worth much less than twenty from
    twelve, and a reader cannot tell which they have without being told."""
    assert populated().compare("agent", "one_shot").repositories == 4


def test_a_difference_below_what_the_corpus_resolves_is_marked():
    """A corpus that cannot resolve a difference has not failed to find it."""
    report = Report()
    for i in range(4):
        report.record("agent", score(f"t{i}", "r", 690 + i * 40))
        report.record("one_shot", score(f"t{i}", "r", 700))
    comparison = report.compare("agent", "one_shot")
    assert comparison.detectable is not None
    if not comparison.resolvable:
        assert "below what this corpus can resolve" in comparison.line()


def test_a_missing_arm_produces_no_claim():
    report = Report()
    report.record("agent", score("t1", "r", 600))
    assert report.compare("agent", "best_of").difference is None


def test_the_contrasts_include_the_one_that_decides_the_question():
    """Whether the loop is useful feedback or merely bought compute."""
    assert ("agent", "best_of") in Report.CONTRASTS
    assert ("agent", "agent_no_profile") in Report.CONTRASTS
    assert ("one_shot_profile", "one_shot") in Report.CONTRASTS


def test_the_expert_is_among_the_contrasts():
    """The question is how much of what the maintainer found the agent found."""
    assert ("agent", "human") in Report.CONTRASTS


def test_unscored_tasks_are_counted_rather_than_omitted():
    report = populated()
    report.dropped = {"no_workload": 12, "ground_truth_failed": 2}
    summary = report.summary()
    assert "no_workload" in summary and "12" in summary
    assert "ground_truth_failed" in summary


def test_the_summary_says_what_a_small_difference_does_not_mean():
    assert "not evidence of no difference" in populated().summary()


def test_the_written_record_keeps_every_task_not_just_the_means(tmp_path):
    import json

    report = populated()
    path = tmp_path / "results.json"
    report.write(path)
    written = json.loads(path.read_text())
    assert len(written["arms"]["agent"]["tasks"]) == 8
    assert written["contrasts"][0]["minimum_detectable_effect"] is not None
