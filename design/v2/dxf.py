"""最小 DXF R12 写出（激光店可开）。不含第三方库。"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from .plates import Hole, Plate, Point, bbox


def _f(v: float) -> str:
    return f"{v:.4f}"


def _line(x1: float, y1: float, x2: float, y2: float, layer: str = "0") -> str:
    return (
        f"0\nLINE\n8\n{layer}\n10\n{_f(x1)}\n20\n{_f(y1)}\n11\n{_f(x2)}\n21\n{_f(y2)}\n"
    )


def _circle(x: float, y: float, r: float, layer: str = "HOLES") -> str:
    return f"0\nCIRCLE\n8\n{layer}\n10\n{_f(x)}\n20\n{_f(y)}\n40\n{_f(r)}\n"


def _poly(pts: Sequence[Point], layer: str = "0") -> str:
    parts: List[str] = []
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        parts.append(_line(x1, y1, x2, y2, layer))
    return "".join(parts)


def plate_entities(p: Plate, ox: float, oy: float) -> str:
    pts = [(x + ox, y + oy) for x, y in p.outline]
    body = _poly(pts, "CUT")
    for h in p.holes:
        body += _circle(h.x + ox, h.y + oy, h.d / 2.0, "HOLES")
    return body


def nest_positions(plates: Iterable[Plate], sheet_w: float = 300.0, gap: float = 3.0):
    """按数量展开，简单从左到右、从下到上码垛。"""
    x, y, row_h = gap, gap, 0.0
    out = []
    for spec in plates:
        xmin, ymin, xmax, ymax = bbox(spec)
        w, h = xmax - xmin + gap, ymax - ymin + gap
        for _ in range(spec.qty):
            if x + w > sheet_w:
                x = gap
                y += row_h
                row_h = 0.0
            out.append((spec, x - xmin, y - ymin))
            x += w
            row_h = max(row_h, h)
    return out


def dumps_nested(plates: Iterable[Plate], sheet_w: float = 300.0) -> str:
    ents = []
    for spec, ox, oy in nest_positions(plates, sheet_w=sheet_w):
        ents.append(plate_entities(spec, ox, oy))
    return (
        "0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n"
        "0\nSECTION\n2\nENTITIES\n"
        + "".join(ents)
        + "0\nENDSEC\n0\nEOF\n"
    )


def dumps_plate(p: Plate) -> str:
    return dumps_nested([Plate(**{**p.__dict__, "qty": 1})])
