"""The command a person actually uses."""

from pathlib import Path

from speedproof.optimise import EXAMPLE, _install


def test_the_example_is_valid_and_has_the_shape_required(tmp_path):
    import ast

    ast.parse(EXAMPLE)
    assert "def run()" in EXAMPLE
    namespace = {}
    exec(EXAMPLE, namespace)
    assert namespace["run"]() is not None, "run() must return its result"


def test_the_baseline_keeps_the_imports_and_drops_the_work(tmp_path):
    """Subtracting it removes what the module does when it loads, so the
    measurement is of the work rather than of the import."""
    source = tmp_path / "s.py"
    source.write_text(
        "import math\n\nDATA = list(range(10))\n\n\n"
        "def run():\n    total = 0\n    for x in DATA:\n"
        "        total += math.sqrt(x)\n    return total\n"
    )
    staging = tmp_path / "staging"
    workload, baseline = _install(source, staging)

    text = (staging / baseline).read_text()
    assert "import math" in text, "the import is kept"
    assert "DATA = list(range(10))" in text, "module-level work is kept"
    assert "math.sqrt" not in text, "the body of run() is dropped"
    assert "return None" in text

    namespace = {}
    exec(text, namespace)
    assert namespace["run"]() is None


def test_the_subject_is_copied_unchanged(tmp_path):
    source = tmp_path / "s.py"
    source.write_text("def run():\n    return 1\n")
    staging = tmp_path / "staging"
    workload, _ = _install(source, staging)
    assert (staging / workload).read_text() == source.read_text()


def test_a_function_after_run_is_not_swallowed(tmp_path):
    """The baseline drops the body of run() and nothing else."""
    source = tmp_path / "s.py"
    source.write_text(
        "def run():\n    return helper()\n\n\ndef helper():\n    return 7\n"
    )
    staging = tmp_path / "staging"
    _, baseline = _install(source, staging)
    text = (staging / baseline).read_text()
    assert "def helper():" in text
    assert "return 7" in text
