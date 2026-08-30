"""Finding where a workload spends its work, deterministically.

The obvious instrument is the one already running. Callgrind attributes every
instruction to a function, so the profile ought to be free -- and for a C
program it would be. For Python it is worthless: Callgrind sees machine
functions, so a profile of a Python workload is a list of CPython's internals,
``_PyEval_EvalFrameDefault`` and unnamed addresses inside libpython, with the
user's own code nowhere in it. That is a property of where the instructions
really are, not a defect in the tool, and it means the research advice to check
a patch's functions against the Callgrind profile does not transfer to Python.

What does work is counting, which suits this project better anyway. Two counts,
both exact and both reproducible to the unit:

* how many times each **line** executed, which is what exposes a loop doing
  quadratic work,
* how many times each **function** was called, which is what exposes a cheap
  function called from somewhere expensive.

Neither is a measure of cost. A line that runs three hundred times may be
trivial or may be copying a growing list, and the counts alone cannot tell them
apart -- the source can, which is why the profile is rendered against the source
rather than as bare numbers. Times are deliberately not collected: they would
vary between runs, and a profile that changes when nothing else has is a
profile that invites the reader to chase noise.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from speedproof.verifyperf.callgrind import (
    MeasurementError,
    _docker,
    _install_harness_script,
    ensure_image,
    image_tag,
)
from speedproof.verifyperf.session import install_cleanup, label_args

#: How many hot lines and functions to show. Enough to point somewhere, few
#: enough that the prompt is not mostly profile.
TOP_LINES = 12
TOP_FUNCTIONS = 8

_COLLECTOR = '''
import collections, gc, json, sys

gc.disable()
sys.path.insert(0, "/work")
sys.path.insert(1, "/work/src")

target = sys.argv[1]
# The caller's own name for this file. The container works on a copy, and
# reporting the copy's path lets a same-named file elsewhere in the tree be
# annotated instead -- which produced a profile whose counts were right and
# whose source lines came from an unrelated module.
reported_as = sys.argv[2]
source = open(target).read()
namespace = {"__name__": "_sp_workload", "__file__": target}
exec(compile(source, target, "exec"), namespace)
run = namespace["run"]

line_counts = collections.Counter()
call_counts = collections.Counter()


def tracer(frame, event, arg):
    code = frame.f_code
    name = code.co_filename
    if name.startswith(("/work/", "/tmp/workload")):
        name = reported_as if name.startswith("/tmp/workload") else name[len("/work/"):]
        if event == "line":
            line_counts[(name, frame.f_lineno)] += 1
        elif event == "call":
            call_counts[(name, code.co_name, code.co_firstlineno)] += 1
    return tracer


sys.settrace(tracer)
try:
    run()
finally:
    sys.settrace(None)

json.dump(
    {
        "lines": [[f, n, c] for (f, n), c in line_counts.most_common(200)],
        "functions": [[f, name, n, c]
                      for (f, name, n), c in call_counts.most_common(100)],
    },
    sys.stdout,
)
'''


@dataclass(frozen=True)
class HotLine:
    path: str
    line: int
    count: int
    text: str = ""


@dataclass(frozen=True)
class HotFunction:
    path: str
    name: str
    line: int
    calls: int


@dataclass
class Profile:
    """Where a workload's work goes, as counts rather than as time."""

    lines: list[HotLine] = field(default_factory=list)
    functions: list[HotFunction] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.lines and not self.functions

    def render(self, top_lines: int = TOP_LINES, top_functions: int = TOP_FUNCTIONS) -> str:
        """A compact table, rendered against the source it describes.

        The counts are shown beside the code they belong to because the count
        alone is ambiguous: three hundred executions of a list append and three
        hundred of a list concatenation look identical as numbers and are not
        remotely the same amount of work.
        """
        if self.empty:
            return ""
        out: list[str] = []
        if self.lines:
            out.append("lines by execution count")
            width = max(len(f"{h.count:,}") for h in self.lines[:top_lines])
            for hot in self.lines[:top_lines]:
                where = f"{Path(hot.path).name}:{hot.line}"
                text = hot.text.strip()[:64]
                out.append(f"  {hot.count:>{width},} x  {where:<22} {text}")
        if self.functions:
            out.append("")
            out.append("functions by call count")
            for fn in self.functions[:top_functions]:
                where = f"{Path(fn.path).name}:{fn.line}"
                out.append(f"  {fn.calls:>9,} x  {fn.name:<28} {where}")
        return "\n".join(out)


def _annotate(hot_lines: list[HotLine], workspace: Path) -> list[HotLine]:
    """Attach the source text of each hot line."""
    cache: dict[str, list[str]] = {}
    annotated: list[HotLine] = []
    for hot in hot_lines:
        # Exact relative path only. Searching the tree for a matching file name
        # will find a same-named module elsewhere and annotate the counts with
        # somebody else's source.
        if hot.path not in cache:
            candidate = workspace / hot.path
            cache[hot.path] = (
                candidate.read_text(errors="replace").splitlines()
                if candidate.is_file() else []
            )
        source = cache[hot.path]
        line = source[hot.line - 1] if 0 < hot.line <= len(source) else ""
        annotated.append(HotLine(hot.path, hot.line, hot.count, line))
    return annotated


def collect(
    workspace: Path,
    workload: Path,
    image: str | None = None,
    platform: str | None = None,
    timeout: int = 900,
) -> Profile:
    """Profile one workload, in the container the measurement uses.

    A profile that cannot be collected is returned empty rather than raised on:
    the agent can work without one, and losing a task because its profile
    failed would trade information for nothing.
    """
    if image is None:
        ensure_image(platform=platform)
    install_cleanup()
    workspace = Path(workspace).resolve()
    relative = workload.relative_to(workspace) if workload.is_absolute() else workload

    script = f"""
set -e
cd /tmp
{_install_harness_script()}
cat > /tmp/collect.py <<'COLLECT_EOF'
{_COLLECTOR}
COLLECT_EOF
cp /work/{relative} /tmp/workload.py
export PYTHONPATH=/tmp/harness:/work
echo "---PROFILE---"
python3 /tmp/collect.py /tmp/workload.py "{relative}"
"""
    try:
        proc = subprocess.run(
            [_docker(), "run", "--rm", "-i", "--network", "none"]
            + label_args()
            + (["--platform", platform] if platform else [])
            + [
                "-v", f"{workspace}:/work:ro",
                "-e", "PYTHONHASHSEED=0",
                "-e", "PYTHON_JIT=0",
                image or image_tag(platform), "bash", "-s",
            ],
            input=script.encode(),
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return Profile()

    text = proc.stdout.decode(errors="replace")
    if proc.returncode != 0 or "---PROFILE---" not in text:
        return Profile()
    try:
        payload = json.loads(text.split("---PROFILE---", 1)[1].strip())
    except (json.JSONDecodeError, IndexError):
        return Profile()

    lines = [HotLine(p, n, c) for p, n, c in payload.get("lines", [])]
    functions = [HotFunction(p, name, n, c)
                 for p, name, n, c in payload.get("functions", [])]
    return Profile(lines=_annotate(lines, workspace), functions=functions)
