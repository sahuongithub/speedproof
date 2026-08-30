"""The controller's decisions, driven by a fake model so they can be checked.

Every test here fixes a decision the controller makes on the agent's behalf,
because the agent is not permitted to make any of them.
"""

import pytest

from speedproof.speedagent.controller import Judgement, ModelUnavailable, run
from speedproof.speedagent.workspace import Workspace


def edit_reply(find, replace):
    return f"<<<<<<< SEARCH\n{find}\n=======\n{replace}\n>>>>>>> REPLACE\n"


@pytest.fixture
def workspace(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "m.py").write_text("value = 1\n")
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        yield ws


def scripted(*replies):
    """A model that says these things, in order."""
    remaining = list(replies)

    def ask(prompt):
        if not remaining:
            raise ModelUnavailable("no more scripted replies")
        return remaining.pop(0)

    return ask


def scoring(*counts):
    """A harness that returns these measurements, in order."""
    remaining = list(counts)

    def judge(workspace):
        value = remaining.pop(0) if remaining else None
        if isinstance(value, str):
            return Judgement(rejected=value)
        return Judgement(net_ir=value, equivalent=True)

    return judge


def test_the_loop_runs_until_the_controller_stops_it(workspace):
    """Not until the agent says it is done: three quarters of trajectories in
    the surveyed work stop early with budget remaining."""
    t = run(
        workspace, "m.py",
        judge=scoring(900, 800, 700),
        task="t", baseline_ir=1000,
        rounds=3, patience=5,
        ask_model=scripted(
            edit_reply("value = 1", "value = 2"),
            edit_reply("value = 1", "value = 3"),
            edit_reply("value = 1", "value = 4"),
        ),
    )
    assert len(t.rounds) == 3
    assert "reached the limit" in t.stopped_because


def test_it_stops_when_rounds_stop_helping(workspace):
    """The measurement is exact, so a round that does not improve did not
    improve -- there is no noise for it to have been."""
    t = run(
        workspace, "m.py",
        judge=scoring(500, 900, 950),
        task="t", baseline_ir=1000,
        rounds=5, patience=2,
        ask_model=scripted(
            edit_reply("value = 1", "value = 2"),
            edit_reply("value = 1", "value = 3"),
            edit_reply("value = 1", "value = 4"),
        ),
    )
    assert len(t.rounds) == 3
    assert "no improvement" in t.stopped_because
    assert t.best.net_ir == 500


def test_the_workspace_ends_holding_the_best_attempt(workspace):
    """Not the last one. Published turn-by-turn figures end on a regression."""
    run(
        workspace, "m.py",
        judge=scoring(400, 800),
        task="t", baseline_ir=1000,
        rounds=2, patience=5,
        ask_model=scripted(
            edit_reply("value = 1", "value = 2"),
            edit_reply("value = 1", "value = 3"),
        ),
    )
    assert workspace.read("m.py") == "value = 2\n"


def test_a_repeated_attempt_is_not_measured_twice(workspace):
    """Measuring a repeat costs a Valgrind run to learn what is known."""
    same = edit_reply("value = 1", "value = 2")
    t = run(
        workspace, "m.py",
        judge=scoring(500),
        task="t", baseline_ir=1000,
        rounds=3, patience=5,
        ask_model=scripted(same, same, same),
    )
    measured = [r for r in t.rounds if r.net_ir is not None]
    assert len(measured) == 1
    assert any("already tried" in (r.rejected or "") for r in t.rounds)


def test_a_rejected_attempt_does_not_become_the_answer(workspace):
    t = run(
        workspace, "m.py",
        judge=scoring("it computes different answers"),
        task="t", baseline_ir=1000,
        rounds=1, patience=5,
        ask_model=scripted(edit_reply("value = 1", "value = 99")),
    )
    assert t.best is None
    assert workspace.read("m.py") == "value = 1\n"


def test_an_unusable_reply_costs_a_round_and_not_the_run(workspace):
    t = run(
        workspace, "m.py",
        judge=scoring(500),
        task="t", baseline_ir=1000,
        rounds=2, patience=5,
        ask_model=scripted(
            "I would suggest using a comprehension.",
            edit_reply("value = 1", "value = 2"),
        ),
    )
    assert t.rounds[0].rejected
    assert t.rounds[1].accepted


def test_an_unavailable_model_ends_the_run_and_says_so(workspace):
    def unavailable(prompt):
        raise ModelUnavailable("rate limited")

    t = run(
        workspace, "m.py", judge=scoring(), task="t", baseline_ir=1000,
        rounds=3, ask_model=unavailable,
    )
    assert t.rounds == []
    assert "unavailable" in t.stopped_because


def test_the_agent_never_measures_anything():
    """The judge is passed in, so the loop has nothing to measure with."""
    import inspect

    from speedproof.speedagent import controller

    source = inspect.getsource(controller)
    assert "from speedproof.verifyperf" not in source
    assert "measure(" not in source


def test_rounds_that_produce_nothing_usable_still_run_out_of_patience(workspace):
    """Otherwise a run whose every reply is unusable asks the model the same
    question to the limit and gets the same answer."""
    t = run(
        workspace, "m.py",
        judge=scoring(),
        task="t", baseline_ir=1000,
        rounds=5, patience=2,
        ask_model=scripted(*["no code here"] * 5),
    )
    assert len(t.rounds) == 2
    assert "no improvement" in t.stopped_because
