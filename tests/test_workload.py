"""Generating a measurable workload from a project's own benchmark."""

import textwrap

from speedproof.corpus.workload import Benchmark, discover, render

SUITE = textwrap.dedent('''
    from helpers import build

    class Lexer:
        WORKLOAD = build(500)

        def setup(self):
            self.data = build(10)

        def time_constant_100(self):
            lex(Lexer.WORKLOAD)

        def track_tokens(self):
            return 7

        def ignore_time_huge(self):
            lex(build(100000))

        def _time_private(self):
            pass

        def time_parameterised(self, size):
            lex(size)

        def helper(self):
            pass
''')


def write(tmp_path, source=SUITE, name="benchmarks/lexer.py"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return tmp_path


def test_finds_benchmarks_without_importing_them(tmp_path):
    """Importing would run whatever the class body does, which is the cost."""
    tree = write(tmp_path)
    names = {b.method for b in discover(tree, ("benchmarks/lexer.py",))}
    assert names == {"time_constant_100", "track_tokens"}


def test_disabled_benchmarks_are_left_alone(tmp_path):
    """A suite disables a benchmark by renaming it, not by deleting it."""
    tree = write(tmp_path)
    names = {b.method for b in discover(tree, ("benchmarks/lexer.py",))}
    assert "ignore_time_huge" not in names
    assert "_time_private" not in names


def test_parameterised_benchmarks_are_skipped(tmp_path):
    """They need the runner's machinery to supply their arguments."""
    tree = write(tmp_path)
    assert "time_parameterised" not in {
        b.method for b in discover(tree, ("benchmarks/lexer.py",))
    }


def test_a_syntax_error_does_not_stop_discovery(tmp_path):
    tree = write(tmp_path, "class Broken:\n  def time_x(self)\n", "benchmarks/bad.py")
    write(tree)
    found = discover(tree, ("benchmarks/bad.py", "benchmarks/lexer.py"))
    assert {b.method for b in found} == {"time_constant_100", "track_tokens"}


def test_the_pair_differs_only_in_the_call(tmp_path):
    """Everything the import does must be common to both sides."""
    tree = write(tmp_path)
    bench = Benchmark("benchmarks.lexer", "Lexer", "time_constant_100")
    workload, baseline = render(tree, bench)

    assert "_bench.time_constant_100()" in workload
    assert "_bench.time_constant_100()" not in baseline
    # Same imports, same construction, same setup on both sides.
    assert "from benchmarks.lexer import Lexer" in baseline
    assert "_bench = Lexer()" in baseline
    assert "_bench.setup()" in workload and "_bench.setup()" in baseline

    differing = set(workload.splitlines()) ^ set(baseline.splitlines())
    assert differing == {"    _bench.time_constant_100()"}


def test_setup_is_only_called_when_defined(tmp_path):
    tree = write(tmp_path, SUITE.replace("def setup(self):", "def unrelated(self):"))
    workload, baseline = render(
        tree, Benchmark("benchmarks.lexer", "Lexer", "time_constant_100")
    )
    assert "_bench.setup()" not in workload
    assert "_bench.setup()" not in baseline


MODULE_LEVEL = '''
from timeit import default_timer as clock

def bench_R1():
    "a benchmark written as a module-level function"
    compute()

def bench_with_args(n):
    compute(n)

def helper():
    pass
'''


def test_module_level_benchmarks_are_found(tmp_path):
    """Older suites write benchmarks as functions, not methods on a class.
    Recognising only one convention read a repository offering sixty-eight
    optimisations as having no benchmarks at all."""
    path = tmp_path / "sympy" / "benchmarks" / "bench_symbench.py"
    path.parent.mkdir(parents=True)
    path.write_text(MODULE_LEVEL)
    found = discover(tmp_path, ("sympy/benchmarks/bench_symbench.py",))
    assert [b.method for b in found] == ["bench_R1"]
    assert found[0].cls is None
    assert found[0].name == "sympy.benchmarks.bench_symbench.bench_R1"


def test_a_function_benchmark_taking_arguments_is_skipped(tmp_path):
    path = tmp_path / "b.py"
    path.write_text(MODULE_LEVEL)
    assert "bench_with_args" not in {b.method for b in discover(tmp_path, ("b.py",))}


def test_a_function_benchmark_renders_a_matched_pair(tmp_path):
    path = tmp_path / "b.py"
    path.write_text(MODULE_LEVEL)
    bench = discover(tmp_path, ("b.py",))[0]
    workload, baseline = render(tmp_path, bench)
    assert "bench_R1()" in workload
    assert "bench_R1()" not in baseline
    assert "from b import bench_R1" in baseline
    differing = set(workload.splitlines()) ^ set(baseline.splitlines())
    assert differing == {"    bench_R1()"}
