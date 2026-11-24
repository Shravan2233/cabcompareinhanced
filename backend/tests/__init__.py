"""Test package initialization supporting both repo-root and parent-workspace execution."""
from __future__ import annotations

import sys
import types
from pathlib import Path

try:
    import cabcompare.backend  # noqa: F401
except ModuleNotFoundError:
    _repo_root = Path(__file__).resolve().parents[2]
    _pkg = types.ModuleType("cabcompare")
    _pkg.__path__ = [str(_repo_root)]
    sys.modules["cabcompare"] = _pkg
