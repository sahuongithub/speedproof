"""A page a reader can open, for the reader who will not run anything.

There is an audience between the two this project already serves: someone who
will not type a command but will not read source either. They are most of the
people who will look at it. A terminal transcript does not serve them and
neither does a module docstring.

So the same data the tool already writes becomes one self-contained HTML file.
No server, no build step, nothing to install — it is a file, and opening it is
the whole interaction. That constraint is deliberate: a page that needs
something running is a page that can fail on somebody else's machine, and the
argument this project makes is about not asking anyone to take a number on
trust.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

STYLE = """
:root {
  --ink: #16181d; --dim: #6b7280; --line: #e5e7eb; --paper: #ffffff;
  --good: #15803d; --good-bg: #f0fdf4; --bad: #b91c1c; --bad-bg: #fef2f2;
  --accent: #1d4ed8; --rule: #f3f4f6;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ink: #e5e7eb; --dim: #9ca3af; --line: #374151; --paper: #111318;
    --good: #4ade80; --good-bg: #0d2818; --bad: #f87171; --bad-bg: #2a1315;
    --accent: #93c5fd; --rule: #1f2430;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 3rem 1.5rem 6rem; background: var(--paper); color: var(--ink);
  font: 16px/1.65 ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif;
}
main { max-width: 46rem; margin: 0 auto; }
h1 { font-size: 1.9rem; margin: 0 0 .3rem; letter-spacing: -.02em; }
h2 { font-size: 1.15rem; margin: 3rem 0 1rem; letter-spacing: -.01em; }
.lede { color: var(--dim); margin: 0 0 2.5rem; font-size: 1.05rem; }
.headline {
  display: flex; gap: 2.5rem; flex-wrap: wrap; padding: 1.5rem 0;
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
}
.figure .value { font-size: 2rem; font-weight: 600; letter-spacing: -.03em;
  font-variant-numeric: tabular-nums; }
.figure .label { color: var(--dim); font-size: .85rem; }
.figure.win .value { color: var(--good); }
.bar { display: flex; align-items: center; gap: .75rem; margin: .4rem 0; }
.bar .name { width: 9rem; font-size: .9rem; color: var(--dim); flex: none; }
.bar .track { flex: 1; height: 1.6rem; background: var(--rule); border-radius: 3px;
  overflow: hidden; }
.bar .fill { height: 100%; background: var(--accent); opacity: .85; }
.bar .fill.after { background: var(--good); }
.bar .n { width: 8rem; text-align: right; font-variant-numeric: tabular-nums;
  font-size: .9rem; flex: none; }
.round { border: 1px solid var(--line); border-radius: 8px; padding: 1rem 1.25rem;
  margin: .85rem 0; }
.round.kept { border-color: var(--good); background: var(--good-bg); }
.round.rejected { border-color: var(--bad); background: var(--bad-bg); }
.round .top { display: flex; justify-content: space-between; align-items: baseline;
  gap: 1rem; margin-bottom: .6rem; }
