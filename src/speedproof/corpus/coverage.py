"""Recording which lines each workload executes.

The selector needs to know what a workload touches before it can decide whether
a patch is worth measuring against it. That map is produced here, by running
each workload under coverage measurement inside the same container the
measurement uses.

Two design notes, both from what the reference implementations get wrong.

Coverage is collected **per workload, in its own process**. Running several in
one process is cheaper and lets them contaminate each other: a module imported
by the first workload is already imported for the second, so the second appears
not to touch it. Since the whole point is deciding what a workload reaches, an
attribution that depends on run order is worse than useless.

Coverage is collected **on the base tree only**. The patched tree may not
contain the lines the patch removed, and the selector reasons about the
post-image line numbers of the diff. Mixing the two silently misaligns them.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from speedproof.corpus.workload import Benchmark
from speedproof.verifyperf.callgrind import (
    MeasurementError,
    _docker,
    ensure_image,
    image_tag,
)
from speedproof.verifyperf.session import install_cleanup, label_args

#: Directories whose coverage says nothing about what a patch touches.
_IGNORED_PREFIXES = ("/usr/", "/tmp/harness/", "<")

_COLLECTOR = '''
import json, sys, coverage

sys.path.insert(0, "/work")

target, out = sys.argv[1], sys.argv[2]
module, cls, method = target.rsplit(".", 2)

# Import and construct BEFORE measurement starts. Everything a module does
# when it is imported is common to every workload in that suite, so counting
# it makes all of them look alike: measured the other way round, four xdsl
# benchmarks shared 6,652 of their ~6,700 covered lines and differed by as
# few as four. What the selector needs is what a workload reaches that others
# do not, which is the call and nothing else.
#
# A patch to code that only runs at import is therefore invisible here, and
# deliberately so -- the selector escalates those to the whole suite by a
# separate rule rather than trying to see them in coverage.
mod = __import__(module, fromlist=[cls])
bench = getattr(mod, cls)()
if hasattr(bench, "setup"):
    bench.setup()

# branch=False: the selector asks which lines ran, not which arcs, and arc
# collection costs more for information nothing downstream uses.
cov = coverage.Coverage(config_file=False, branch=False, data_file=None)
cov.start()
try:
    getattr(bench, method)()
finally:
    cov.stop()

data = cov.get_data()
lines = {}
for path in data.measured_files():
    executed = data.lines(path)
    if executed:
        lines[path] = sorted(executed)
json.dump(lines, open(out, "w"))
'''


def _relative(path: str, root: str = "/work/") -> str | None:
    """Turn a container path into one comparable with a diff's file names."""
    if path.startswith(_IGNORED_PREFIXES):
        return None
    if path.startswith(root):
        return path[len(root):]
    return None


def collect(
    tree: Path,
    benchmarks: list[Benchmark],
    image: str | None = None,
    platform: str | None = None,
    timeout: int = 600,
) -> dict[str, dict[str, set[int]]]:
    """Map each benchmark to the lines it executes, keyed by repository path.

    A benchmark that fails to run is omitted rather than recorded as touching
    nothing. The distinction matters: an empty coverage map would tell the
    selector that this workload reaches no part of any patch, which is a claim,
    whereas absence tells it nothing was learned.
    """
    if image is None:
        ensure_image(platform=platform)
    install_cleanup()

    names = " ".join(b.name for b in benchmarks)
    script = f"""
set -e
pip install --quiet --no-cache-dir coverage 2>/dev/null || true
mkdir -p /tmp/cov
cat > /tmp/collect.py <<'COLLECT_EOF'
{_COLLECTOR}
COLLECT_EOF
cd /tmp
for target in {names}; do
  if python3 /tmp/collect.py "$target" "/tmp/cov/$target.json" 2>/dev/null; then
    echo "OK $target"
  else
    echo "FAILED $target"
  fi
done
echo "---COVERAGE---"
python3 - <<'DUMP_EOF'
import json, pathlib
out = {{}}
for p in pathlib.Path("/tmp/cov").glob("*.json"):
    try:
        out[p.stem] = json.loads(p.read_text())
    except Exception:
        pass
print(json.dumps(out))
DUMP_EOF
"""
    proc = subprocess.run(
        [_docker(), "run", "--rm", "-i"]
        + label_args()
        + (["--platform", platform] if platform else [])
        + [
            "-v", f"{tree}:/work:ro",
            "-e", "PYTHONHASHSEED=0",
            "-e", "PYTHON_JIT=0",
            image or image_tag(platform), "bash", "-s",
        ],
        input=script.encode(),
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise MeasurementError(
            "coverage collection failed:\n"
            + proc.stderr.decode(errors="replace")[-1500:]
        )

    text = proc.stdout.decode()
    if "---COVERAGE---" not in text:
        raise MeasurementError("coverage collection produced no data")
    payload = json.loads(text.split("---COVERAGE---", 1)[1].strip())

    coverage_map: dict[str, dict[str, set[int]]] = {}
    for workload, files in payload.items():
        per_file: dict[str, set[int]] = {}
        for path, lines in files.items():
            relative = _relative(path)
            if relative:
                per_file[relative] = set(lines)
        if per_file:
            coverage_map[workload] = per_file
    return coverage_map


def summarise(coverage_map: dict[str, dict[str, set[int]]]) -> str:
    if not coverage_map:
        return "no workload produced coverage"
    lines = []
    for workload, files in sorted(coverage_map.items()):
        total = sum(len(v) for v in files.values())
        lines.append(f"  {workload:52s} {len(files):>3} files  {total:>6} lines")
    return "\n".join(lines)
