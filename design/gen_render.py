#!/usr/bin/env python3
"""A.T.R.I. 等轴测外观渲染器（纯标准库软件渲染）。

不依赖 OpenGL / Blender / CAD：自己生成三角网格、做轴测投影、
按深度排序（画家算法）、平面着色，输出 SVG。

用法：
    python3 design/gen_render.py
    python3 design/gen_render.py --pose stance --png
    python3 design/gen_render.py --views front,iso,side

产出（design/renders/）：
    01_等轴测外观.svg        默认 3/4 视角，自然站姿
    02_正视外观.svg
    03_侧视外观.svg
    04_关节配色图.svg        按部位着色，便于识别构型

诚实说明
--------
这是**软件渲染的设计示意图**，不是照片、不是实机、也不是专业渲染器出图。
几何为基元近似（长方体/圆柱/球/胶囊），材质为单色平面着色。
所有尺寸为设计值，实物制造前须复测。
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import geometry  # noqa: E402
import gen_urdf  # noqa: E402

OUT_DIR = HERE / "renders"

Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]

# 自然站姿：微屈膝 + 手臂略微外展，比零姿态更像真实机器人
STANCE_POSE: Dict[str, float] = {
    # 微屈膝、重心略降，比笔直零位更像真实站立
    "left_hip_pitch": -8.0, "right_hip_pitch": -8.0,
    "left_knee_pitch": 16.0, "right_knee_pitch": 16.0,
    "left_ankle_pitch": -8.0, "right_ankle_pitch": -8.0,
    # 手臂外展，避免贴住躯干遮挡关节，也便于看清肩/肘/夹爪
    "left_shoulder_roll": 22.0, "right_shoulder_roll": -22.0,
    "left_shoulder_pitch": 10.0, "right_shoulder_pitch": 10.0,
    "left_elbow_pitch": -30.0, "right_elbow_pitch": -30.0,
    # 夹爪微张
    "left_gripper": 18.0, "right_gripper": 18.0,
    "head_pitch": -4.0,
    "head_yaw": 8.0,
}

# 按部位配色（关节配色图用）
GROUP_COLORS: Dict[str, Tuple[float, float, float]] = {
    "head": (0.95, 0.78, 0.25),
    "trunk": (0.90, 0.36, 0.22),
    "leg_l": (0.24, 0.55, 0.85),
    "leg_r": (0.20, 0.72, 0.62),
    "arm_l": (0.58, 0.40, 0.85),
    "arm_r": (0.85, 0.35, 0.62),
}


# --------------------------------------------------------------------------
# 相机：轴测投影
# --------------------------------------------------------------------------
class Camera:
    """方位角 (az) + 俯仰角 (el) 的轴测相机。

    先绕 Z 轴旋转 az，再绕 X 轴旋转 el，然后正交投影：
        屏幕 x = 旋转后 x
        屏幕 y = -旋转后 z
        深度   = 旋转后 y（越大越远）
    """

    def __init__(self, az_deg: float, el_deg: float,
                 width: int = 1250, height: int = 1250,
                 margin: float = 90.0) -> None:
        self.az = math.radians(az_deg)
        self.el = math.radians(el_deg)
        self.w = width
        self.h = height
        self.margin = margin
        self.scale = 1.0
        self.cx = width / 2.0
        self.cy = height / 2.0

    def rotate(self, p: Vec3) -> Vec3:
        ca, sa = math.cos(self.az), math.sin(self.az)
        x1 = p[0] * ca - p[1] * sa
        y1 = p[0] * sa + p[1] * ca
        z1 = p[2]
        ce, se = math.cos(self.el), math.sin(self.el)
        y2 = y1 * ce - z1 * se
        z2 = y1 * se + z1 * ce
        return (x1, y2, z2)

    def rotate_dir(self, v: Vec3) -> Vec3:
        """只旋转方向（法线用，不做平移）。"""
        return self.rotate(v)

    def project(self, p: Vec3) -> Tuple[float, float]:
        """世界坐标 -> 屏幕坐标（先旋转，再缩放平移）。"""
        x2, y2, z2 = p
        return (self.cx + x2 * self.scale, self.cy - z2 * self.scale)

    def fit(self, world_pts: Sequence[Vec3]) -> None:
        """根据所有顶点自动计算缩放与居中。"""
        if not world_pts:
            return
        rot = [self.rotate(p) for p in world_pts]
        xs = [r[0] for r in rot]
        zs = [r[2] for r in rot]
        w = max(xs) - min(xs)
        h = max(zs) - min(zs)
        avail_w = self.w - 2 * self.margin
        avail_h = self.h - 2 * self.margin
        self.scale = min(avail_w / max(w, 1e-6), avail_h / max(h, 1e-6))
        self.cx = self.w / 2.0 - (min(xs) + max(xs)) / 2.0 * self.scale
        self.cy = self.h / 2.0 + (min(zs) + max(zs)) / 2.0 * self.scale


# --------------------------------------------------------------------------
# 着色
# --------------------------------------------------------------------------
def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(v: Vec3) -> Vec3:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if n < 1e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _shade(base: Tuple[float, float, float], normal_cam: Vec3,
           light: Vec3, ambient: float = 0.34,
           rim: float = 0.18) -> str:
    """平面着色：环境光 + 漫反射 + 边缘光。"""
    diff = max(0.0, _dot(normal_cam, light))
    # 与视线夹角越大越"掠射"，给一点边缘提亮，避免暗面死黑
    grazing = 1.0 - abs(normal_cam[1])
    k = ambient + (1.0 - ambient) * diff + rim * grazing * 0.35
    k = max(0.10, min(1.35, k))
    r = min(1.0, base[0] * k)
    g = min(1.0, base[1] * k)
    b = min(1.0, base[2] * k)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


LIGHT = _norm((-0.45, -0.80, 0.55))  # 相机坐标系下的光照方向（上前方偏左）


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------
class Scene:
    """收集所有三角形并渲染成 SVG。"""

    def __init__(self, camera: Camera) -> None:
        self.cam = camera
        self.tris: List[Tuple[float, str]] = []  # (深度, svg polygon)
        self.world_pts: List[Vec3] = []

    def add_link(self, model: Dict[str, Any], link: Dict[str, Any],
                 tf: geometry.Matrix,
                 color_override: Optional[Tuple[float, float, float]] = None,
                 segments: int = 22, rings: int = 9) -> None:
        geom = link["geometry"]
        base = color_override or tuple(geom.get("color", [0.7, 0.7, 0.7]))
        try:
            local_tris = geometry.mesh(geom, segments, rings)
        except geometry.GeometryError:
            local_tris = geometry.mesh(geometry.equivalent_box(geom), segments)

        for tri in local_tris:
            world = [geometry.transform_point(tf, v) for v in tri]
            self.world_pts.extend(world)

    def build(self, model: Dict[str, Any], pose: Dict[str, float],
              by_group: bool = False, segments: int = 22,
              rings: int = 9) -> None:
        tfs = geometry.link_positions(model, pose)
        # 先收集顶点用来自动取景
        raw: List[Tuple[Dict[str, Any], geometry.Matrix]] = []
        for link in model["links"]:
            tf = tfs.get(link["name"])
            if tf is None:
                continue
            raw.append((link, tf))
            geom = link["geometry"]
            try:
                local_tris = geometry.mesh(geom, segments, rings)
            except geometry.GeometryError:
                local_tris = geometry.mesh(geometry.equivalent_box(geom),
                                           segments)
            for tri in local_tris:
                self.world_pts.extend(
                    geometry.transform_point(tf, v) for v in tri
                )
        self.cam.fit(self.world_pts)

        # 再逐三角形投影 + 着色
        for link, tf in raw:
            geom = link["geometry"]
            if by_group:
                base = GROUP_COLORS.get(link.get("group", ""),
                                        (0.7, 0.7, 0.7))
            else:
                base = tuple(geom.get("color", [0.7, 0.7, 0.7]))
            try:
                local_tris = geometry.mesh(geom, segments, rings)
            except geometry.GeometryError:
                local_tris = geometry.mesh(geometry.equivalent_box(geom),
                                           segments)
            for tri in local_tris:
                w = [geometry.transform_point(tf, v) for v in tri]
                r = [self.cam.rotate(p) for p in w]
                # 世界法线 -> 相机空间
                n_world = _norm(_cross(_sub(w[1], w[0]), _sub(w[2], w[0])))
                # 变换后的法线：用旋转后的边重算，等价且更省事
                n_cam = _norm(_cross(_sub(r[1], r[0]), _sub(r[2], r[0])))
                # 背面剔除：相机看向 +y，法线 y 分量为正表示背对
                if n_cam[1] > 0.02:
                    continue
                depth = (r[0][1] + r[1][1] + r[2][1]) / 3.0
                pts = " ".join(
                    f"{x:.1f},{y:.1f}" for x, y in
                    (self.cam.project(p) for p in r)
                )
                fill = _shade(base, n_cam, LIGHT)
                self.tris.append(
                    (depth, f'<polygon points="{pts}" fill="{fill}"/>')
                )

    def render(self, title: str = "", subtitle: str = "",
               note: str = "") -> str:
        c = self.cam
        head = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{c.w}" '
            f'height="{c.h}" viewBox="0 0 {c.w} {c.h}">',
            f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="#f7f9fc"/>'
            f'<stop offset="100%" stop-color="#dfe6ee"/></linearGradient></defs>',
            f'<rect width="{c.w}" height="{c.h}" fill="url(#bg)"/>',
        ]
        # 画家算法：远的先画
        body = [svg for _, svg in sorted(self.tris, key=lambda t: -t[0])]

        font = ("PingFang SC, Hiragino Sans GB, Microsoft YaHei, "
                "Helvetica, Arial, sans-serif")
        overlay = []
        if title:
            overlay.append(
                f'<text x="{c.w/2}" y="52" text-anchor="middle" font-size="30" '
                f'font-family="{font}" font-weight="bold" fill="#16202b">'
                f'{title}</text>'
            )
        if subtitle:
            overlay.append(
                f'<text x="{c.w/2}" y="82" text-anchor="middle" font-size="15" '
                f'font-family="{font}" fill="#55636f">{subtitle}</text>'
            )
        if note:
            overlay.append(
                f'<text x="{c.w/2}" y="{c.h-26}" text-anchor="middle" '
                f'font-size="13" font-family="{font}" fill="#77838f">'
                f'{note}</text>'
            )
        return "\n".join(head + body + overlay + ["</svg>"]) + "\n"


def add_ground(svg_parts: List[str], cam: Camera, model: Dict[str, Any],
               spacing: float = 200.0) -> List[str]:
    """画一个地板网格（简单的透视参考，帮助理解尺度）。"""
    env = gen_urdf.measured_envelope(model)
    half = 500.0
    lines = []
    x = -half
    while x <= half + 1e-6:
        a = cam.project(cam.rotate((x, -half, 0.0)))
        b = cam.project(cam.rotate((x, half, 0.0)))
        lines.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" '
                     f'x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#c3ccd6" '
                     f'stroke-width="1"/>')
        x += spacing
    y = -half
    while y <= half + 1e-6:
        a = cam.project(cam.rotate((-half, y, 0.0)))
        b = cam.project(cam.rotate((half, y, 0.0)))
        lines.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" '
                     f'x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#c3ccd6" '
                     f'stroke-width="1"/>')
        y += spacing
    return lines


# --------------------------------------------------------------------------
# 视图定义
# --------------------------------------------------------------------------
VIEWS: Dict[str, Dict[str, Any]] = {
    "iso": {"file": "01_等轴测外观.svg", "az": 38.0, "el": 18.0,
            "title": "A.T.R.I. 等轴测外观",
            "sub": "自然站姿 · 软件渲染（基元近似 · 平面着色）"},
    "iso_back": {"file": "05_等轴测外观-背面.svg", "az": 218.0, "el": 18.0,
                 "title": "A.T.R.I. 等轴测外观（背面）",
                 "sub": "自然站姿 · 软件渲染（基元近似 · 平面着色）"},
    # 相机：绕 Z 转 az 后，屏幕横轴 = 旋转后 x。
    # 机器人朝向 +X，故 az=-90 时屏幕横轴 = +Y，才是真正的正视（看到脸）。
    "front": {"file": "02_正视外观.svg", "az": -90.0, "el": 0.0,
              "title": "A.T.R.I. 正视外观",
              "sub": "从正前方观察（可见左右两侧肢体）· 软件渲染"},
    "side": {"file": "03_侧视外观.svg", "az": 0.0, "el": 0.0,
             "title": "A.T.R.I. 侧视外观",
             "sub": "从侧面观察（机器人朝向画面右侧）· 软件渲染"},
    "groups": {"file": "04_关节配色图.svg", "az": 38.0, "el": 18.0,
               "title": "A.T.R.I. 部位配色图",
               "sub": "按部位着色：头/躯干/左腿/右腿/左臂/右臂",
               "by_group": True},
}

GROUP_LEGEND = [
    ("head", "头部 head", (0.95, 0.78, 0.25)),
    ("trunk", "躯干 trunk", (0.90, 0.36, 0.22)),
    ("leg_l", "左腿 leg_l", (0.24, 0.55, 0.85)),
    ("leg_r", "右腿 leg_r", (0.20, 0.72, 0.62)),
    ("arm_l", "左臂 arm_l", (0.58, 0.40, 0.85)),
    ("arm_r", "右臂 arm_r", (0.85, 0.35, 0.62)),
]


def _legend_svg(cam: Camera) -> str:
    font = ("PingFang SC, Hiragino Sans GB, Microsoft YaHei, Helvetica, "
            "Arial, sans-serif")
    x, y = 40.0, 120.0
    out = [f'<rect x="{x}" y="{y}" width="250" height="{34*len(GROUP_LEGEND)+50}" '
           f'rx="10" fill="#ffffff" fill-opacity="0.88" stroke="#b9c4d0"/>']
    out.append(f'<text x="{x+18}" y="{y+30}" font-size="15" font-weight="bold" '
               f'font-family="{font}" fill="#16202b">部位配色</text>')
    for i, (_, label, col) in enumerate(GROUP_LEGEND):
        yy = y + 58 + i * 34
        out.append(f'<rect x="{x+18}" y="{yy-15}" width="22" height="16" rx="4" '
                   f'fill="#{int(col[0]*255):02x}{int(col[1]*255):02x}'
                   f'{int(col[2]*255):02x}" stroke="#8b96a2"/>')
        out.append(f'<text x="{x+50}" y="{yy}" font-size="13" '
                   f'font-family="{font}" fill="#2b3742">{label}</text>')
    return "\n".join(out)


def render_view(model: Dict[str, Any], key: str, pose: Dict[str, float],
                png: bool = False, ground: bool = True,
                width: int = 1250, height: int = 1250) -> Path:
    v = VIEWS[key]
    cam = Camera(v["az"], v["el"], width=width, height=height)
    scene = Scene(cam)
    scene.build(model, pose, by_group=v.get("by_group", False))
    svg = scene.render(title=v["title"], subtitle=v["sub"],
                       note="软件渲染设计示意图 · 非实机照片 · 尺寸为设计值，制造前须复测")

    # 地板网格插到最底层
    if ground and key.startswith("iso"):
        grid = add_ground([], cam, model)
        svg = svg.replace("</svg>", "\n".join(grid) + "\n</svg>")
    if v.get("by_group"):
        svg = svg.replace("</svg>", _legend_svg(cam) + "\n</svg>")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / v["file"]
    path.write_text(svg, encoding="utf-8")
    return path


def export_png(svg: Path, size: int = 1800) -> Optional[Path]:
    """用 macOS qlmanage 把 SVG 转成 PNG（先补成正方避免被裁切）。"""
    import re
    src = svg.read_text(encoding="utf-8")
    m = re.search(r'width="(\d+)" height="(\d+)"', src)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    side = max(w, h)
    pad = (side - h) // 2
    body = src.split(">", 1)[1].rsplit("</svg>", 1)[0]
    tmp = svg.with_name("_tmp_square.svg")
    tmp.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" '
        f'height="{side}" viewBox="0 0 {side} {side}">'
        f'<rect width="{side}" height="{side}" fill="#ffffff"/>'
        f'<g transform="translate(0,{pad})">{body}</g></svg>',
        encoding="utf-8",
    )
    try:
        subprocess.run(["qlmanage", "-t", "-s", str(size), "-o",
                        str(svg.parent), str(tmp)],
                       check=True, capture_output=True, timeout=120)
        produced = svg.parent / (tmp.name + ".png")
        if produced.exists():
            final = svg.with_suffix(".png")
            produced.replace(final)
            return final
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    finally:
        tmp.unlink(missing_ok=True)
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A.T.R.I. 等轴测外观渲染")
    ap.add_argument("--views", type=str, default="iso,front,side,groups,iso_back",
                    help="逗号分隔：iso,iso_back,front,side,groups")
    ap.add_argument("--pose", choices=["stance", "zero"], default="stance")
    ap.add_argument("--png", action="store_true", help="同时导出 PNG")
    ap.add_argument("--size", type=int, default=1800, help="PNG 尺寸")
    args = ap.parse_args(argv)

    model = gen_urdf.load_model()
    pose = STANCE_POSE if args.pose == "stance" else {}

    keys = [k.strip() for k in args.views.split(",") if k.strip()]
    for k in keys:
        if k not in VIEWS:
            print(f"未知视图: {k}（可选 {sorted(VIEWS)}）")
            return 2
        path = render_view(model, k, pose)
        print(f"已生成 {path}  ({path.stat().st_size} bytes)")
        if args.png:
            png = export_png(path, args.size)
            print(f"   PNG -> {png}" if png else "   PNG 转换失败")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
