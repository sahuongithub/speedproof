"""How a task is prepared once and answered several times."""

import pytest

from speedproof.corpus.variants import NotPreparable, Variant


def test_the_four_answers_are_named():
    """base is the starting point, human is the maintainer's own patch, and
    the two candidates are measured against both."""
    assert {v.value for v in Variant} == {"base", "human", "one_shot", "agent"}


def test_the_human_patch_is_a_variant_not_the_ground_truth_of_scoring():
    """It is what someone who knew the codebase did, which makes the question
    'did the agent find what the human found' rather than 'did a number move'."""
    assert Variant.HUMAN.value == "human"


def test_a_task_that_cannot_be_prepared_reports_what_stopped_it():
    """Not a failure count: which stage a candidate died at is the finding."""
    exc = NotPreparable("no_workload", "nothing reaches the changed lines")
    assert exc.outcome == "no_workload"
    assert "nothing reaches" in exc.detail


def test_preparation_happens_once_per_task_not_once_per_answer():
    """A pandas build alone is about four minutes; four answers would be
    sixteen for no additional information.

    Counted by parsing rather than by substring: `needs_build(` contains
    `build(`, and a test that cannot tell them apart is not checking what it
    claims to.
    """
    import ast
    import inspect

    from speedproof.corpus import variants

    tree = ast.parse(inspect.getsource(variants.prepare))
    called = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert called.count("build") == 1
    assert called.count("collect_coverage") == 1
    assert called.count("collect_profile") == 1


def test_unknown_equivalence_is_never_reported_as_agreement():
    """A timing benchmark returns None, which hashes identically whatever the
    code did. Treating that as equality is the vacuous check this project
    exists to avoid."""
    import inspect

    from speedproof.corpus import variants

    source = inspect.getsource(variants.computes_same_answer)
    assert "return None" in source
    assert "checksum(None)" in source


def test_a_task_whose_ground_truth_fails_is_broken_not_hard():
    """Leaving it in would penalise every arm for the harness rather than for
    the work. One surveyed benchmark had 11.3% of problems whose test suites
    would not consistently pass their own reference solution."""
    from speedproof.corpus.variants import GroundTruthFailed

    assert issubclass(GroundTruthFailed, Exception)


def test_the_expert_patch_is_checked_before_any_arm_runs():
    """So a broken task costs one measurement rather than a whole evaluation."""
    import inspect

    from speedproof.corpus import variants

    source = inspect.getsource(variants.prepare)
    assert source.index("GroundTruthFailed") < source.index("collect_profile(")


def test_it_is_counted_rather_than_quietly_dropped():
    from speedproof.corpus.runner import Outcome

    assert Outcome.GROUND_TRUTH_FAILED.value == "ground_truth_failed"
    assert not Outcome.GROUND_TRUTH_FAILED.usable
