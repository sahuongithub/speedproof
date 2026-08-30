"""Run tasks from a manifest and report where each one got to."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from speedproof.corpus.runner import CorpusReport, run_task
from speedproof.corpus.task import load_tasks
from speedproof.verifyperf.callgrind import ensure_image, probe_environment

#: Dependencies a project needs in the measurement image, pinned by us. An
#: unpinned dependency would change instruction counts with no change to the
#: code under measurement.
PROJECT_DEPENDENCIES = {
    "xdslproject/xdsl": (
        "immutabledict<4.2.2",
        "typing-extensions>=4.7,<5",
        "ordered-set==4.1.0",
    ),
    # pandas is built from source in the image. Its build needs ninja and a
    # toolchain; its runtime needs dateutil and pytz. Pinning them is what
    # keeps an instruction count attributable to the code rather than to a
    # dependency that moved underneath it.
    "pandas-dev/pandas": (
        "meson-python>=0.19,<1",
        "meson>=1.2.3,<2",
        "ninja",
        "wheel",
        "Cython>3.1.0,<4",
        "numpy>=2.0",
        "versioneer[toml]",
        "python-dateutil",
        "pytz",
    ),
}

#: Projects that must be compiled before their benchmarks can run. The build
#: happens once per task: every mined patch touches only Python, so the base
#: and patched trees share the same compiled artefacts.
PROJECT_BUILD = {
    "pandas-dev/pandas": "pip install --no-build-isolation -e . >/dev/null 2>&1",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speedproof-corpus")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--task", action="append", help="run only these task ids")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--threshold", type=float, default=0.02)
    parser.add_argument("--out", type=Path, default=Path("eval/corpus-report.json"))
    parser.add_argument("--keep", action="store_true", help="leave worktrees in place")
    args = parser.parse_args(argv)

    tasks = load_tasks(args.manifest)
    if args.task:
        wanted = set(args.task)
        tasks = [t for t in tasks if t.task_id in wanted]
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 1

    repo = tasks[0].repo
    dependencies = PROJECT_DEPENDENCIES.get(repo, ())
    tag = f"speedproof/measure-{repo.split('/')[-1]}:0.1.0"
    image = ensure_image(dependencies=dependencies, tag=tag)

    cache = Path("corpus/repos").resolve()
    workspace = Path("corpus/work").resolve()
    clone = cache / repo.split("/")[-1]
    fingerprint = probe_environment(clone if clone.is_dir() else cache, image=image)
    print(f"{len(tasks)} task(s) from {repo}", file=sys.stderr)
    print(f"environment {fingerprint}\n", file=sys.stderr)

    report = CorpusReport()
    for index, task in enumerate(tasks, 1):
        result = run_task(
            task, cache, workspace,
            image=image, threshold=args.threshold,
            repetitions=args.repetitions, fingerprint=fingerprint,
            keep=args.keep,
        )
        report.results.append(result)
        print(f"[{index}/{len(tasks)}] {result.line()}", flush=True)

    print()
    print(report.summary())
    report.write(args.out)
    print(f"\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
