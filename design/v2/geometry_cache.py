"""Prevent stale manufactured geometry from silently entering the preview."""
from __future__ import annotations
import hashlib
from pathlib import Path


def pelvis_source_hash() -> str:
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in ("profile.py", "pelvis_cad.py"):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()
