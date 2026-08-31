"""speedproof <command>"""

from __future__ import annotations

import sys

COMMANDS = {
    "optimise": "speedproof.optimise",
    "optimize": "speedproof.optimise",
    "demo": "speedproof.hackguard.__main__",
    "verify": "speedproof.verifyperf.cli",
    "site": "speedproof.site",
}

USAGE = """\
speedproof — make code faster, and prove it got faster

  speedproof optimise FILE     improve a Python file, showing every attempt
  speedproof optimise --example slow.py
                               write an example file to try it on
  speedproof demo              five attempted optimisations, three of them cheats
  speedproof verify            check the correctness gate, then measure
  speedproof site              rebuild the recorded-results pages in docs/site

A file to optimise needs one function, run(), which does the work and returns
its result. The result is what correctness is judged on.
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    command = argv.pop(0)
    module = COMMANDS.get(command)
    if module is None:
        print(f"speedproof: unknown command {command!r}\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    import importlib

    return importlib.import_module(module).main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
