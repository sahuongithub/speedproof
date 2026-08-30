"""What the profile is, and what it deliberately is not."""

from pathlib import Path

from speedproof.speedagent.profile import (
    _COLLECTOR,
    HotFunction,
    HotLine,
    Profile,
    _annotate,
)


def test_no_times_are_collected():
    """Times vary between runs. A profile that changes when nothing else has
    invites the reader to chase noise, so only counts are collected."""
    assert "time" not in _COLLECTOR.lower()
    assert "line_counts" in _COLLECTOR and "call_counts" in _COLLECTOR


def test_only_the_project_under_measurement_is_profiled():
    """The standard library is not something a patch can change."""
    assert 'startswith(("/work/", "/tmp/workload"))' in _COLLECTOR


def test_counts_are_rendered_beside_the_source_they_describe():
    """Three hundred executions of an append and of a list concatenation look
    identical as numbers and are not the same amount of work."""
    profile = Profile(
        lines=[HotLine("/work/m.py", 4, 300, "    out = out + [i * i]")],
        functions=[HotFunction("/work/m.py", "helper", 6, 300)],
    )
    rendered = profile.render()
    assert "300 x" in rendered
    assert "out = out + [i * i]" in rendered
    assert "m.py:4" in rendered
    assert "helper" in rendered


def test_an_empty_profile_renders_to_nothing():
    """So a prompt built from it says nothing rather than saying nothing at
    length."""
    assert Profile().render() == ""
    assert Profile().empty


def test_source_text_is_attached_to_each_hot_line(tmp_path):
    (tmp_path / "m.py").write_text("a = 1\nb = 2\nc = 3\n")
    annotated = _annotate([HotLine("m.py", 2, 99)], tmp_path)
    assert annotated[0].text == "b = 2"


def test_annotation_never_falls_back_to_a_same_named_file(tmp_path):
    """Searching the tree by file name found an unrelated module and annotated
    correct counts with its source, which looked entirely plausible."""
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "workload.py").write_text("WRONG = 'other module'\n")
    annotated = _annotate([HotLine("workload.py", 1, 5)], tmp_path)
    assert annotated[0].text == ""


def test_a_line_number_past_the_end_does_not_raise(tmp_path):
    """The profile and the source can disagree if a tree changed underneath."""
    (tmp_path / "m.py").write_text("a = 1\n")
    assert _annotate([HotLine("m.py", 99, 1)], tmp_path)[0].text == ""


def test_a_missing_source_file_does_not_raise(tmp_path):
    assert _annotate([HotLine("gone.py", 1, 1)], tmp_path)[0].text == ""
