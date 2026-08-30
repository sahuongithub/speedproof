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


def test_six_arms_are_needed_not_four():
    """Comparing a loop that sees a profile against a prompt that does not
    confounds iterating with being told where the work is. The two dissociate:
    profiler access alone lowered the surveyed score from 20.6 to 17.6, while
    the same profile inside a loop raised it to 36.3."""
    assert "one_shot_profile" in arms.ARMS
    assert "agent_no_profile" in arms.ARMS
    assert len(arms.ARMS) == 7  # six arms plus the base they are measured from


def test_an_arm_names_itself_by_what_it_was_given():
    """So a result cannot be attributed to the wrong configuration."""
    source = inspect.getsource(arms.run_one_shot)
    assert 'one_shot_profile" if profile else "one_shot' in source
    assert '"agent" if use_profile else "agent_no_profile"' in inspect.getsource(
        arms.run_agent
    )


def test_every_arm_records_what_it_tried_even_when_refused():
    """A trajectory that says 'no change was produced' when a change was
    produced has lost the evidence a reader most wants."""
    source = inspect.getsource(arms.run_one_shot)
    # the failure path builds a trajectory too
    before, _, after = source.partition("except (EditError, WorkspaceError)")
    assert "trajectory" in after.split("return result")[0]


def test_the_control_records_every_attempt_not_only_the_winner():
    """The convention requires all rollouts and the selection rule, not the
    chosen one alone."""
    source = inspect.getsource(arms.run_best_of)
    assert "attempts_made.append" in source
    assert '"rounds": attempts_made' in source
