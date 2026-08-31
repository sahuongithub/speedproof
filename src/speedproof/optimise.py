"""Point this at a Python file and watch it get faster, or watch it not.

Everything else in this project measures optimisations that already exist. This
is the part a person uses: hand it a file, and an agent tries to speed it up
while the harness checks every attempt.

It prints as it goes rather than at the end, because the interesting part is
not the final number. It is watching an attempt get rejected for computing the
wrong answer, and the next attempt work.

The file needs one thing: a function called ``run()`` that does the work and
returns its result. The result is what correctness is judged on, so it has to
be returned rather than printed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[36m"

EXAMPLE = '''\
"""A slow way to count how often each word appears."""

WORDS = ["apple", "banana", "cherry"] * 2000


def run():
    counts = {}
    for word in WORDS:
        if word in counts:
            counts[word] = counts[word] + 1
        else:
            counts[word] = 1
    return sorted(counts.items())
'''


@dataclass
class Console:
    """Printing that stays readable when it is not a terminal."""

    colour: bool = True

    def paint(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.colour else text

    def say(self, text: str = "") -> None:
        print(text, flush=True)

    def heading(self, text: str) -> None:
        self.say()
        self.say(self.paint(text, BOLD))

    def note(self, text: str) -> None:
        self.say(self.paint(f"  {text}", DIM))

    def good(self, text: str) -> None:
        self.say(self.paint(f"  {text}", GREEN))

    def bad(self, text: str) -> None:
        self.say(self.paint(f"  {text}", RED))

    def number(self, label: str, value: str) -> None:
        self.say(f"  {label:<26} {self.paint(value, BOLD)}")

    def diff(self, patch: str, limit: int = 14) -> None:
        """Show what changed, and only what changed."""
        shown = 0
        for line in patch.splitlines():
            if line.startswith(("+++", "---", "diff ", "index ", "@@")):
                continue
            if line.startswith("+"):
                self.say("    " + self.paint(line, GREEN))
                shown += 1
            elif line.startswith("-"):
                self.say("    " + self.paint(line, RED))
                shown += 1
            if shown >= limit:
                self.say(self.paint("    …", DIM))
                return


def _install(target: Path, workspace_dir: Path) -> tuple[Path, Path]:
    """Put the file and its paired baseline where they can be measured.

    The baseline is the same file with ``run()`` emptied. Subtracting it removes
    everything the module does when it loads, so the measurement is of the work
    rather than of the import -- and it also means work moved into the import
    cannot hide, because the import cost is measured separately.
    """
    source = target.read_text()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "subject.py").write_text(source)

    # The baseline keeps everything except the body of run().
    lines = source.splitlines()
    out, skipping = [], False
    for line in lines:
        if line.startswith("def run("):
            out.append(line)
            out.append("    return None")
            skipping = True
            continue
        if skipping:
            if line and not line[0].isspace():
                skipping = False
            else:
                continue
        out.append(line)
    (workspace_dir / "subject_baseline.py").write_text("\n".join(out) + "\n")
    return Path("subject.py"), Path("subject_baseline.py")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="speedproof optimise",
        description="Make a Python file faster, and prove it got faster.",
    )
    parser.add_argument("file", nargs="?", type=Path,
                        help="a Python file defining run()")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--example", action="store_true",
                        help="write an example file to start from")
    parser.add_argument("--no-colour", action="store_true")
    parser.add_argument("--output", type=Path,
                        help="where to write the improved file")
    args = parser.parse_args(argv)

    console = Console(colour=sys.stdout.isatty() and not args.no_colour)

    if args.example:
        destination = args.file or Path("slow.py")
        destination.write_text(EXAMPLE)
        console.say(f"wrote {destination}")
        console.note(f"now run: speedproof optimise {destination}")
        return 0

    if args.file is None:
        parser.print_help()
        return 2
    if not args.file.is_file():
        console.bad(f"no such file: {args.file}")
        return 2
    if "def run(" not in args.file.read_text():
        console.bad(f"{args.file} defines no run() function")
        console.note("the file needs a run() that does the work and returns "
                     "its result, since the result is what correctness is "
                     "judged on")
        return 2

    return _optimise(args, console)


def _optimise(args, console: Console) -> int:
    from speedproof.speedagent.controller import ModelUnavailable, ask
    from speedproof.speedagent.loop import (
        EditError,
        Round,
        Trajectory,
        apply_edits,
        build_prompt,
        parse_edits,
        patch_fingerprint,
    )
    from speedproof.speedagent.profile import collect as collect_profile
    from speedproof.speedagent.workspace import Workspace, WorkspaceError
    from speedproof.verifyperf.callgrind import (
        MeasurementError,
        measure,
        probe_environment,
    )
    from speedproof.verifyperf.verify import _capture

    staging = Path.home() / ".speedproof" / "subject"
    shutil.rmtree(staging, ignore_errors=True)
    workload, baseline = _install(args.file, staging)

    console.heading(f"Measuring {args.file}")
    console.note("in a container, counting every instruction it executes")
    try:
        fingerprint = probe_environment(staging)
        start = measure(staging, workload, repetitions=args.repetitions,
                        fingerprint=fingerprint, baseline=baseline)
        reference = _capture(staging, workload, "checksum")
    except MeasurementError as exc:
        console.bad("could not measure it")
        console.note(str(exc).splitlines()[0][:120])
        return 1

    if start.net <= 0:
        console.bad("this file does almost no work; there is nothing to measure")
        return 1

    console.number("instructions", f"{start.net:,}")
    console.number("reproducible",
                   "yes, identical every run" if start.deterministic
                   else f"varies by {start.spread:,}")

    profile = collect_profile(staging, workload)
    if not profile.empty:
        console.heading("Where the work goes")
        for hot in profile.lines[:5]:
            console.say(f"  {hot.count:>9,} x  {hot.text.strip()[:60]}")

    console.heading(f"Asking an agent to improve it, up to {args.rounds} times")
    console.note("it proposes changes; it never measures one")

    trajectory = Trajectory(task=args.file.name, baseline_ir=start.net)
    seen: set[str] = set()
    original = args.file.read_text()
    #: The improved source of each round that was accepted, by round number.
    #: Kept here rather than re-derived from the reply, because re-applying an
    #: edit assumes it still applies and the point of this dictionary is that
    #: the answer is already known.
    accepted_source: dict[int, str] = {}

    with Workspace.clone(staging) as workspace:
        for number in range(1, args.rounds + 1):
            console.say()
            console.say(console.paint(f"  Round {number}", BOLD))
            prompt = build_prompt(
                source=workspace.read(workload), path=str(args.file.name),
                profile=profile, trajectory=trajectory,
            )
            try:
                reply = ask(prompt)
            except ModelUnavailable as exc:
                console.bad(f"  the model was unavailable: {exc}")
                break

            edits = parse_edits(reply)
            entry = Round(number)
            try:
                apply_edits(workspace, workload, edits)
            except (EditError, WorkspaceError) as exc:
                entry.rejected = str(exc).splitlines()[0][:80]
                console.bad(f"  rejected — {entry.rejected}")
                trajectory.rounds.append(entry)
                workspace.write(workload, original)
                continue

            patch = workspace.diff()
            console.diff(patch)

            if patch_fingerprint(patch) in seen:
                entry.rejected = "the same change as before"
                console.note("  rejected — the same change as before")
                trajectory.rounds.append(entry)
                workspace.write(workload, original)
                continue
            seen.add(patch_fingerprint(patch))

            try:
                digest = _capture(workspace.root, workload, "checksum")
                if digest != reference:
                    entry.rejected = "it computes different answers"
                    console.bad("  REJECTED — it computes different answers")
                    trajectory.rounds.append(entry)
                    workspace.write(workload, original)
                    continue
                result = measure(workspace.root, workload,
                                 repetitions=args.repetitions,
                                 fingerprint=fingerprint, baseline=baseline)
            except MeasurementError as exc:
                entry.rejected = f"it did not run: {str(exc).splitlines()[0][:60]}"
                console.bad(f"  REJECTED — {entry.rejected}")
                trajectory.rounds.append(entry)
                workspace.write(workload, original)
                continue

            moved = (
                start.import_cost is not None
                and result.import_cost is not None
                and (result.import_cost - start.import_cost)
                > (start.net - result.net) * 0.5
                and result.net < start.net
            )
            if moved:
                entry.rejected = "the work moved into module import"
                console.bad("  REJECTED — the work moved into module import "
                            "rather than going away")
                trajectory.rounds.append(entry)
                workspace.write(workload, original)
                continue

            entry.net_ir = result.net
            entry.patch = patch
            accepted_source[number] = workspace.read(workload)
            change = (start.net - result.net) / start.net
            best = trajectory.best
            trajectory.rounds.append(entry)
            if change > 0:
                console.good(f"  {result.net:,} instructions  ({change:+.1%})"
                             + ("  ← best so far"
                                if best is None or result.net < best.net_ir else ""))
            else:
                console.note(f"  {result.net:,} instructions  ({change:+.1%})")
            workspace.write(workload, original)

        best = trajectory.best
        console.heading("Result")
        if best is None:
            console.bad("nothing was accepted")
            console.note("every attempt either changed the answers or did not "
                         "run. The file is unchanged.")
            return 1

        change = (start.net - best.net_ir) / start.net
        console.number("before", f"{start.net:,} instructions")
        console.number("after", f"{best.net_ir:,} instructions")
        console.number("work removed", f"{change:.1%}")
        console.number("answers", "identical, checked by hashing the result")
        console.number("kept", f"round {best.number} of {len(trajectory.rounds)}")

        destination = args.output or args.file.with_suffix(".optimised.py")
        destination.write_text(accepted_source[best.number])
        console.say()
        console.good(f"wrote {destination}")
        console.note(f"diff it against the original: diff {args.file} {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
