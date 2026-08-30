"""Compiling a project before its benchmarks can run.

Most projects need nothing: their code is Python and importing it is enough.
A project shipping compiled extensions needs those built, and building them is
the most expensive step in the pipeline -- around four minutes for pandas.

It happens **once per task, not once per tree**. Every mined patch for such a
project touches only Python files, so the base and patched trees differ in
nothing that affects compilation and can share one set of artefacts. Building
twice would double the cost of the corpus for no information.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from speedproof.verifyperf.callgrind import MeasurementError, _docker, image_tag
from speedproof.verifyperf.session import install_cleanup, label_args

#: How to build each project that needs it, and what to check afterwards. The
#: check matters: an editable install arranges import hooks without compiling
#: anything and still exits zero, which is how a pandas build once appeared to
#: take twenty-seven seconds.
BUILD_RECIPES: dict[str, tuple[str, str]] = {
    "pandas-dev/pandas": (
        "pip install --no-build-isolation -e . 2>&1 | tail -2",
        "import pandas, pandas._libs.hashtable",
    ),
}

#: Files a build leaves behind that the other tree needs.
_ARTEFACT_SUFFIXES = (".so", ".pyd", ".dylib")


def needs_build(repo: str) -> bool:
    return repo in BUILD_RECIPES


def build(
    repo: str,
    tree: Path,
    image: str | None = None,
    platform: str | None = None,
    timeout: int = 1800,
) -> None:
    """Compile ``tree`` in place, and prove the artefacts actually work."""
    recipe = BUILD_RECIPES.get(repo)
    if recipe is None:
        return
    command, check = recipe
    install_cleanup()

    script = f"""
set -e
cd /work
{command}
python3 -c "{check}" || {{ echo "BUILD_PRODUCED_NOTHING" >&2; exit 9; }}
echo BUILD_OK
"""
    proc = subprocess.run(
        [_docker(), "run", "--rm", "-i"]
        + label_args()
        + (["--platform", platform] if platform else [])
        + [
            "-v", f"{Path(tree).resolve()}:/work",   # writable: the build lands here
            "-e", "PYTHONHASHSEED=0",
            image or image_tag(platform), "bash", "-s",
        ],
        input=script.encode(),
        capture_output=True,
        timeout=timeout,
    )
    if b"BUILD_OK" not in proc.stdout:
        detail = proc.stderr.decode(errors="replace")[-800:]
        if b"BUILD_PRODUCED_NOTHING" in proc.stderr:
            detail = (
                "the build exited successfully but the compiled extension "
                "could not be imported"
            )
        raise MeasurementError(f"could not build {repo}:\n{detail}")


def share_artefacts(source: Path, target: Path) -> int:
    """Copy compiled artefacts from one tree to the other.

    Sound only because the patch touches no compiled source, which is a
    condition the miner enforces rather than one assumed here.
    """
    copied = 0
    source, target = Path(source), Path(target)
    for path in source.rglob("*"):
        if path.suffix not in _ARTEFACT_SUFFIXES or not path.is_file():
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied
