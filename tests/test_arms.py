"""What each arm is allowed, and what is held equal between them."""

import inspect

from speedproof.speedagent import arms


def test_every_arm_builds_its_prompt_the_same_way():
    """The surveyed literature reports self-correction results inflated by
    giving the iterating arm a better prompt than its baseline. Both arms call
    the same function, so a difference between them cannot be the wording."""
    source = inspect.getsource(arms)
    assert source.count("build_prompt(") >= 2
    for arm in ("run_one_shot", "run_best_of"):
        assert "build_prompt(" in inspect.getsource(getattr(arms, arm))


def test_the_control_is_given_the_profile_too():
    """Withholding it would confound the comparison with the thing tested."""
    signature = inspect.signature(arms.run_best_of)
    assert "profile" in signature.parameters


def test_the_control_gets_as_many_model_calls_as_the_loop():
    """Otherwise the loop is being compared against less compute, not against
    a different use of the same compute."""
    signature = inspect.signature(arms.run_best_of)
    assert "attempts" in signature.parameters


def test_the_control_chooses_with_the_oracle_and_that_is_deliberate():
    """It sees every attempt scored before choosing; the loop must decide from
    measurements it already spent its budget on. The asymmetry favours the
    control and is left in place, so that beating it means something."""
    doc = arms.run_best_of.__doc__
    assert "asymmetry" in doc and "favours the control" in doc


def test_each_arm_works_in_its_own_workspace():
    """An arm that could see another's edits would not be answering the same
    question."""
    for arm in ("run_one_shot", "run_agent", "run_best_of"):
        assert "Workspace.clone" in inspect.getsource(getattr(arms, arm))


def test_arms_report_what_they_cost():
    """A claim that the loop is worth it needs the denominator."""
    run = arms.ArmRun(arm="agent", model_calls=5, measurements=5)
    assert run.model_calls == 5 and run.measurements == 5


def test_a_task_naming_no_file_is_refused_rather_than_guessed_at():
    prepared = type("P", (), {"changed_files": ()})()
    assert arms._target_file(prepared) is None


def test_only_the_first_changed_file_is_offered():
    """Understates what an arm could do, which is the conservative direction:
    an arm not allowed to change a file cannot be credited for changing it."""
    prepared = type("P", (), {"changed_files": ("a.py", "b.py")})()
    assert arms._target_file(prepared) == "a.py"
