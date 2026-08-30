"""Turning a project's own benchmark into something measurable.

A benchmark under the common convention is a class whose ``time_*`` methods
perform the work and whose inputs are built once, when the class is defined.
That last part is the difficulty. Importing the module can cost far more than
running the benchmark -- one xdsl lexer benchmark builds a 500x500 tensor at
class scope, and measuring it against an empty baseline came to 27 billion
instructions, almost none of which was lexing.

So each workload is generated as a *pair*. Both files import the same module
and construct the same object; only one of them calls the benchmark. Everything
the import does is common to the two and subtracts away exactly, leaving the
call under study.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

#: Method-name prefixes that mark a benchmark under the conventions in use.
_BENCHMARK_PREFIX = ("time_", "track_")

#: Benchmarks a project has explicitly turned off. asv suites disable a method
#: by renaming rather than deleting it, and running one anyway measures
#: something the project decided was not worth measuring.
_DISABLED_PREFIX = ("ignore_", "skip_", "_")

_WORKLOAD_TEMPLATE = '''\
# Generated from {module}.{cls}.{method} in the project under measurement.
# The paired baseline is identical except that run() does nothing, so the cost
# of importing this module cancels exactly and only the benchmarked call is left.
import sys

# A project may keep its package under src/, so both are on the path. The
# order matters: the tree root first, since that is where the benchmark
# package itself lives.
sys.path.insert(0, "/work")
sys.path.insert(1, "/work/src")

from {module} import {cls}

_bench = {cls}()
{setup}

def run():
{body}
'''


@dataclass(frozen=True)
class Benchmark:
    """One callable benchmark found in a project's suite."""

    module: str
    cls: str
    method: str

    @property
    def name(self) -> str:
        return f"{self.module}.{self.cls}.{self.method}"


def discover(tree: Path, benchmark_files: tuple[str, ...]) -> list[Benchmark]:
    """Find the benchmarks a tree offers, without importing anything.

    Parsing rather than importing matters: importing a benchmark module runs
    whatever it does at class scope, which for some suites is most of the cost
    of the benchmark itself.
    """
    found: list[Benchmark] = []
    for relative in benchmark_files:
        path = tree / relative
        if not path.is_file():
            continue
        try:
            module_ast = ast.parse(path.read_text(errors="replace"), str(path))
        except SyntaxError:
            continue
        module = relative[: -len(".py")].replace("/", ".")
        for node in module_ast.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                name = item.name
                if name.startswith(_DISABLED_PREFIX):
                    continue
                if not name.startswith(_BENCHMARK_PREFIX):
                    continue
                if any(a.arg != "self" for a in item.args.args):
                    # asv parameterised benchmarks take their arguments from
                    # class attributes the runner supplies; calling one
                    # directly would need that machinery.
                    continue
                found.append(Benchmark(module=module, cls=node.name, method=name))
    return found


def _setup_call(tree: Path, benchmark: Benchmark) -> str:
    """A ``setup()`` call, when the benchmark class defines one."""
    path = tree / (benchmark.module.replace(".", "/") + ".py")
    try:
        source = path.read_text(errors="replace")
    except OSError:
        return ""
    pattern = re.compile(
        rf"class\s+{re.escape(benchmark.cls)}\b.*?(?=^class\s|\Z)",
        re.S | re.M,
    )
    match = pattern.search(source)
    if match and re.search(r"^\s+def\s+setup\s*\(\s*self\s*\)", match.group(), re.M):
        return "_bench.setup()\n"
    return ""


def render(tree: Path, benchmark: Benchmark) -> tuple[str, str]:
    """Return the workload and its paired baseline, as source text."""
    setup = _setup_call(tree, benchmark)
    workload = _WORKLOAD_TEMPLATE.format(
        module=benchmark.module,
        cls=benchmark.cls,
        method=benchmark.method,
        setup=setup,
        body=f"    _bench.{benchmark.method}()\n    return None",
    )
    baseline = _WORKLOAD_TEMPLATE.format(
        module=benchmark.module,
        cls=benchmark.cls,
        method=benchmark.method,
        setup=setup,
        body="    return None",
    )
    return workload, baseline


def install(tree: Path, benchmark: Benchmark) -> tuple[Path, Path]:
    """Write the workload pair into ``tree`` and return their relative paths."""
    workload, baseline = render(tree, benchmark)
    stem = f"_sp_{benchmark.cls}_{benchmark.method}".lower()
    (tree / f"{stem}.py").write_text(workload)
    (tree / f"{stem}_baseline.py").write_text(baseline)
    return Path(f"{stem}.py"), Path(f"{stem}_baseline.py")
