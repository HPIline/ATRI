"""零位装配体检：舵机是否在关节上、零件是否悬空、舵机是否对穿。"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from .assembly3d import build_parts, fk, kinematic_tree, m_apply, m_ident

AABB = Tuple[float, float, float, float, float, float]


def _aabb(verts: Sequence[float]) -> AABB:
    xs = verts[0::6]
    ys = verts[1::6]
    zs = verts[2::6]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _contains(bb: AABB, p: Sequence[float], m: float) -> bool:
    return (
        bb[0] - m <= p[0] <= bb[3] + m
        and bb[1] - m <= p[1] <= bb[4] + m
        and bb[2] - m <= p[2] <= bb[5] + m
    )


def _overlap(a: AABB, b: AABB) -> bool:
    return a[0] < b[3] and a[3] > b[0] and a[1] < b[4] and a[4] > b[1] and a[2] < b[5] and a[5] > b[2]


def _vol(bb: AABB) -> float:
    return max(0.0, bb[3] - bb[0]) * max(0.0, bb[4] - bb[1]) * max(0.0, bb[5] - bb[2])


def _inter(a: AABB, b: AABB) -> AABB:
    return (
        max(a[0], b[0]),
        max(a[1], b[1]),
        max(a[2], b[2]),
        min(a[3], b[3]),
        min(a[4], b[4]),
        min(a[5], b[5]),
    )


def audit(parts: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    tree = kinematic_tree()
    if parts is None:
        parts = build_parts()
    by = {p["name"]: p for p in parts}
    missing: List[str] = []
    floating: List[str] = []
    pierce: List[str] = []

    for j in tree["joints"]:
        key = f"servo-{j['name']}"
        if key not in by:
            missing.append(key)
            continue
        bb = _aabb(by[key]["verts"])
        if not _contains(bb, j["xyz"], 28.0):
            missing.append(f"{key} not at joint {j['xyz']} aabb={tuple(round(x,1) for x in bb)}")

    for name in (
        "neck-column",
        "head-bracket",
        "torso-post-l",
        "torso-post-r",
        "torso-floor",
        "foot-upright-l-a",
        "wrist-l-a",
        "servo-left_ankle_pitch",
        "servo-left_gripper",
        "servo-head_pitch",
        "pelvis-open-frame",
        "pelvis-output-adapter-left",
        "pelvis-output-adapter-right",
        "pelvis-output-adapter-trunk",
        "cover-torso-f",
    ):
        if name not in by:
            floating.append(f"missing frame {name}")
    if "pelvis-al" in by:
        pierce.append("pelvis-al midplane plate still present")

    def extent(name: str, axis: int) -> Tuple[float, float]:
        v = by[name]["verts"]
        xs = v[axis::6]
        return min(xs), max(xs)

    nc = by.get("neck-column")
    if nc is not None and nc["link"] != "head_yaw_link":
        floating.append("neck-column not on head_yaw_link")
    side = by.get("neck-side-a")
    if side is not None:
        z0, z1 = extent("neck-side-a", 2)
        hp = next(j for j in tree["joints"] if j["name"] == "head_pitch")
        if z1 < hp["xyz"][2] - 8:
            floating.append(f"neck-side does not reach head_pitch z1={z1:.1f}")
        if z0 > 26:
            floating.append(f"neck-side does not meet head_yaw z0={z0:.1f}")

    if "cover-head" in by:
        zmin, _ = extent("cover-head", 2)
        if zmin < 10.0:
            pierce.append(f"cover-head swallows pitch servo zmin={zmin:.1f}")
        if zmin > 20.0:
            floating.append(f"cover-head floats zmin={zmin:.1f}")

    for name in ("cover-torso-l", "cover-torso-r"):
        if name in by:
            ymin, ymax = extent(name, 1)
            if ymax - ymin > 12.0:
                floating.append(f"{name} shelf dy={ymax - ymin:.1f}")

    if "foot-upright-l-a" in by:
        _, zmax = extent("foot-upright-l-a", 2)
        if zmax < -6.0:
            floating.append(f"foot-upright does not reach ankle zmax={zmax:.1f}")
        zmin, _ = extent("foot-upright-l-a", 2)
        if "foot-l" in by:
            plate_z = extent("foot-l", 2)[0]
            if abs(zmin - plate_z) > 8.0:
                floating.append(f"foot-upright not on plate dz={zmin - plate_z:.1f}")

    W = fk(tree)

    def world_bb(p: Dict[str, Any]) -> AABB:
        w = W.get(p["link"], m_ident()) if p["link"] else m_ident()
        xs: List[float] = []
        ys: List[float] = []
        zs: List[float] = []
        v = p["verts"]
        for i in range(0, len(v), 6):
            x, y, z = m_apply(w, (v[i], v[i + 1], v[i + 2]))
            xs.append(x)
            ys.append(y)
            zs.append(z)
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    servos = [(p["name"], world_bb(p)) for p in parts if p["name"].startswith("servo-")]
    for i, (n1, a1) in enumerate(servos):
        for n2, a2 in servos[i + 1 :]:
            if not _overlap(a1, a2):
                continue
            iv = _vol(_inter(a1, a2))
            if iv > 0.35 * min(_vol(a1), _vol(a2)):
                pierce.append(f"{n1} x {n2} overlap {iv:.0f} mm3")

    def aabb_gap(a: AABB, b: AABB) -> float:
        dx = max(0.0, max(a[0] - b[3], b[0] - a[3]))
        dy = max(0.0, max(a[1] - b[4], b[1] - a[4]))
        dz = max(0.0, max(a[2] - b[5], b[2] - a[5]))
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    for j in tree["joints"]:
        sn, hn = f"servo-{j['name']}", f"horn-{j['name']}"
        if sn not in by or hn not in by:
            continue
        sb, hb = world_bb(by[sn]), world_bb(by[hn])
        if not _overlap(sb, hb) and aabb_gap(sb, hb) > 4.0:
            floating.append(f"{hn} gap {aabb_gap(sb, hb):.1f}mm from servo")

    for p in parts:
        if p["kind"] != "petg":
            continue
        pb = world_bb(p)
        for sn, sb in servos:
            if not _overlap(pb, sb):
                continue
            iv = _vol(_inter(pb, sb))
            if p["name"].startswith(("cam-", "camera", "lens", "cover-head", "gland-", "channel-", "neck-collar")):
                continue
            if iv > 0.20 * min(_vol(pb), _vol(sb)):
                pierce.append(f"{p['name']} x {sn} overlap {iv:.0f} mm3")

    narrow_phase_required: List[str] = []
    skip_al = ("idle-", "horn-", "c-")
    for p in parts:
        if p["kind"] not in ("al", "standoff"):
            continue
        if p["name"].startswith(skip_al):
            continue
        pb = world_bb(p)
        for sn, sb in servos:
            if not _overlap(pb, sb):
                continue
            iv = _vol(_inter(pb, sb))
            if p["kind"] == "standoff":
                if iv > 80.0:
                    pierce.append(f"{p['name']} x {sn} overlap {iv:.0f} mm3")
            elif iv > 0.25 * _vol(sb):
                if p["name"].startswith("pelvis-output-adapter-"):
                    # L-angle AABBs include empty air. Do not declare either
                    # collision or clearance without the B-rep narrow phase.
                    narrow_phase_required.append(f"{p['name']} x {sn}")
                else:
                    pierce.append(f"{p['name']} x {sn} overlap {iv:.0f} mm3")

    if "pelvis-front" in by:
        xmin, xmax = extent("pelvis-front", 0)
        if xmax - xmin > 8.0:
            pierce.append(f"pelvis-front is a midplane shelf dx={xmax-xmin:.1f}")

    if "lens" in by and "cover-head-f" in by:
        if extent("lens", 0)[1] < extent("cover-head-f", 0)[1]:
            floating.append("camera lens does not protrude through face")

    return {
        "missing_joint_servos": missing,
        "floating": floating,
        "pierce": pierce,
        "narrow_phase_required": narrow_phase_required,
        "scope": "Legacy proxy meshes only; use cad_audit for manufacturing solids",
        "release_ready": False,
        "ok": not missing and not floating and not pierce and not narrow_phase_required,
        "n_parts": len(parts),
    }


def rom_audit(parts: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """每个关节走到限位，非相邻舵机 AABB 体积重叠不得超过 35%。"""
    tree = kinematic_tree()
    if parts is None:
        parts = build_parts()
    servo_parts = [p for p in parts if p["name"].startswith("servo-")]
    share: Dict[str, List[str]] = {}
    for j in tree["joints"]:
        share.setdefault(j["parent"], []).append(j["name"])
        share.setdefault(j["child"], []).append(j["name"])
    adjacent = set()
    for names in share.values():
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                adjacent.add(tuple(sorted((a, b))))

    pierce: List[str] = []
    n = len(tree["joints"])
    for i, j in enumerate(tree["joints"]):
        for lim in j["limit_deg"]:
            if abs(float(lim)) < 1e-6:
                continue
            angles = [0.0] * n
            angles[i] = float(lim)
            W = fk(tree, angles)
            bbs: List[Tuple[str, AABB]] = []
            for p in servo_parts:
                w = W.get(p["link"], m_ident()) if p["link"] else m_ident()
                xs: List[float] = []
                ys: List[float] = []
                zs: List[float] = []
                v = p["verts"]
                for k in range(0, len(v), 6):
                    x, y, z = m_apply(w, (v[k], v[k + 1], v[k + 2]))
                    xs.append(x)
                    ys.append(y)
                    zs.append(z)
                bbs.append((p["name"], (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))))
            for ia, (n1, a1) in enumerate(bbs):
                for n2, a2 in bbs[ia + 1 :]:
                    ja, jb = n1[6:], n2[6:]
                    if tuple(sorted((ja, jb))) in adjacent:
                        continue
                    if not _overlap(a1, a2):
                        continue
                    iv = _vol(_inter(a1, a2))
                    if iv > 0.35 * min(_vol(a1), _vol(a2)):
                        pierce.append(f"{j['name']}={lim:g} {n1} x {n2} {iv:.0f}mm3")
    return {"pierce": pierce, "ok": not pierce, "n_checks": n * 2}
