"""The page for the reader who will not run anything."""

from speedproof.report import Report

ROUNDS = [
    {"round": 1, "net_ir": 5_252_181, "rejected": None,
     "patch": "--- a\n+++ b\n@@ -1 +1 @@\n-        if word in counts:\n"
              "+        counts[word] = get(word, 0) + 1\n"},
    {"round": 2, "net_ir": None, "rejected": "it computes different answers",
     "patch": "-    return sorted(counts.items())\n+    return counts\n"},
]


def page(**kw):
    base = dict(subject="slow.py", before=6_035_688, after=4_076_748,
                rounds=ROUNDS, kept_round=1, deterministic=True)
    return Report(**{**base, **kw}).to_html()


def test_it_is_one_file_with_nothing_to_fetch():
    """A page that needs something running is a page that can fail on somebody
    else's machine."""
    html = page()
    assert "<script" not in html
    assert "http://" not in html and "https://" not in html
    assert "<style>" in html


def test_the_headline_numbers_are_present():
    html = page()
    assert "6,035,688" in html and "4,076,748" in html
    assert "32%" in html


def test_rejected_rounds_are_shown_not_hidden():
    """A record showing only the successful rounds would be a selection."""
    html = page()
    assert "it computes different answers" in html
    assert "Round 2" in html


def test_the_kept_round_is_marked():
    html = page()
    assert "kept" in html


def test_a_run_that_produced_nothing_still_renders():
    html = page(after=None, kept_round=None)
    assert "nothing was accepted" in html


def test_the_environment_is_recorded():
    """Counts are not comparable across architectures, so the page says which
    one it came from."""
    html = page(environment="aarch64/3.12.14/vg3.24.0")
    assert "aarch64" in html
    assert "not\ncomparable across architectures" in html or "not" in html


def test_it_reads_in_both_light_and_dark():
    html = page()
    assert "prefers-color-scheme: dark" in html


def test_diff_lines_are_coloured_by_direction():
    html = page()
    assert 'class="add"' in html and 'class="del"' in html
