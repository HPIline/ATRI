"""CI 是 Python 3.14，没有 CadQuery。本机 CAD 测试走仓库根 .venv-cad（3.12）。

unittest 在 import 阶段抛 ImportError 会记成 ERROR 而不是 skip。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
for _p in (_REPO, _REPO / "design"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

try:
    import cadquery as cq  # noqa: F401
    HAS_CADQUERY = True
    CADQUERY_SKIP_REASON = ""
except ImportError:
    cq = None
    HAS_CADQUERY = False
    CADQUERY_SKIP_REASON = "需要 CadQuery：仓库根目录 .venv-cad（Python 3.12）"

skip_without_cadquery = unittest.skipUnless(HAS_CADQUERY, CADQUERY_SKIP_REASON)
