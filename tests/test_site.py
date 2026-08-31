"""The recorded-results site."""

from pathlib import Path

import pytest

from speedproof.site import NAV, Site


@pytest.fixture
def built(tmp_path):
    pages = Site(Path.cwd()).build(tmp_path / "site")
    return {p.name: p.read_text() for p in pages}


def test_every_page_is_self_contained(built):
    """A page that needs something running is a page that can fail on someone
    else's machine."""
    for name, html in built.items():
        assert "<script" not in html, name
        assert "http://" not in html and "https://" not in html, name
        assert "<style>" in html, name


def test_every_page_says_nothing_here_runs(built):
    """A site that looks interactive and is not would be the exact failing this
    project criticises."""
    for name, html in built.items():
        assert "Nothing on this site runs" in html, name
        assert "uv run speedproof optimise" in html, name


def test_the_pages_link_to_each_other(built):
    for name, html in built.items():
        for href, _ in NAV:
            assert href in html, f"{name} does not link to {href}"


def test_the_result_page_shows_the_maintainer_as_the_target(built):
    assert "maintainer" in built["index.html"]


def test_the_failure_page_leads_with_what_did_not_work(built):
    """Most candidates do not survive, and the reasons are the finding."""
    corpus = built["corpus.html"]
    assert "What did not work" in corpus
    assert "no benchmark reaches the changed lines" in corpus


def test_the_cheats_page_names_its_sources(built):
    """None was invented to be caught."""
    assert "published benchmark" in built["cheats.html"]


def test_github_pages_is_told_not_to_process_it(tmp_path):
    Site(Path.cwd()).build(tmp_path / "site")
    assert (tmp_path / "site" / ".nojekyll").exists()
