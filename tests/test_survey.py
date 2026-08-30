"""Rules the repository survey must not regress on.

Both cases below are lessons from real false rejections: the first version of
this gate rejected two repositories that are in fact usable.
"""

from speedproof.corpus.survey import _PERF_SUBJECT, _REACHES_OUT, _TIMED_METHOD


def test_reading_a_checked_in_data_file_is_not_reaching_out():
    """A fixed file beside the benchmark is as sealed as a string literal.

    An earlier version listed ``open(`` as disqualifying and rejected a good
    repository for loading its own sample data.
    """
    assert not _REACHES_OUT.search("data = open('version_sample.txt').read()")
    assert not _REACHES_OUT.search("text = Path(__file__).parent.joinpath('s.txt')")


def test_discovering_inputs_at_run_time_is_reaching_out():
    assert _REACHES_OUT.search("for f in glob.glob('*.mlir'):")
    assert _REACHES_OUT.search("subprocess.run(['mlir-opt', path])")
    assert _REACHES_OUT.search("for name in os.listdir(root):")


def test_every_benchmark_convention_counts():
    """Recognising only asv rejects projects that use a different runner."""
    assert _TIMED_METHOD.search("    def time_parse(self):")          # asv
    assert _TIMED_METHOD.search("    def track_size(self):")          # asv
    assert _TIMED_METHOD.search("runner.bench_func('parse', parse)")  # pyperf
    assert _TIMED_METHOD.search("benchmark(lambda: parse(text))")     # pytest-benchmark


def test_a_plain_function_is_not_a_benchmark():
    assert not _TIMED_METHOD.search("def parse(text):")
    assert not _TIMED_METHOD.search("def helper_time_travel():")


def test_perf_subjects_match_several_project_conventions():
    for subject in (
        "perf: add __slots__ to Requirement",
        "perf(markers): cache the default environment",
        "ENH: speed up the tokenizer",
        "Make canonicalisation faster",
        "optimize the rewrite loop",
    ):
        assert _PERF_SUBJECT.search(subject), subject


def test_unrelated_subjects_do_not_match():
    for subject in ("docs: fix a typo", "Bump version to 2.1", "Add a test case"):
        assert not _PERF_SUBJECT.search(subject), subject
