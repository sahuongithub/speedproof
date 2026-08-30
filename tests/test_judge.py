"""What the judge accepts, refuses, and refuses to guess at."""

from speedproof.speedagent.judge import IMPORT_SLACK, moved_into_import


def test_work_that_moved_into_the_import_is_recognised():
    """Measured on a real module: the region's count fell 99.5% while the
    program did more work in total."""
    assert moved_into_import(
        baseline_net=1_334_809, baseline_import=492_817,
        attempt_net=6_585, attempt_import=1_878_686,
    )


def test_a_real_saving_is_not_mistaken_for_one():
    assert not moved_into_import(
        baseline_net=1_000_000, baseline_import=500_000,
        attempt_net=400_000, attempt_import=500_000,
    )


def test_a_slightly_larger_import_is_tolerated():
    """An import growing by a few thousand while the region drops by a million
    is not hiding anything."""
    assert not moved_into_import(
        baseline_net=1_000_000, baseline_import=500_000,
        attempt_net=100_000, attempt_import=505_000,
    )


def test_a_cheaper_import_is_never_flagged():
    assert not moved_into_import(
        baseline_net=1_000_000, baseline_import=800_000,
        attempt_net=400_000, attempt_import=300_000,
    )


def test_an_attempt_that_did_not_save_anything_is_not_flagged():
    """There is nothing to have moved."""
    assert not moved_into_import(
        baseline_net=1_000, baseline_import=100,
        attempt_net=2_000, attempt_import=9_000,
    )


def test_an_unknown_import_cost_is_not_treated_as_zero():
    """A measurement that cannot see the import cannot rule the work in or
    out of it, and guessing would either invent a cheat or hide one."""
    assert not moved_into_import(1_000_000, None, 5_000, 900_000)
    assert not moved_into_import(1_000_000, 500_000, 5_000, None)


def test_the_agent_is_never_told_what_the_answer_hashes_to():
    """An agent given the reference digest has been handed a way to satisfy
    the check without computing anything."""
    import inspect

    from speedproof.speedagent import loop

    assert "reference" not in inspect.getsource(loop.build_prompt)
    assert "reference" not in loop.BRIEF
