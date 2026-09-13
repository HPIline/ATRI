"""兼容 ``discover -s tests``：同目录也能 ``from _optional_cadquery import ...``。"""
from atri.optional_cadquery import (  # noqa: F401
    CADQUERY_SKIP_REASON,
    HAS_CADQUERY,
    cq,
    skip_without_cadquery,
)