.round .who { font-weight: 600; }
.round .verdict { font-size: .85rem; font-weight: 600; }
.round.kept .verdict { color: var(--good); }
.round.rejected .verdict { color: var(--bad); }
pre { margin: .5rem 0 0; padding: .75rem .9rem; background: var(--rule);
  border-radius: 6px; overflow-x: auto; font-size: .82rem; line-height: 1.5;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
pre .add { color: var(--good); } pre .del { color: var(--bad); }
table { width: 100%; border-collapse: collapse; font-size: .92rem; margin: .5rem 0; }
th { text-align: left; font-weight: 600; font-size: .78rem; color: var(--dim);
  text-transform: uppercase; letter-spacing: .06em; padding: .5rem .6rem;
  border-bottom: 1px solid var(--line); }
td { padding: .6rem; border-bottom: 1px solid var(--rule);
  font-variant-numeric: tabular-nums; }
td.good { color: var(--good); font-weight: 600; }
td.bad { color: var(--bad); font-weight: 600; }
.note { color: var(--dim); font-size: .9rem; }
footer { margin-top: 4rem; padding-top: 1.5rem; border-top: 1px solid var(--line);
  color: var(--dim); font-size: .85rem; }
"""


def _n(value) -> str:
    return f"{value:,}" if isinstance(value, int) else "—"


def _diff(patch: str, limit: int = 12) -> str:
    """Render a patch, showing only the lines that changed."""
    out, shown = [], 0
    for line in (patch or "").splitlines():
        if line.startswith(("+++", "---", "diff ", "index ", "@@")):
            continue
        css = "add" if line.startswith("+") else "del" if line.startswith("-") else None
        if css is None:
            continue
        out.append(f'<span class="{css}">{html.escape(line)}</span>')
        shown += 1
        if shown >= limit:
            out.append('<span class="note">…</span>')
            break
    return "<pre>" + "\n".join(out) + "</pre>" if out else ""


@dataclass
class Report:
    """One optimisation run, as a page."""

    subject: str
    before: int
    after: int | None
    rounds: list[dict]
    kept_round: int | None
    deterministic: bool
    environment: str = ""

    @property
    def removed(self) -> float:
        if not self.after or not self.before:
            return 0.0
        return (self.before - self.after) / self.before

    def to_html(self) -> str:
        bars = ""
        if self.after:
            widest = max(self.before, self.after)
            for name, value, css in (("before", self.before, ""),
                                     ("after", self.after, " after")):
                width = value / widest * 100
                bars += (
                    f'<div class="bar"><div class="name">{name}</div>'
                    f'<div class="track"><div class="fill{css}" '
                    f'style="width:{width:.1f}%"></div></div>'
                    f'<div class="n">{_n(value)}</div></div>'
                )

        cards = ""
        for entry in self.rounds:
            number = entry.get("round")
            rejected = entry.get("rejected")
            net = entry.get("net_ir")
            kept = number == self.kept_round
            css = "kept" if kept else ("rejected" if rejected else "")
            if rejected:
                verdict = f"rejected — {html.escape(str(rejected))}"
            elif net:
                change = (self.before - net) / self.before if self.before else 0
                verdict = f"{_n(net)} instructions ({change:+.1%})"
                if kept:
                    verdict += " · kept"
            else:
                verdict = "no measurement"
            cards += (
                f'<div class="round {css}"><div class="top">'
                f'<span class="who">Round {number}</span>'
                f'<span class="verdict">{verdict}</span></div>'
                f'{_diff(entry.get("patch", ""))}</div>'
            )

        outcome = (
            f'<div class="figure win"><div class="value">{self.removed:.0%}</div>'
            f'<div class="label">of the work removed</div></div>'
            if self.after else
            '<div class="figure"><div class="value">—</div>'
            '<div class="label">nothing was accepted</div></div>'
        )

        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>speedproof — {html.escape(self.subject)}</title>
<style>{STYLE}</style></head><body><main>

<h1>{html.escape(self.subject)}</h1>
<p class="lede">An agent was asked to make this file do less work. Every attempt
was measured by counting the instructions it executed, in a container the agent
could not reach.</p>

<div class="headline">
  <div class="figure"><div class="value">{_n(self.before)}</div>
    <div class="label">instructions, before</div></div>
  <div class="figure"><div class="value">{_n(self.after)}</div>
    <div class="label">instructions, after</div></div>
  {outcome}
</div>

{f'<h2>The change</h2>{bars}' if bars else ''}

<h2>What the agent tried</h2>
<p class="note">Every round is here, including the ones that were refused. A
record that showed only the successful rounds would be a selection.</p>
{cards}

<h2>What was checked</h2>
<table>
<tr><th>check</th><th>result</th></tr>
<tr><td>the answers are unchanged</td><td class="good">verified by hashing the
result, outside the process being measured</td></tr>
<tr><td>the measurement repeats</td><td class="{'good' if self.deterministic else 'bad'}">
{'identical on every run' if self.deterministic else 'varied between runs'}</td></tr>
<tr><td>the work went away</td><td class="good">the cost of importing the module
is measured separately, so work moved there cannot hide</td></tr>
</table>

<footer>
Generated by speedproof. {html.escape(self.environment)}<br>
Instruction counts are exact and reproduce within one environment. They are not
comparable across architectures, which is why the environment is recorded.
</footer>
</main></body></html>
"""

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_html())
        return path
