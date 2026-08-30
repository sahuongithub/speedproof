"""Python side of the region counter."""

from __future__ import annotations

import ctypes
import os
from contextlib import contextmanager

DEFAULT_LIBRARY = "/opt/speedproof/libvgcount.so"

_ENTRY_POINTS = ("vgcount_zero", "vgcount_start", "vgcount_stop", "vgcount_dump")


class _Shim:
    """Thin binding to the client-request shim, absent when not counting."""

    def __init__(self, path: str | None = None) -> None:
        path = path or os.environ.get("SPEEDPROOF_VGCOUNT_LIB", DEFAULT_LIBRARY)
        try:
            self.lib = ctypes.CDLL(path)
        except OSError:
            # Running outside the measurement image is normal: the workload
            # should still execute, just without being counted.
            self.lib = None
            return
        for name in _ENTRY_POINTS:
            fn = getattr(self.lib, name)
            fn.restype = None
            fn.argtypes = []
        self.lib.vgcount_active.restype = ctypes.c_int

    @property
    def active(self) -> bool:
        return self.lib is not None and bool(self.lib.vgcount_active())


_SHIM = _Shim()


def is_counting() -> bool:
    """True when this process is running under Callgrind with the shim loaded."""
    return _SHIM.active


@contextmanager
def counted():
    """Count instructions retired inside this block, and nothing else.

    A no-op when the process is not being measured, so the same workload file
    runs unchanged during development.
    """
    if _SHIM.lib is None:
        yield
        return
    _SHIM.lib.vgcount_zero()
    _SHIM.lib.vgcount_start()
    try:
        yield
    finally:
        _SHIM.lib.vgcount_stop()
        _SHIM.lib.vgcount_dump()
