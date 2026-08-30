"""The score, and why it is shaped this way."""

import math

import pytest

from speedproof.speedagent.scoring import (
    CREDIT_CAP,
    ArmResult,
    TaskScore,
    clustered_standard_error,
    minimum_detectable_effect,
    paired_difference,
)


def score(task="t", repo="r", base=1000, human=500, arm=500):
    return TaskScore(task=task, repo=repo, base_ir=base, human_ir=human, arm_ir=arm)


def test_matching_the_expert_scores_one():
    assert score(base=1000, human=500, arm=500).expert_fraction == pytest.approx(1.0)


def test_finding_nothing_scores_zero():
    assert score(base=1000, human=500, arm=1000).expert_fraction == pytest.approx(0.0)


def test_half_the_experts_log_reduction_scores_a_half():
    """On a log scale, so halving the work and halving it again count equally."""
    arm = 1000 / math.sqrt(2)
    assert score(base=1000, human=500, arm=arm).expert_fraction == pytest.approx(0.5)


def test_beating_the_expert_is_reported_not_hidden():
    assert score(base=1000, human=500, arm=250).expert_fraction > 1.0


def test_one_extraordinary_task_cannot_carry_the_mean():
    """Capped so a single fifty-fold win does not become the headline for a
    corpus where the arm usually finds nothing."""
    assert score(base=1000, human=999, arm=1).expert_fraction == CREDIT_CAP


def test_a_task_the_expert_barely_improved_cannot_be_scored():
    """The denominator would be near zero and the score meaningless either
    way, so the task says nothing rather than saying something loudly."""
    assert not score(base=1000, human=1000).measurable
    assert score(base=1000, human=1000).expert_fraction is None


def test_an_arm_that_did_not_produce_anything_scores_zero_not_nothing():
    """Distinct from a task that cannot be scored: this arm was asked and
    failed, which is information."""
    assert score(arm=None).expert_fraction == 0.0


def test_arms_are_compared_only_on_tasks_both_scored():
    a = ArmResult("agent", [score("t1", arm=500), score("t2", arm=600)])
    b = ArmResult("one_shot", [score("t1", arm=800)])
    assert [t for t, _, _ in paired_difference(a, b)] == ["t1"]


def test_the_error_widens_when_tasks_share_a_repository():
    """Tasks from one project share a build, a style and often the same hot
    loops. Treating them as independent understates the error."""
    same = [(f"t{i}", "one-repo", 0.4) for i in range(6)]
    spread = [(f"t{i}", f"repo{i}", 0.4) for i in range(6)]
    # Identical values within one cluster: the residuals add rather than cancel.
    assert clustered_standard_error(same) >= clustered_standard_error(spread)


def test_a_corpus_states_what_it_could_have_detected():
    """Reported alongside the result. A corpus that cannot resolve the claimed
    difference has not failed to find it; it was never able to."""
    differences = [(f"t{i}", "r", v) for i, v in enumerate([0.1, 0.3, 0.2, 0.4])]
    mde = minimum_detectable_effect(differences)
    assert mde is not None and mde > 0


def test_nothing_is_claimed_from_a_single_task():
    assert clustered_standard_error([("t", "r", 0.5)]) is None
    assert minimum_detectable_effect([("t", "r", 0.5)]) is None


def test_parity_is_counted_separately_from_the_mean():
    arm = ArmResult("agent", [score("t1", arm=500), score("t2", arm=900)])
    assert arm.parity_count == 1
    assert arm.mean_fraction < 1.0
