"""零依赖三角网格：方块 / 圆柱 / 挤出。单位 mm。交错 pos+normal。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, List, Sequence, Tuple

Vec = Tuple[float, float, float]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec) -> Vec:
    n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


@dataclass
class Mesh:
    verts: List[float] = field(default_factory=list)  # x y z nx ny nz

    def add_tri(self, a: Vec, b: Vec, c: Vec) -> None:
        n = _norm(_cross(_sub(b, a), _sub(c, a)))
        for p in (a, b, c):
            self.verts.extend((p[0], p[1], p[2], n[0], n[1], n[2]))

    def add_quad(self, a: Vec, b: Vec, c: Vec, d: Vec) -> None:
        self.add_tri(a, b, c)
        self.add_tri(a, c, d)

    def extend(self, other: "Mesh") -> None:
        self.verts.extend(other.verts)

    def translated(self, x: float, y: float, z: float) -> "Mesh":
        out = Mesh()
        v = self.verts
        for i in range(0, len(v), 6):
            out.verts.extend((v[i] + x, v[i + 1] + y, v[i + 2] + z, v[i + 3], v[i + 4], v[i + 5]))
        return out

    def tri_count(self) -> int:
        return len(self.verts) // 18


def box(sx: float, sy: float, sz: float, center: Vec = (0.0, 0.0, 0.0)) -> Mesh:
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    cx, cy, cz = center
    p = [
        (cx - hx, cy - hy, cz - hz),
        (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz),
        (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz),
        (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz),
        (cx - hx, cy + hy, cz + hz),
    ]
    m = Mesh()
    m.add_quad(p[0], p[1], p[2], p[3])
    m.add_quad(p[4], p[7], p[6], p[5])
    m.add_quad(p[0], p[4], p[5], p[1])
    m.add_quad(p[2], p[6], p[7], p[3])
    m.add_quad(p[0], p[3], p[7], p[4])
    m.add_quad(p[1], p[5], p[6], p[2])
    return m


def cylinder(radius: float, height: float, axis: str = "z", segs: int = 16, center: Vec = (0.0, 0.0, 0.0)) -> Mesh:
    m = Mesh()
    h = height / 2.0
    cx, cy, cz = center

    def pt(i: int, z: float) -> Vec:
        a = 2 * math.pi * i / segs
        x, y = radius * math.cos(a), radius * math.sin(a)
        if axis == "z":
            return (cx + x, cy + y, cz + z)
        if axis == "y":
            return (cx + x, cy + z, cz + y)
        return (cx + z, cy + x, cz + y)

    for i in range(segs):
        m.add_quad(pt(i, -h), pt(i + 1, -h), pt(i + 1, h), pt(i, h))
        top = (cx, cy, cz + h) if axis == "z" else ((cx, cy + h, cz) if axis == "y" else (cx + h, cy, cz))
        bot = (cx, cy, cz - h) if axis == "z" else ((cx, cy - h, cz) if axis == "y" else (cx - h, cy, cz))
        m.add_tri(top, pt(i, h), pt(i + 1, h))
        m.add_tri(bot, pt(i + 1, -h), pt(i, -h))
    return m


def cylinder_between(a: Vec, b: Vec, r: float = 1.6, segs: int = 8) -> Mesh:
    """两点之间的圆柱，用来画舵机总线 / CSI。"""
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0)
    m = cylinder(r, length, "z", segs, (0.0, 0.0, 0.0))
    ux, uy, uz = dx / length, dy / length, dz / length
    if uz < -0.999:
        m = Mesh_rotated(m, (1.0, 0.0, 0.0), math.pi)
    elif uz < 0.999:
        cx, cy = -uy, ux
        n = math.hypot(cx, cy) or 1.0
        ang = math.acos(max(-1.0, min(1.0, uz)))
        m = Mesh_rotated(m, (cx / n, cy / n, 0.0), ang)
    return m.translated(*mid)


def rod(a: Vec, b: Vec, thick: float) -> Mesh:
    """两点之间的方杆（沿最长主轴近似，足够预览）。"""
    mx = (a[0] + b[0]) / 2.0
    my = (a[1] + b[1]) / 2.0
    mz = (a[2] + b[2]) / 2.0
    dx, dy, dz = abs(b[0] - a[0]), abs(b[1] - a[1]), abs(b[2] - a[2])
    return box(max(dx, thick), max(dy, thick), max(dz, thick), (mx, my, mz))


def _rot_y_to_axis(axis: str) -> Tuple[Vec, float]:
    """把局部 +Y 转到关节轴。返回 (旋转轴, 弧度)。"""
    if axis == "y":
        return ((0.0, 0.0, 1.0), 0.0)
    if axis == "x":
        return ((0.0, 0.0, 1.0), -math.pi / 2.0)  # +Y → +X
    return ((1.0, 0.0, 0.0), math.pi / 2.0)  # +Y → +Z


def Mesh_rotated(m: Mesh, ax: Vec, th: float) -> Mesh:
    if abs(th) < 1e-12:
        return m
    n = _norm(ax)
    c, s, C = math.cos(th), math.sin(th), 1.0 - math.cos(th)
    x, y, z = n
    r = (
        (x * x * C + c, x * y * C - z * s, x * z * C + y * s),
        (y * x * C + z * s, y * y * C + c, y * z * C - x * s),
        (z * x * C - y * s, z * y * C + x * s, z * z * C + c),
    )

    def rv(p: Vec) -> Vec:
        return (
            r[0][0] * p[0] + r[0][1] * p[1] + r[0][2] * p[2],
            r[1][0] * p[0] + r[1][1] * p[1] + r[1][2] * p[2],
            r[2][0] * p[0] + r[2][1] * p[1] + r[2][2] * p[2],
        )

    out = Mesh()
    v = m.verts
    for i in range(0, len(v), 6):
        p = rv((v[i], v[i + 1], v[i + 2]))
        nn = rv((v[i + 3], v[i + 4], v[i + 5]))
        out.verts.extend((p[0], p[1], p[2], nn[0], nn[1], nn[2]))
    return out


def orient_z_to_axis(m: Mesh, axis: Sequence[float]) -> Mesh:
    """铝板默认厚度 +Z，转到关节轴。"""
    ax = axis_of(axis)
    if ax == "z":
        return m
    if ax == "y":
        return Mesh_rotated(m, (1.0, 0.0, 0.0), -math.pi / 2.0)
    return Mesh_rotated(m, (0.0, 1.0, 0.0), math.pi / 2.0)


def limb_side_plate(m: Mesh) -> Mesh:
    m = Mesh_rotated(m, (0.0, 1.0, 0.0), math.pi / 2.0)
    return Mesh_rotated(m, (0.0, 0.0, 1.0), math.pi / 2.0)


def axis_of(vec: Sequence[float]) -> str:
    ax, ay, az = abs(vec[0]), abs(vec[1]), abs(vec[2])
    if ay >= ax and ay >= az:
        return "y"
    if ax >= az:
        return "x"
    return "z"


def round_rect_pts(w: float, h: float, r: float, n: int = 6) -> List[Tuple[float, float]]:
    hw, hh = w / 2.0, h / 2.0
    r = min(r, hw, hh)
    pts: List[Tuple[float, float]] = []
    corners = (
        (hw - r, hh - r, 0.0),
        (-hw + r, hh - r, math.pi / 2),
        (-hw + r, -hh + r, math.pi),
        (hw - r, -hh + r, 3 * math.pi / 2),
    )
    for cx, cy, a0 in corners:
        for i in range(n + 1):
            a = a0 + (math.pi / 2) * (i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def extrude_poly(
    outline: Sequence[Tuple[float, float]],
    thick: float,
    axis: str = "z",
    center: Vec = (0.0, 0.0, 0.0),
) -> Mesh:
    """沿 axis 挤出闭合折线（侧面 + 顶底三角扇）。"""
    pts = list(outline)
    n = len(pts)
    if n < 3:
        return Mesh()
    h = thick / 2.0
    cx, cy, cz = center

    def put(x: float, y: float, z: float) -> Vec:
        if axis == "z":
            return (cx + x, cy + y, cz + z)
        if axis == "y":
            return (cx + x, cy + z, cz + y)
        return (cx + z, cy + x, cz + y)

    m = Mesh()
    for i in range(n):
        j = (i + 1) % n
        a0 = put(pts[i][0], pts[i][1], -h)
        a1 = put(pts[j][0], pts[j][1], -h)
        a2 = put(pts[j][0], pts[j][1], h)
        a3 = put(pts[i][0], pts[i][1], h)
        m.add_quad(a0, a1, a2, a3)
    top = put(0.0, 0.0, h)
    bot = put(0.0, 0.0, -h)
    for i in range(n):
        j = (i + 1) % n
        m.add_tri(top, put(pts[i][0], pts[i][1], h), put(pts[j][0], pts[j][1], h))
        m.add_tri(bot, put(pts[j][0], pts[j][1], -h), put(pts[i][0], pts[i][1], -h))
    return m


def rounded_box(
    sx: float,
    sy: float,
    sz: float,
    r: float = 2.0,
    segs: int = 5,
    center: Vec = (0.0, 0.0, 0.0),
    axis: str = "z",
) -> Mesh:
    if axis == "z":
        w, h, t = sx, sy, sz
    elif axis == "y":
        w, h, t = sx, sz, sy
    else:
        w, h, t = sy, sz, sx
    return extrude_poly(round_rect_pts(w, h, r, segs), t, axis=axis, center=center)


def plate_mesh(
    outline: Sequence[Tuple[float, float]],
    thick: float,
    holes: Sequence[Any] = (),
    axis: str = "z",
    center: Vec = (0.0, 0.0, 0.0),
    nx: int = 18,
    ny: int = 14,
) -> Mesh:
    """激光板：网格挤出，圆孔挖空。holes 项需有 x,y,d。"""
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    # 点在多边形内（射线法）
    n = len(outline)

    def inside(x: float, y: float) -> bool:
        ok = False
        for i in range(n):
            x1, y1 = outline[i]
            x2, y2 = outline[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                t = (y - y1) / ((y2 - y1) or 1e-12)
                if x < x1 + t * (x2 - x1):
                    ok = not ok
        if not ok:
            return False
        for h in holes:
            dx, dy = x - h.x, y - h.y
            if dx * dx + dy * dy <= (h.d * 0.5) ** 2:
                return False
        return True

    m = Mesh()
    dx = (xmax - xmin) / nx
    dy = (ymax - ymin) / ny
    h = thick / 2.0
    cx, cy, cz = center

    def put(x: float, y: float, z: float) -> Vec:
        if axis == "z":
            return (cx + x, cy + y, cz + z)
        if axis == "y":
            return (cx + x, cy + z, cz + y)
        return (cx + z, cy + x, cz + y)

    for iy in range(ny):
        y0 = ymin + iy * dy
        y1 = y0 + dy
        for ix in range(nx):
            x0 = xmin + ix * dx
            x1 = x0 + dx
            mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            if not inside(mx, my):
                continue
            q = [
                put(x0, y0, -h),
                put(x1, y0, -h),
                put(x1, y1, -h),
                put(x0, y1, -h),
                put(x0, y0, h),
                put(x1, y0, h),
                put(x1, y1, h),
                put(x0, y1, h),
            ]
            m.add_quad(q[0], q[1], q[2], q[3])
            m.add_quad(q[4], q[7], q[6], q[5])
            m.add_quad(q[0], q[4], q[5], q[1])
            m.add_quad(q[2], q[6], q[7], q[3])
            m.add_quad(q[0], q[3], q[7], q[4])
            m.add_quad(q[1], q[5], q[6], q[2])
    return m


def servo_sts3215(axis: str = "y", center: Vec = (0.0, 0.0, 0.0)) -> Mesh:
    """飞特 STS3215-C018：无耳、两端 Φ20 盘、25T 花键、副轴。局部 +Y 为输出轴。"""
    L, Wd, Ax = 45.2, 24.7, 35.0
    near = 10.2
    body = rounded_box(L, Ax, Wd, r=2.2, segs=4, center=(near - L / 2.0, 0.0, 0.0), axis="y")
    boss = cylinder(10.0, 2.5, "y", 20, (0.0, Ax / 2.0 + 1.25, 0.0))
    spline = cylinder(2.95, 3.2, "y", 16, (0.0, Ax / 2.0 + 2.5 + 1.6, 0.0))
    stub = cylinder(3.0, 4.1, "y", 14, (0.0, -Ax / 2.0 - 2.05, 0.0))
    idle = cylinder(10.0, 2.1, "y", 18, (0.0, -Ax / 2.0 - 1.05, 0.0))
    cable = rounded_box(6.0, 8.0, 4.0, r=1.0, segs=3, center=(near - L - 3.0, 0.0, 0.0), axis="x")
    m = Mesh()
    for part in (body, boss, spline, stub, idle, cable):
        m.extend(part)
    ax, th = _rot_y_to_axis(axis)
    m = Mesh_rotated(m, ax, th)
    return m.translated(*center)


def horn_disc(axis: str = "y", center: Vec = (0.0, 0.0, 0.0)) -> Mesh:
    disc = cylinder(10.0, 4.0, axis, 24, center)
    hub = cylinder(3.2, 5.0, axis, 12, center)
    m = Mesh()
    m.extend(disc)
    m.extend(hub)
    return m
