"""Workload selection, including every way it could silently select nothing.

Each escalation below corresponds to a measured false negative in the published
implementations of this idea.
"""

from speedproof.corpus.relevance import (
    Selection,
    patch_scope,
    select_workloads,
)

ALL = ("lexer", "parser", "printer")


def diff(path, start=10, count=3):
    return (
        f"--- a/{path}\n+++ b/{path}\n"
        f"@@ -{start},{count} +{start},{count} @@\n"
        "-old\n+new\n"
    )


def test_changed_lines_are_read_from_the_post_image():
    scope = patch_scope(diff("pkg/mod.py", start=100, count=4))
    assert scope.lines == {"pkg/mod.py": {100, 101, 102, 103}}


def test_a_workload_covering_the_change_is_selected():
    cov = {"lexer": {"pkg/mod.py": {100, 101}}, "parser": {"pkg/other.py": {5}}}
    sel = select_workloads(diff("pkg/mod.py", 100, 2), cov, ALL)
    assert sel.reason is Selection.COVERED
    assert sel.workloads == ("lexer",)


def test_a_data_file_change_escalates_to_everything():
    """Coverage never reports a .json, so a change to one looks like nothing."""
    sel = select_workloads(diff("pkg/table.json"), {"lexer": {}}, ALL)
    assert sel.reason is Selection.ALL_UNTRACEABLE
    assert sel.workloads == ALL


def test_a_compiled_extension_change_escalates_to_everything():
    sel = select_workloads(diff("pkg/_speedups.c"), {"lexer": {}}, ALL)
    assert sel.reason is Selection.ALL_UNTRACEABLE


def test_an_import_time_change_escalates_to_everything():
    """__init__ runs before any workload, so coverage cannot attribute it."""
    sel = select_workloads(diff("pkg/__init__.py"), {"lexer": {"pkg/m.py": {1}}}, ALL)
    assert sel.reason is Selection.ALL_IMPORT_TIME
    assert sel.workloads == ALL


def test_missing_coverage_escalates_rather_than_selecting_none():
    sel = select_workloads(diff("pkg/mod.py"), None, ALL)
    assert sel.reason is Selection.ALL_NO_COVERAGE
    assert sel.workloads == ALL


def test_a_test_only_change_needs_no_workload():
    sel = select_workloads(diff("tests/test_mod.py"), {"lexer": {}}, ALL)
    assert sel.reason is Selection.NONE_TESTS_ONLY
    assert not sel.measurable


def test_no_covering_workload_is_reported_not_silently_skipped():
    """The task is unmeasurable, and says so, rather than passing vacuously."""
    cov = {"lexer": {"pkg/elsewhere.py": {1, 2}}}
    sel = select_workloads(diff("pkg/mod.py"), cov, ALL)
    assert not sel.measurable
    assert "observed" in sel.detail


def test_a_test_file_does_not_count_as_untraceable():
    """Test fixtures are not behaviour, so a .txt under tests/ is not an escalation."""
    scope = patch_scope(diff("tests/data/sample.txt"))
    assert scope.untraceable_files == set()
