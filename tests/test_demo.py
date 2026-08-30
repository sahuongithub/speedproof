"""The demonstration, and the honesty conditions it has to meet."""

import ast

from speedproof.hackguard.demo import CASES, HONEST, BASELINE


def test_every_case_is_valid_python():
    ast.parse(HONEST)
    ast.parse(BASELINE)
    for case in CASES:
        ast.parse(case.source)
        ast.parse(case.baseline)


def test_at_least_one_case_must_be_accepted():
    """A demonstration where everything is rejected shows a gate that refuses,
    not a gate that discriminates."""
    assert any(c.should_be_accepted for c in CASES)


def test_the_genuine_case_was_chosen_by_measurement():
    """Not by intuition. Four of seven hand-written candidates were slower
    than the code they replaced."""
    genuine = next(c for c in CASES if c.should_be_accepted)
    assert "measuring" in genuine.provenance


def test_the_genuine_case_adds_no_import():
    """An optimisation that needs a new import pays for it once, and a
    workload run once cannot tell that apart from work moved into the import."""
    genuine = next(c for c in CASES if c.should_be_accepted)
    tree = ast.parse(genuine.source)
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not imports


def test_the_cheats_cite_where_they_come_from():
    """Each is a failure a published benchmark documented, not one invented
    here to be caught."""
    for case in CASES:
        if not case.should_be_accepted:
            assert case.provenance, case.name


def test_each_case_has_its_own_paired_baseline():
    """Or the import cost of the case would be compared against a different
    module's, which is how a real optimisation was first mistaken for a cheat."""
    for case in CASES:
        assert case.baseline.strip()


def test_the_readme_command_exists():
    """The README tells a reader to run this; it should exist."""
    import importlib.util

    assert importlib.util.find_spec("speedproof.hackguard.__main__")


def test_the_demonstration_fails_loudly_if_a_gate_stops_working():
    """It exits non-zero when any case is judged wrongly, so a regression in
    the gates cannot pass unnoticed."""
    import inspect

    from speedproof.hackguard import __main__

    source = inspect.getsource(__main__.main)
    assert "return 0 if all(o.correct for o in outcomes) else 1" in source
