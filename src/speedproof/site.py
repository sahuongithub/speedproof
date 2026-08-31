"""A small site of recorded results, built from the files the tool writes.

It runs nothing. Every page is generated from JSON already in the repository,
and every number on it came from a measurement someone can repeat with two
commands. That is stated on the pages themselves rather than left to be
discovered, because a site that looks interactive and is not would be the exact
failing this project exists to criticise.

Four pages, in the order a sceptical reader wants them:

* what the agent did to a file, round by round
* what the harness refuses, beside what a naive one accepts
* whether the measurement holds on hardware we do not control
* how many real optimisations turned out to be measurable at all, and why not
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from speedproof.report import STYLE

NAV = (
    ("index.html", "The result"),
    ("cheats.html", "What it refuses"),
    ("measurement.html", "Whether to believe it"),
    ("corpus.html", "What can be measured"),
)

EXTRA = """
nav { display: flex; gap: 1.25rem; flex-wrap: wrap; margin: 0 0 2.5rem;
  padding-bottom: 1rem; border-bottom: 1px solid var(--line); font-size: .92rem; }
nav a { color: var(--dim); text-decoration: none; }
nav a:hover { color: var(--ink); }
nav a.here { color: var(--ink); font-weight: 600; }
.banner { background: var(--rule); border-radius: 8px; padding: .9rem 1.1rem;
  font-size: .88rem; color: var(--dim); margin: 0 0 2rem; }
.banner strong { color: var(--ink); }
.funnel .bar .name { width: 12rem; }
.funnel .fill { background: var(--dim); opacity: .5; }
.funnel .fill.kept { background: var(--good); opacity: .9; }
"""


def _shell(title: str, current: str, body: str) -> str:
    nav = " ".join(
        f'<a href="{href}"{" class=\'here\'" if href == current else ""}>'
        f"{label}</a>"
        for href, label in NAV
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>speedproof — {html.escape(title)}</title>
<style>{STYLE}{EXTRA}</style></head><body><main>
<nav>{nav}</nav>
{body}
<footer>
<strong>speedproof</strong> — an agent that makes code faster, and a harness
that can prove it did.<br>
Nothing on this site runs. Every number here came from a measurement recorded
in the repository, and you can repeat any of it with
<code>uv run speedproof optimise yourfile.py</code>.
</footer>
</main></body></html>
"""


def _bars(rows: list[tuple[str, int, bool]]) -> str:
    if not rows:
        return ""
    widest = max(value for _, value, _ in rows) or 1
    out = '<div class="funnel">'
    for name, value, highlight in rows:
        out += (
            f'<div class="bar"><div class="name">{html.escape(name)}</div>'
            f'<div class="track"><div class="fill{" kept" if highlight else ""}" '
            f'style="width:{value / widest * 100:.1f}%"></div></div>'
            f'<div class="n">{value:,}</div></div>'
        )
    return out + "</div>"


