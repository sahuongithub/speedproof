"""The isolation the agent's workspace has to provide.

Every test here corresponds to a way the agent could otherwise reach the tree
that judges it.
"""

from pathlib import Path

import pytest

from speedproof.speedagent.workspace import Workspace, WorkspaceError


@pytest.fixture
def origin(tmp_path):
    tree = tmp_path / "origin"
    (tree / "pkg").mkdir(parents=True)
    (tree / "pkg" / "module.py").write_text("original\n")
    (tree / "_sp_workload.py").write_text("def run(): return 1\n")
    return tree


def test_a_write_does_not_reach_the_original(origin, tmp_path):
    """A hard-linked file written in place changes every name it has, which
    would modify the corpus checkout silently and corrupt later measurements
    rather than fail them."""
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        ws.write("pkg/module.py", "changed\n")
        assert ws.read("pkg/module.py") == "changed\n"
        assert (origin / "pkg" / "module.py").read_text() == "original\n"


def test_the_clone_starts_identical(origin, tmp_path):
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        assert ws.read("pkg/module.py") == "original\n"


def test_the_workload_cannot_be_edited(origin, tmp_path):
    """It is the instrument, not the code under measurement."""
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        with pytest.raises(WorkspaceError, match="measurement"):
            ws.write("_sp_workload.py", "def run(): return 0\n")


def test_git_metadata_cannot_be_edited(origin, tmp_path):
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        with pytest.raises(WorkspaceError, match="measurement"):
            ws.write(".git/config", "x")


def test_a_write_cannot_escape_upwards(origin, tmp_path):
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        with pytest.raises(WorkspaceError, match="outside"):
            ws.write("../escaped.py", "x")


def test_a_failed_write_leaves_the_previous_contents(origin, tmp_path, monkeypatch):
    """A partial write would leave a file that parses differently and measures
    differently, which is worse than not writing at all."""
    import os

    with Workspace.clone(origin, tmp_path / "ws") as ws:
        def explode(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", explode)
        with pytest.raises(OSError):
            ws.write("pkg/module.py", "half")
        assert ws.read("pkg/module.py") == "original\n"


def test_what_was_written_is_recorded(origin, tmp_path):
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        ws.write("pkg/module.py", "a\n")
        ws.write("pkg/other.py", "b\n")
        assert ws.written == ("pkg/module.py", "pkg/other.py")


def test_the_change_is_recoverable_as_a_patch(origin, tmp_path):
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        ws.write("pkg/module.py", "changed\n")
        patch = ws.diff()
        assert "-original" in patch and "+changed" in patch


def test_nothing_written_means_no_patch(origin, tmp_path):
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        assert ws.diff() == ""


def test_the_workspace_is_removed_afterwards(origin, tmp_path):
    with Workspace.clone(origin, tmp_path / "ws") as ws:
        root = ws.root
        assert root.exists()
    assert not root.exists()


def test_cloning_something_that_is_not_there_is_refused(tmp_path):
    with pytest.raises(WorkspaceError, match="nothing to clone"):
        Workspace.clone(tmp_path / "absent")


def test_a_workspace_is_not_made_in_the_system_temporary_directory():
    """On macOS that resolves under /var/folders, which the container runtime
    does not mount, so the workspace exists on the host and is empty inside the
    container. Every measurement then fails identically and the failure looks
    like the agent's."""
    import tempfile

    from speedproof.speedagent.workspace import WORKSPACE_ROOT

    system_temp = Path(tempfile.gettempdir()).resolve()
    assert not str(WORKSPACE_ROOT.resolve()).startswith(str(system_temp))
    assert WORKSPACE_ROOT.is_relative_to(Path.home())


def test_the_default_workspace_is_reachable_by_a_container(tmp_path):
    """A path the measurement cannot mount is not a workspace, whatever else
    is true of it."""
    from speedproof.speedagent.workspace import WORKSPACE_ROOT, Workspace

    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "m.py").write_text("x = 1\n")
    ws = Workspace.clone(origin)
    try:
        assert ws.root.is_relative_to(WORKSPACE_ROOT.resolve())
    finally:
        ws.release()
