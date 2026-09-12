"""CadQuery 零件：STS3215 + 铝板挤出。需 .venv-cad。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import cadquery as cq
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要 CadQuery：仓库根目录 .venv-cad（Python 3.12）") from exc

CAD = Path(__file__).resolve().parents[1] / "cad"
sys.path.insert(0, str(CAD))

from kit import servo_frame  # noqa: E402
from parts import sanitize  # noqa: E402

from .plates import Plate
from .profile import CAD_INTERFACE, SERVO

VENDOR_STEP = CAD / "vendor" / "so-arm100" / "STS3215_03a.step"


def sts3215_parametric() -> "cq.Workplane":
    """按 servo_frame：原点=输出轴心，+Y 输出，+X 机身短端。"""
    f = servo_frame("STS3215")
    cx = (f["x_min"] + f["x_max"]) / 2.0
    body = (
        cq.Workplane("XZ")
        .rect(f["len"], f["width"])
        .extrude(f["axial"])
        .translate((cx, -f["axial"] / 2.0, 0.0))
    )
    try:
        body = body.edges("|Y").fillet(1.8)
    except Exception:
        pass
    boss = (
        cq.Workplane("XZ")
        .circle(f["boss_d"] / 2.0)
        .extrude(f["boss_t"])
        .translate((0.0, f["axial"] / 2.0, 0.0))
    )
    spline = (
        cq.Workplane("XZ")
        .circle(f["spline_d"] / 2.0)
        .extrude(f["spline_h"] + 1.6)
        .translate((0.0, f["boss_face"], 0.0))
    )
    idle = (
        cq.Workplane("XZ")
        .circle(f["boss_d"] / 2.0)
        .extrude(2.1)
        .translate((0.0, -f["axial"] / 2.0 - 2.1, 0.0))
    )
    stub = (
        cq.Workplane("XZ")
        .circle(f["stub_dia"] / 2.0)
        .extrude(f["stub_len"])
        .translate((0.0, -f["axial"] / 2.0 - 2.1 - f["stub_len"], 0.0))
    )
    cable = (
        cq.Workplane("XY")
        .box(8.0, 6.0, 4.0)
        .translate((f["x_min"] - 4.0, 0.0, 0.0))
    )
    part = body.union(boss).union(spline).union(idle).union(stub).union(cable)
    return sanitize(part)


def sts3215() -> "cq.Workplane":
    """Load the vendor geometry; assembly exports must never use a silent placeholder."""
    if not VENDOR_STEP.is_file():
        raise FileNotFoundError(f"Required vendor servo STEP is missing: {VENDOR_STEP}")
    imported = cq.importers.importStep(str(VENDOR_STEP))
    # Native shaft is +Z at X=12.5. Recenter before orienting to +Y.
    aligned = imported.translate((-CAD_INTERFACE["vendor_shaft_x_mm"], 0, 0)).rotate((0, 0, 0), (1, 0, 0), -90)
    bb = aligned.val().BoundingBox()
    if not (40.0 < bb.xlen < 52.0 and 32.0 < bb.ylen < 46.0 and 20.0 < bb.zlen < 30.0):
        raise ValueError(f"Vendor servo geometry has unexpected bounds: {bb.xlen}, {bb.ylen}, {bb.zlen}")
    if not aligned.val().isValid():
        raise ValueError("Vendor servo STEP contains invalid geometry")
    return aligned


def sts3215_components() -> dict[str, "cq.Workplane"]:
    """Partition the reference STEP at its measured case faces, without remeshing.

    These are reference envelopes, not a claim that the old supplier STEP matches
    every C018 accessory dimension. The unsplit source remains available above.
    """
    ref = sts3215()
    r = CAD_INTERFACE["vendor_accessory_cut_radius_mm"]
    end = CAD_INTERFACE["vendor_cut_extent_mm"]
    front = CAD_INTERFACE["vendor_drive_body_face_mm"]
    back = CAD_INTERFACE["vendor_passive_body_face_mm"]
    def region(lo, hi):
        return cq.Workplane("XY").circle(r).extrude(hi-lo).rotate((0,0,0),(1,0,0),-90).translate((0,lo,0))
    drive_tool, passive_tool = region(front,end), region(-end,back)
    drive, passive = ref.intersect(drive_tool), ref.intersect(passive_tool)
    body = ref.cut(drive_tool).cut(passive_tool)
    return {"body": body, "drive": drive, "passive": passive}


def c018_accessories() -> dict[str, "cq.Workplane"]:
    """Purchased C018 discs, official p7 envelopes; thread/spline are symbolic.

    Not tooling for manufacturing a 25T spline. The spline pocket uses its
    nominal envelope; its actual tooth form remains a purchased-part interface.
    """
    def axial(w, lo):
        return w.rotate((0,0,0),(1,0,0),-90).translate((0,lo,0))
    od, hub = SERVO["horn_od_mm"], SERVO["horn_hub_od_mm"]
    ft, tt = SERVO["horn_flange_t_mm"], SERVO["horn_total_t_mm"]
    front = cq.Workplane("XY").polygon(8,od).extrude(ft).translate((0,0,tt-ft))
    front = front.union(cq.Workplane("XY").circle(hub/2).extrude(tt))
    front = front.cut(cq.Workplane("XY").circle(SERVO["horn_center_clear_mm"]/2).extrude(tt))
    front = front.cut(cq.Workplane("XY").circle(SERVO["horn_spline_od_mm"]/2).extrude(SERVO["horn_spline_depth_mm"]))
    rt, rf = SERVO["rear_disc_total_t_mm"], SERVO["rear_disc_flange_t_mm"]
    rear = cq.Workplane("XY").circle(od/2).extrude(rf)
    rear = rear.union(cq.Workplane("XY").circle(hub/2).extrude(rt))
    rear = rear.cut(cq.Workplane("XY").circle(SERVO["rear_disc_bore_mm"]/2).extrude(rt))
    a = SERVO["horn_hole_square_mm"]/2
    for x,z in ((a,a),(a,-a),(-a,a),(-a,-a)):
        hole = cq.Workplane("XY").center(x,z).circle(1.5).extrude(max(tt,rt))
        front, rear = front.cut(hole), rear.cut(hole)
    return {"drive": axial(front,CAD_INTERFACE["drive_hub_inner_y_mm"]),
            "passive": axial(rear,CAD_INTERFACE["passive_outer_y_mm"])}


def c018_horn(passive: bool = False) -> "cq.Workplane":
    """One purchased accessory in canonical servo coordinates."""
    return c018_accessories()["passive" if passive else "drive"]


def horn_disc() -> "cq.Workplane":
    """25T 金属舵盘：Φ20×4，中心 Φ6.2，4×M2.5 在 9.90 方阵（PCD14）。"""
    disc = (
        cq.Workplane("XY")
        .circle(10.0)
        .extrude(4.0)
        .translate((0.0, 0.0, -2.0))
        .rotate((0, 0, 0), (1, 0, 0), 90)
    )
    hole = (
        cq.Workplane("XY")
        .circle(3.1)
        .extrude(8.0)
        .translate((0.0, 0.0, -4.0))
        .rotate((0, 0, 0), (1, 0, 0), 90)
    )
    s = 4.95
    for x, z in ((s, s), (s, -s), (-s, s), (-s, -s)):
        hole = hole.union(
            cq.Workplane("XY")
            .circle(1.35)
            .extrude(8.0)
            .translate((x, z, -4.0))
            .rotate((0, 0, 0), (1, 0, 0), 90)
        )
    return disc.cut(hole)


def m25_screw() -> "cq.Workplane":
    """M2.5×8 圆柱头：沿 +Y，头在 +Y。"""
    shank = cq.Workplane("XZ").circle(1.15).extrude(6.5).translate((0.0, -3.25, 0.0))
    head = cq.Workplane("XZ").circle(2.25).extrude(1.6).translate((0.0, 3.25, 0.0))
    return shank.union(head)


def plate_solid(p: Plate) -> "cq.Workplane":
    t = p.thickness_mm
    wp = cq.Workplane("XY").polyline(p.outline).close().extrude(t)
    wp = wp.translate((0.0, 0.0, -t / 2.0))
    for h in p.holes:
        cut = (
            cq.Workplane("XY")
            .circle(h.d / 2.0)
            .extrude(t + 4.0)
            .translate((h.x, h.y, -t / 2.0 - 2.0))
        )
        wp = wp.cut(cut)
    return sanitize(wp)


def cover_shell(sx: float, sy: float, sz: float, wall: float = 2.0, r: float = 8.0) -> "cq.Workplane":
    outer = cq.Workplane("XY").box(sx, sy, sz)
    try:
        outer = outer.edges("|Z").fillet(min(r, sx, sy) / 2.0 * 0.4)
    except Exception:
        pass
    inner = cq.Workplane("XY").box(max(sx - 2 * wall, 4.0), max(sy - 2 * wall, 4.0), sz + 2.0)
    return sanitize(outer.cut(inner.translate((0, 0, wall))))


def orient_y_to_axis(wp: "cq.Workplane", axis: Any) -> "cq.Workplane":
    ax, ay, az = float(axis[0]), float(axis[1]), float(axis[2])
    if abs(ay) >= abs(ax) and abs(ay) >= abs(az):
        return wp if ay>=0 else wp.rotate((0,0,0),(1,0,0),180)
    if abs(ax) >= abs(az):
        return wp.rotate((0, 0, 0), (0, 0, 1), -90 if ax > 0 else 90)
    return wp.rotate((0, 0, 0), (1, 0, 0), 90 if az > 0 else -90)


def orient_z_to_axis(wp: "cq.Workplane", axis: Any) -> "cq.Workplane":
    """铝板默认厚度 +Z，转到关节轴。"""
    ax, ay, az = float(axis[0]), float(axis[1]), float(axis[2])
    if abs(az) >= abs(ax) and abs(az) >= abs(ay):
        return wp
    if abs(ay) >= abs(ax):
        return wp.rotate((0, 0, 0), (1, 0, 0), -90 if ay > 0 else 90)
    return wp.rotate((0, 0, 0), (0, 1, 0), 90 if ax > 0 else -90)


def limb_side_plate(wp: "cq.Workplane") -> "cq.Workplane":
    """C 臂：长度 X、厚度 Z → 长度 Z、厚度 Y（腿两侧夹板）。"""
    return wp.rotate((0, 0, 0), (0, 1, 0), 90).rotate((0, 0, 0), (0, 0, 1), 90)