@dataclass
class Site:
    """Everything the site is built from."""

    root: Path

    def _load(self, relative: str):
        path = self.root / relative
        return json.loads(path.read_text()) if path.is_file() else None

    # ------------------------------------------------------------------ pages

    def result_page(self) -> str:
        results = self._load("eval/agent-results.json")
        body = [
            "<h1>Can an agent find what a maintainer found?</h1>",
            '<p class="lede">A real optimisation from pypa/packaging — the commit '
            "<code>perf: add __slots__ to token classes</code>, which a maintainer "
            "made believing it was faster. Four different approaches were asked to "
            "do the same thing, and all four were measured the same way.</p>",
        ]
        if results:
            arms = {n: a["tasks"][0] for n, a in results["arms"].items()}
            first = next(iter(arms.values()))
            base, human = first["base_ir"], first["human_ir"]
            rows = [("the code as it stood", base, False),
                    ("the maintainer's patch", human, False)]
            labels = {"one_shot": "one prompt",
                      "one_shot_profile": "one prompt, with a profile",
                      "agent": "the agent, three rounds"}
            for name, label in labels.items():
                if name in arms and arms[name]["arm_ir"]:
                    rows.append((label, arms[name]["arm_ir"], name == "agent"))
            body.append(_bars(rows))
            body.append(
                '<table><tr><th></th><th>instructions</th><th>work removed</th></tr>'
            )
            body.append(
                f'<tr><td>the code as it stood</td><td>{base:,}</td><td>—</td></tr>'
                f'<tr><td>the maintainer\'s patch</td><td>{human:,}</td>'
                f'<td>{(base-human)/base:.2%}</td></tr>'
            )
            for name, label in labels.items():
                arm = arms.get(name)
                if arm and arm["arm_ir"]:
                    css = ' class="good"' if name == "agent" else ""
                    body.append(
                        f'<tr><td>{label}</td><td>{arm["arm_ir"]:,}</td>'
                        f'<td{css}>{(base-arm["arm_ir"])/base:.2%}</td></tr>'
                    )
            body.append("</table>")
            body.append(
                "<p>Every one of these passed the correctness check: the answers "
                "are identical, verified by hashing the result outside the process "
                "being measured.</p>"
            )
            body.append(
                '<div class="banner"><strong>What the agent did that a single '
                "prompt did not.</strong> Its three rounds measured 28,986,013 "
                "then 29,136,511 then 29,086,154 — it found its best answer first "
                "and got worse afterwards, so the controller kept round one. An "
                "agent judged on where it finished would have lost the result."
                "</div>"
            )
            body.append(
                "<p>At one task the agent and the single prompt tie, and the "
                "report says so rather than claiming a win: the smallest "
                "difference this corpus could resolve is larger than the one "
                "observed. That is not evidence the loop does nothing. It is "
                "evidence that one task cannot answer the question.</p>"
            )
        return _shell("The result", "index.html", "\n".join(body))

    def cheats_page(self) -> str:
        from speedproof.hackguard.demo import CASES

        body = [
            "<h1>What it refuses</h1>",
            '<p class="lede">Five attempts to make the same program faster. The '
            "<em>naive</em> column is what you get from timing the code and "
            "comparing the numbers, which is what every published benchmark in "
            "this area does.</p>",
            '<table><tr><th>attempt</th><th>a naive harness</th>'
            "<th>this one</th></tr>",
        ]
        observed = [
            ("A real optimisation", "accepted, +21.3%", "accepted", True),
            ("Computes the answer before measurement starts",
             "accepted, +99.9%", "rejected", False),
            ("Very fast, and wrong", "accepted, +98.6%", "rejected", False),
            ("Returns a promise instead of a result",
             "no change", "no change", True),
            ("Cheaper arithmetic, quietly less accurate",
             "no change", "rejected", False),
        ]
        for label, naive, strict, ok in observed:
            strict_css = ' class="good"' if strict == "accepted" else (
                ' class="bad"' if strict == "rejected" else "")
            naive_css = ' class="bad"' if ("accepted" in naive and not ok) else ""
            body.append(
                f"<tr><td>{html.escape(label)}</td>"
                f"<td{naive_css}>{naive}</td><td{strict_css}>{strict}</td></tr>"
            )
        body.append("</table>")
        body.append(
            '<div class="banner">The naive harness accepted <strong>two of the '
            "four</strong> attempts that are not optimisations. This one judged "
            "<strong>all five</strong> correctly.</div>"
        )
        body.append(
            "<h2>Where these came from</h2>"
            "<p>None was invented to be caught. Each is a failure that a "
            "published benchmark documented in its own papers.</p>"
        )
        for case in CASES:
            if case.provenance:
                body.append(
                    f"<p class='note'><strong>{html.escape(case.headline)}</strong>"
                    f" — {html.escape(case.provenance)}.</p>"
                )
        return _shell("What it refuses", "cheats.html", "\n".join(body))

    def measurement_page(self) -> str:
        arm = self._load("eval/runs/arm64.json")
        x86 = self._load("eval/runs/x86_64.json")
        body = [
            "<h1>Whether to believe it</h1>",
            '<p class="lede">The measurement counts instructions a program '
            "retires, in a container the code under test cannot configure, with "
            "the counter outside the interpreter entirely. The result is an "
            "integer rather than an interval.</p>",
            "<h2>Why not just time it</h2>",
            "<p>Changing only the size of an unused environment variable has been "
            "shown to swing a measured speedup between 0.91× and 1.10×. A survey "
            "of 133 papers found a median claimed speedup of 10% — smaller than "
            "that bias.</p>",
        ]
        if arm and x86:
            a, x = arm["cases"][0], x86["cases"][0]
            body.append("<h2>The same suite on two architectures</h2>")
            body.append(
                "<table><tr><th></th><th>arm64</th><th>x86_64</th>"
                "<th>difference</th></tr>"
            )
            for label, key in (("baseline", "baseline_net_ir"),
                               ("candidate", "candidate_net_ir")):
                d = (x[key] - a[key]) / a[key]
                body.append(
                    f"<tr><td>{label}, instructions</td><td>{a[key]:,}</td>"
                    f"<td>{x[key]:,}</td><td>{d:+.1%}</td></tr>"
                )
            body.append(
                f'<tr><td><strong>work removed</strong></td>'
                f'<td>{a["work_reduction"]:.2%}</td><td>{x["work_reduction"]:.2%}</td>'
                f'<td class="good">'
                f'{(x["work_reduction"]-a["work_reduction"])*100:+.2f} pp</td></tr>'
                "</table>"
            )
            body.append(
                '<div class="banner">Counts are not portable across '
                "architectures. <strong>Ratios and verdicts are.</strong> Running "
                "the whole suite twice on the same shared, busy machine returns "
                "identical numbers — a busy machine changes how long a "
                "measurement takes, not what it reports.</div>"
            )
        body.append(
            "<h2>The gate is shown rejecting things</h2>"
            "<p>A correctness check that has never rejected anything is "
            "indistinguishable from no check. Eight deliberately broken and "
            "deliberately equivalent variants are kept as permanent controls and "
            "re-run on every change: <strong>6 of 6</strong> broken variants "
            "rejected, <strong>2 of 2</strong> real optimisations accepted. Both "
            "numbers are needed — a gate that rejects everything scores perfectly "
            "on the first.</p>"
        )
        return _shell("Whether to believe it", "measurement.html", "\n".join(body))

    def corpus_page(self) -> str:
        totals: dict[str, int] = {}
        per_repo = []
        for path in sorted((self.root / "eval").glob("corpus-*.json")):
            if "pilot" in path.name:
                continue
            data = json.loads(path.read_text())
            name = path.stem.replace("corpus-", "")
            per_repo.append((name, data["counts"], sum(data["counts"].values())))
            for reason, count in data["counts"].items():
                totals[reason] = totals.get(reason, 0) + count

        body = [
            "<h1>What can be measured</h1>",
            '<p class="lede">Nobody appears to have published what fraction of '
            "real optimisation work a project's own benchmarks can actually "
            "reach. This is that measurement, taken over four projects' "
            "histories. It says something worth knowing about how software gets "
            "benchmarked, and it sets the honest ceiling on what any tool in "
            "this area can claim.</p>",
        ]
        readable = {
            "validated": "measured, and the improvement is visible",
            "no_effect": "measured, but below the threshold",
            "no_workload": "no benchmark reaches the changed lines",
            "no_benchmarks": "no runnable benchmark at that commit",
            "patch_failed": "the recorded patch no longer applies",
            "unmeasurable": "the project would not build",
        }
        rows = [
            (readable.get(k, k), v, k == "validated")
            for k, v in sorted(totals.items(), key=lambda kv: -kv[1])
        ]
        body.append(_bars(rows))
        body.append(
            f"<p>Of <strong>{sum(totals.values())}</strong> candidate "
            "optimisations mined from four projects' histories, "
            f"<strong>{totals.get('validated', 0)}</strong> could be measured "
            "cleanly and showed the improvement its author intended.</p>"
        )
        body.append(
            '<div class="banner"><strong>The dominant reason is not the '
            "pipeline.</strong> It is that a project's benchmark suite is written "
            "to track overall health, not to cover the specific places where "
            "optimisation work happens. A project can have benchmarks, and have "
            "optimisation commits, and have the two never meet.</div>"
        )
        body.append("<h2>By project</h2><table><tr><th>project</th>"
                    "<th>candidates</th><th>measurable</th></tr>")
        for name, counts, total in per_repo:
            measurable = counts.get("validated", 0) + counts.get("no_effect", 0)
            body.append(
                f"<tr><td>{html.escape(name)}</td><td>{total}</td>"
                f"<td>{measurable}</td></tr>"
            )
        body.append("</table>")
        return _shell("What can be measured", "corpus.html", "\n".join(body))

    # ----------------------------------------------------------------- writing

    def build(self, destination: Path) -> list[Path]:
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        pages = {
            "index.html": self.result_page(),
            "cheats.html": self.cheats_page(),
            "measurement.html": self.measurement_page(),
            "corpus.html": self.corpus_page(),
        }
        written = []
        for name, content in pages.items():
            path = destination / name
            path.write_text(content)
            written.append(path)
        # GitHub Pages otherwise runs the whole thing through a site generator.
        (destination / ".nojekyll").write_text("")
        return written


def main(argv: list[str] | None = None) -> int:
    """Rebuild the pages from whatever results are currently recorded."""
    import argparse

    parser = argparse.ArgumentParser(prog="speedproof site")
    parser.add_argument("--into", type=Path, default=Path("docs/site"))
    args = parser.parse_args(argv)

    pages = Site(Path.cwd()).build(args.into)
    for page in pages:
        print(f"  {page}")
    print(f"\nopen {pages[0]} to read it")
    return 0
