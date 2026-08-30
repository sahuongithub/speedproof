"""Rules the task runner must not break."""

from speedproof.corpus.runner import CorpusReport, Outcome, TaskResult


def result(outcome, task_id="t", **kw):
    return TaskResult(
        task_id=task_id, repo="a/b", classification="remove_or_reduce_work",
        outcome=outcome, **kw
    )


def test_only_a_validated_task_is_usable():
    """Every other outcome is a reason a candidate did not become a task."""
    for outcome in Outcome:
        assert outcome.usable == (outcome is Outcome.VALIDATED)


def test_the_funnel_is_reported_by_reason_not_as_a_pass_rate():
    """Which stage a candidate died at is the finding, not the count."""
    report = CorpusReport([
        result(Outcome.VALIDATED, "a"),
        result(Outcome.NO_WORKLOAD, "b"),
        result(Outcome.NO_WORKLOAD, "c"),
        result(Outcome.PATCH_FAILED, "d"),
    ])
    assert report.counts() == {
        "validated": 1, "no_workload": 2, "patch_failed": 1
    }
    assert len(report.validated) == 1


def test_a_measured_null_result_is_not_a_failure():
    """A patch too small to measure on this workload is a finding about the
    workload, and is distinct from one that could not be measured at all."""
    assert Outcome.NO_EFFECT is not Outcome.UNMEASURABLE
    assert not Outcome.NO_EFFECT.usable


def test_differing_answers_are_their_own_outcome():
    """Not a measurement failure: the trees genuinely disagree, and that is
    worth looking at rather than counting as noise."""
    assert Outcome.NOT_EQUIVALENT.value == "not_equivalent"
    assert not Outcome.NOT_EQUIVALENT.usable


def test_a_result_line_shows_the_numbers_when_there_are_any():
    r = result(Outcome.VALIDATED, base_net_ir=1000, patched_net_ir=600,
               work_reduction=0.4)
    assert "+40.00%" in r.line()
    assert "1,000" in r.line()


def test_a_result_line_shows_the_reason_when_there_are_none():
    assert "no workload reaches it" in result(
        Outcome.NO_WORKLOAD, detail="no workload reaches it"
    ).line()
