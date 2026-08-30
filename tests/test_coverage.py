"""Turning container coverage into something the selector can use."""

from speedproof.corpus.coverage import _COLLECTOR, _relative, summarise


def test_repository_paths_are_made_relative():
    """Coverage reports container paths; a diff names repository paths."""
    assert _relative("/work/xdsl/parser.py") == "xdsl/parser.py"


def test_library_and_harness_paths_are_dropped():
    """Neither can appear in a patch, so neither can inform selection."""
    assert _relative("/usr/local/lib/python3.12/json/decoder.py") is None
    assert _relative("/tmp/harness/speedproof/verifyperf/inner.py") is None
    assert _relative("<frozen importlib._bootstrap>") is None


def test_paths_outside_the_tree_are_dropped():
    assert _relative("/tmp/collect.py") is None


def test_measurement_starts_after_the_import():
    """Everything a module does on import is common to every workload in its
    suite. Measured the other way round, four xdsl benchmarks shared 6,652 of
    their ~6,700 covered lines; measured this way they share none."""
    body = _COLLECTOR
    import_at = body.index("mod = __import__")
    construct_at = body.index("bench = getattr(mod, cls)()")
    start_at = body.index("cov.start()")
    assert import_at < start_at, "the import must not be measured"
    assert construct_at < start_at, "construction must not be measured"


def test_setup_runs_before_measurement_too():
    body = _COLLECTOR
    assert body.index("bench.setup()") < body.index("cov.start()")


def test_only_the_call_is_measured():
    body = _COLLECTOR
    between = body[body.index("cov.start()"):body.index("cov.stop()")]
    assert "getattr(bench, method)()" in between
    assert "__import__" not in between


def test_an_empty_map_says_so_rather_than_pretending():
    assert "no workload produced coverage" in summarise({})
