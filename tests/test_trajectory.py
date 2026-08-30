"""The record of what happened, and what it must not omit."""

import json

from speedproof.speedagent.trajectory import (
    INLINE_LIMIT,
    RoundRecord,
    TrajectoryRecord,
)


def record(**kw):
    base = dict(
        task_id="packaging_bce44a", repo="pypa/packaging", arm="agent",
        base_commit="abc123def456789", workload="benchmarks.version.TimeVersion.time_parse",
        baseline_ir=1_000_000, expert_ir=800_000,
    )
    return TrajectoryRecord(**{**base, **kw})


def test_the_kept_round_is_marked_and_the_others_are_not():
    t = record()
    t.rounds = [RoundRecord(1, net_ir=950_000), RoundRecord(2, net_ir=820_000)]
    t.close(stopped_because="no improvement in 2 rounds", selected_round=2)
    assert [r.kept for r in t.rounds] == [False, True]


def test_a_round_card_puts_the_measurement_beside_what_was_done():
    """Separating them is what turns a trajectory into a wall of JSON: the
    adjacency is the causal claim."""
    r = RoundRecord(
        1, net_ir=820_000,
        patch="--- a/m.py\n+++ b/m.py\n-slow_thing()\n+fast_thing()\n",
        profile_shown=True,
    )
    card = r.card(baseline_ir=1_000_000, expert_ir=800_000)
    assert "820,000" in card
    assert "+18.0%" in card
    assert "90% of the expert" in card
    assert "fast_thing" in card
    assert "profile" in card


def test_a_rejected_round_says_why_on_its_card():
    r = RoundRecord(2, rejected="it computes different answers")
    assert "different answers" in r.card(1_000_000, 800_000)


def test_the_selection_rule_is_recorded():
    """The convention requires the selection mechanism, not only the winner."""
    t = record(selection_rule="lowest measured instruction count among "
                              "rounds whose answers matched")
    t.rounds = [RoundRecord(1, net_ir=900_000)]
    t.close("reached the limit of 5 rounds", selected_round=1)
    written = t.to_json()
    assert written["selection"]["rule"]
    assert written["selection"]["selected_round"] == 1
    assert written["selection"]["final_round"] == 1


def test_every_round_is_kept_including_the_failures():
    """Publishing only the successful rounds would be publishing a selection."""
    t = record()
    t.rounds = [
        RoundRecord(1, rejected="the reply contained no edits"),
        RoundRecord(2, net_ir=900_000),
    ]
    t.close("done", selected_round=2)
    assert len(t.to_json()["rounds"]) == 2


def test_token_counts_use_the_standard_names():
    """Private names would cost the same and make the record readable only by
    this project."""
    t = record()
    t.rounds = [RoundRecord(1, net_ir=900_000, input_tokens=1200, output_tokens=300)]
    row = t.to_json()["rounds"][0]
    assert row["gen_ai.usage.input_tokens"] == 1200
    assert row["gen_ai.usage.output_tokens"] == 300


def test_a_long_exchange_is_shortened_rather_than_dropped():
    t = record()
    t.rounds = [RoundRecord(1, prompt="x" * (INLINE_LIMIT * 3), net_ir=900_000)]
    written = t.to_json()["rounds"][0]["prompt"]
    assert len(written) < INLINE_LIMIT * 2
    assert "elided" in written


def test_the_readable_page_states_who_measured():
    """A reader should not have to take the separation on trust."""
    t = record()
    t.rounds = [RoundRecord(1, net_ir=900_000)]
    t.close("done", selected_round=1)
    page = t.to_markdown()
    assert "the agent cannot reach" in page
    assert "never measured anything itself" in page


def test_the_expert_is_shown_as_the_target():
    t = record()
    t.close("done", selected_round=None)
    assert "800,000" in t.to_markdown()


def test_both_files_are_written(tmp_path):
    t = record()
    t.rounds = [RoundRecord(1, net_ir=900_000)]
    t.close("done", selected_round=1)
    js, md = t.write(tmp_path)
    assert js.name == "packaging_bce44a__agent.json"
    assert md.name == "packaging_bce44a__agent.md"
    assert json.loads(js.read_text())["schema"].startswith("speedproof-trajectory")


def test_a_run_that_produced_nothing_still_records_that(tmp_path):
    """A trajectory missing because the arm failed is the case a reader most
    wants to see."""
    t = record()
    t.rounds = [RoundRecord(1, rejected="the model was unavailable")]
    t.close("the model was unavailable", selected_round=None)
    assert "nothing was kept" in t.to_markdown()
    assert t.to_json()["selection"]["selected_round"] is None
