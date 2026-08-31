"""The loop's mechanics, and the ways a model gets an edit slightly wrong."""

import pytest

from speedproof.speedagent.loop import (
    Edit,
    EditError,
    Round,
    Trajectory,
    parse_edits,
    patch_fingerprint,
)

REPLY = """\
Here is the change.

<<<<<<< SEARCH
    out = out + [i * i]
=======
    out.append(i * i)
>>>>>>> REPLACE
"""


def test_a_search_replace_block_is_read():
    edits = parse_edits(REPLY)
    assert len(edits) == 1
    assert edits[0].find == "    out = out + [i * i]"
    assert edits[0].replace == "    out.append(i * i)"


def test_several_blocks_are_all_read():
    reply = REPLY + REPLY.replace("out", "acc")
    assert len(parse_edits(reply)) == 2


def test_prose_without_a_block_yields_nothing():
    assert parse_edits("I would suggest using a list comprehension.") == []


def test_an_exact_edit_applies():
    text = "def f():\n    out = out + [i * i]\n    return out\n"
    assert "out.append" in parse_edits(REPLY)[0].apply_to(text)


def test_an_edit_applies_despite_lost_indentation():
    """Models routinely reproduce a block with its shared indentation stripped.
    Rejecting an edit whose intent is unambiguous costs more than being
    careful, since even frontier models malform this format a few per cent of
    the time."""
    edit = Edit(find="out = out + [i * i]", replace="out.append(i * i)")
    text = "def f():\n    out = out + [i * i]\n    return out\n"
    result = edit.apply_to(text)
    assert "    out.append(i * i)" in result, "the replacement should keep the file's indentation"


def test_an_edit_that_matches_nothing_is_refused():
    """Rather than silently changing nothing and being measured as a null."""
    edit = Edit(find="nowhere_in_the_file()", replace="x")
    with pytest.raises(EditError, match="does not appear"):
        edit.apply_to("def f():\n    pass\n")


def test_only_the_first_occurrence_is_replaced():
    edit = Edit(find="x = 1", replace="x = 2")
    assert edit.apply_to("x = 1\nx = 1\n") == "x = 2\nx = 1\n"


def test_the_best_round_is_kept_not_the_last():
    """Published turn-by-turn figures end on a regression; an agent judged on
    where it finished would lose most of what it found."""
    t = Trajectory("task", baseline_ir=1000)
    t.rounds = [
        Round(1, net_ir=900), Round(2, net_ir=400), Round(3, net_ir=650),
    ]
    assert t.best.number == 2
    assert t.improvement == pytest.approx(0.6)


def test_a_rejected_round_cannot_be_the_best():
    t = Trajectory("task", baseline_ir=1000)
    t.rounds = [Round(1, net_ir=10, rejected="it computes different answers")]
    assert t.best is None
    assert t.improvement == 0.0


def test_the_history_ranks_and_includes_failures():
    """An agent shown only its last attempt cannot see that it is going round
    in circles; one shown only successes cannot learn what was rejected."""
    t = Trajectory("task", baseline_ir=1000)
    t.rounds = [
        Round(1, net_ir=900),
        Round(2, rejected="it computes different answers"),
        Round(3, net_ir=400),
    ]
    history = t.history()
    assert history.index("400") < history.index("900"), "best first"
    assert "different answers" in history


def test_no_history_before_the_first_round():
    assert Trajectory("task", baseline_ir=1000).history() == ""


def test_the_same_patch_is_recognised():
    """Measuring a repeat costs a Valgrind run to learn what is already known."""
    assert patch_fingerprint("a") == patch_fingerprint("a")
    assert patch_fingerprint("a") != patch_fingerprint("b")


def test_the_brief_forbids_each_way_of_not_optimising():
    """Named explicitly, because an agent that does not know a route is closed
    will spend a round discovering it."""
    from speedproof.speedagent.loop import BRIEF

    for closed in ("import", "Caching", "Deferring", "fast path"):
        assert closed in BRIEF


def test_the_brief_is_the_same_for_both_arms():
    """A loop compared against a baseline given a worse prompt measures the
    prompt. The surveyed literature reports this inflating published
    self-correction results."""
    from speedproof.speedagent.loop import BRIEF, build_prompt

    first_turn = build_prompt("x = 1", "m.py")
    assert "What has already been tried" not in first_turn
    assert BRIEF.split("{profile}")[0] in first_turn


def test_the_profile_appears_only_when_there_is_one():
    from speedproof.speedagent.loop import build_prompt
    from speedproof.speedagent.profile import HotLine, Profile

    assert "profiled" not in build_prompt("x = 1", "m.py", Profile())
    profiled = build_prompt(
        "x = 1", "m.py", Profile(lines=[HotLine("m.py", 1, 300, "x = 1")])
    )
    assert "profiled" in profiled and "300" in profiled


def test_all_edits_apply_or_none_do(tmp_path):
    """A half-edited file parses differently and measures differently, which is
    worse than an attempt that plainly failed."""
    from speedproof.speedagent.loop import apply_edits
    from speedproof.speedagent.workspace import Workspace

    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "m.py").write_text("a = 1\nb = 2\n")
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        good = Edit(find="a = 1", replace="a = 11")
        bad = Edit(find="nowhere", replace="x")
        with pytest.raises(EditError):
            apply_edits(ws, "m.py", [good, bad])
        assert ws.read("m.py") == "a = 1\nb = 2\n"


def test_the_same_change_hashes_the_same_when_written_twice():
    """A unified diff names each file with a path and a modification time, so
    two byte-identical changes written a moment apart hash differently. The
    failure is invisible on a fast machine and appears on a slower one."""
    first = (
        "diff -u -r --new-file /tmp/a/m.py\t2026-08-31 01:32:11.551084892 +0000\n"
        "--- /tmp/a/m.py\t2026-08-31 01:32:11.551084892 +0000\n"
        "+++ /tmp/b/m.py\t2026-08-31 01:32:11.559112004 +0000\n"
        "@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    )
    second = first.replace("01:32:11.551084892", "01:33:47.220118773").replace(
        "01:32:11.559112004", "01:33:47.881204551"
    )
    assert patch_fingerprint(first) == patch_fingerprint(second)


def test_different_changes_still_differ():
    a = "--- x\n+++ y\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    b = "--- x\n+++ y\n@@ -1 +1 @@\n-value = 1\n+value = 3\n"
    assert patch_fingerprint(a) != patch_fingerprint(b)


def test_a_round_with_no_measurement_and_no_refusal_is_representable():
    """This text goes into the next round's prompt; a bookkeeping gap should
    not end a run."""
    assert "no measurement" in Round(2, net_ir=None).summarise(1000)
