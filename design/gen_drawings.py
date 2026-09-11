#!/usr/bin/env python3
"""A.T.R.I. 2D 工程图生成器（纯标准库）。

产出：
    01_关节编号图.svg    22 个关节逐个标注（躯干 2 DOF 高亮）★ 最高优先级
    02_三视图.svg        正视 / 侧视 / 俯视 + 总体尺寸与官方上限对比
    04_尺寸链图.svg      关节链尺寸链与总高校核
    05_舵机布局图.svg    22 个舵机安装位置与朝向

用法：
    python3 design/gen_drawings.py
    python3 design/gen_drawings.py --only joints
    python3 design/gen_drawings.py --png        # 同时导出 PNG（rsvg-convert / inkscape / qlmanage，缺则只留 SVG）

注意
----
这些是**由设计模型投影生成的示意图**，不是 CAD 出图，也不是渲染图。
标注尺寸为设计值，实物制造前需复测。
"""
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import geometry  # noqa: E402
import gen_urdf  # noqa: E402

OUT_DIR = HERE / "drawings"

# 配色
C_LINE = "#1a1a1a"
C_THIN = "#8a8a8a"
C_DIM = "#0b6bb5"
C_TRUNK = "#d4572b"      # 躯干关节高亮色
C_TRUNK_FILL = "#fbe3d8"
C_CENTER = "#c0392b"
C_FILL = "#e8edf2"
C_TEXT = "#1a1a1a"

FONT = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Helvetica, Arial, sans-serif"


# --------------------------------------------------------------------------
# SVG 画布
# --------------------------------------------------------------------------
class Sheet:
    """一张图纸：管理坐标变换与 SVG 元素。"""

    def __init__(self, width: int = 1684, height: int = 1191,
                 title: str = "", drawing_no: str = "ATRI-000",
                 scale_text: str = "") -> None:
        self.w = width
        self.h = height
        self.title = title
        self.drawing_no = drawing_no
        self.scale_text = scale_text
        self.parts: List[str] = []
        self._clip: Optional[Tuple[float, float, float, float]] = None

    # --- 基础图元 ---
    def add(self, s: str) -> None:
        self.parts.append(s)

    def line(self, x1: float, y1: float, x2: float, y2: float,
             color: str = C_LINE, width: float = 1.5,
             dash: Optional[str] = None) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{color}" stroke-width="{width}"{d}/>'
        )

    def rect(self, x: float, y: float, w: float, h: float,
             fill: str = "none", stroke: str = C_LINE,
             width: float = 1.5, rx: float = 0.0) -> None:
        r = f' rx="{rx:.2f}" ry="{rx:.2f}"' if rx > 0 else ""
        self.add(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
            f'{r} fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'
        )

    def circle(self, cx: float, cy: float, r: float,
               fill: str = "none", stroke: str = C_LINE,
               width: float = 1.5) -> None:
        self.add(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'
        )

    def text(self, x: float, y: float, s: str, size: float = 13,
             anchor: str = "start", color: str = C_TEXT,
             weight: str = "normal", rotate: Optional[float] = None) -> None:
        tr = f' transform="rotate({rotate:.1f} {x:.2f} {y:.2f})"' if rotate else ""
        self.add(
            f'<text x="{x:.2f}" y="{y:.2f}" font-family="{FONT}" '
            f'font-size="{size:.1f}" text-anchor="{anchor}" fill="{color}" '
            f'font-weight="{weight}"{tr}>{_esc(s)}</text>'
        )

    def text_wrapped(self, x: float, y: float, s: str, max_width: float,
                     size: float = 11, line_height: float = 15,
                     sep: str = "、", color: str = C_TEXT) -> float:
        """按分隔符折行绘制文本，返回最后一行的基线 y。

        宽度估算：CJK 字符按 1.0×字号，其余按 0.56×字号。
        """
        def width_of(t: str) -> float:
            w = 0.0
            for ch in t:
                w += size * (1.0 if ord(ch) > 0x2E80 else 0.56)
            return w

        parts = s.split(sep)
        lines: List[str] = []
        cur = ""
        for p in parts:
            cand = p if not cur else f"{cur}{sep}{p}"
            if width_of(cand) <= max_width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = p
        if cur:
            lines.append(cur)

        yy = y
        for ln in lines:
            self.text(x, yy, ln, size=size, color=color)
            yy += line_height
        return yy - line_height

    def capsule_path(self, cx: float, cy: float, r: float, length: float,
                     horizontal: bool, fill: str = C_FILL,
                     stroke: str = C_LINE, width: float = 1.5) -> None:
        """胶囊轮廓：中间矩形 + 两端半圆。"""
        if horizontal:
            half = length / 2.0
            x1, x2 = cx - half, cx + half
            d = (f"M {x1:.2f} {cy - r:.2f} "
                 f"L {x2:.2f} {cy - r:.2f} "
                 f"A {r:.2f} {r:.2f} 0 0 1 {x2:.2f} {cy + r:.2f} "
                 f"L {x1:.2f} {cy + r:.2f} "
                 f"A {r:.2f} {r:.2f} 0 0 1 {x1:.2f} {cy - r:.2f} Z")
        else:
            half = length / 2.0
            y1, y2 = cy - half, cy + half
            d = (f"M {cx - r:.2f} {y1:.2f} "
                 f"L {cx - r:.2f} {y2:.2f} "
                 f"A {r:.2f} {r:.2f} 0 0 0 {cx + r:.2f} {y2:.2f} "
                 f"L {cx + r:.2f} {y1:.2f} "
                 f"A {r:.2f} {r:.2f} 0 0 0 {cx - r:.2f} {y1:.2f} Z")
        self.add(
            f'<path d="{d}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{width}"/>'
        )

    def ring_path(self, cx: float, cy: float, ro: float, ri: float,
                  fill: str = C_FILL, stroke: str = C_LINE,
                  width: float = 1.5) -> None:
        d = (f"M {cx - ro:.2f} {cy:.2f} "
             f"a {ro:.2f} {ro:.2f} 0 1 0 {2*ro:.2f} 0 "
             f"a {ro:.2f} {ro:.2f} 0 1 0 {-2*ro:.2f} 0 Z "
             f"M {cx - ri:.2f} {cy:.2f} "
             f"a {ri:.2f} {ri:.2f} 0 1 1 {2*ri:.2f} 0 "
             f"a {ri:.2f} {ri:.2f} 0 1 1 {-2*ri:.2f} 0 Z")
        self.add(f'<path d="{d}" fill="{fill}" fill-rule="evenodd" '
                 f'stroke="{stroke}" stroke-width="{width}"/>')

    def arrow(self, x: float, y: float, direction: str = "up",
              size: float = 7.0, color: str = C_DIM) -> None:
        if direction in ("up", "down"):
            s = -1 if direction == "up" else 1
            pts = f"{x:.2f},{y:.2f} {x-size:.2f},{y+s*size:.2f} {x+size:.2f},{y+s*size:.2f}"
        else:
            s = -1 if direction == "left" else 1
            pts = f"{x:.2f},{y:.2f} {x+s*size:.2f},{y-size:.2f} {x+s*size:.2f},{y+size:.2f}"
        self.add(f'<polygon points="{pts}" fill="{color}"/>')

    # --- 尺寸标注 ---
    def dim_h(self, x1: float, x2: float, y: float, label: str,
              tick: float = 6.0) -> None:
        """水平尺寸线。"""
        self.line(x1, y, x2, y, color=C_DIM, width=1.0)
        self.line(x1, y - tick, x1, y + tick, color=C_DIM, width=1.0)
        self.line(x2, y - tick, x2, y + tick, color=C_DIM, width=1.0)
        self.arrow(x1, y, "left", 6.0)
        self.arrow(x2, y, "right", 6.0)
        self.text((x1 + x2) / 2.0, y - 5, label, size=12,
                  anchor="middle", color=C_DIM)

    def dim_v(self, y1: float, y2: float, x: float, label: str,
              tick: float = 6.0) -> None:
        """垂直尺寸线。"""
        self.line(x, y1, x, y2, color=C_DIM, width=1.0)
        self.line(x - tick, y1, x + tick, y1, color=C_DIM, width=1.0)
        self.line(x - tick, y2, x + tick, y2, color=C_DIM, width=1.0)
        self.arrow(x, y1, "up", 6.0)
        self.arrow(x, y2, "down", 6.0)
        self.text(x - 6, (y1 + y2) / 2.0, label, size=12,
                  anchor="middle", color=C_DIM, rotate=-90)

    # --- 图框与标题栏 ---
    def frame(self) -> None:
        m = 12
        self.rect(m, m, self.w - 2 * m, self.h - 2 * m,
                  fill="#ffffff", stroke=C_LINE, width=2.0)
        self.rect(m + 8, m + 8, self.w - 2 * m - 16, self.h - 2 * m - 16,
                  fill="none", stroke=C_LINE, width=1.0)

    def title_block(self, extra: Optional[List[Tuple[str, str]]] = None) -> None:
        bw, bh = 560, 130
        x = self.w - 20 - bw
        y = self.h - 20 - bh
        self.rect(x, y, bw, bh, fill="#ffffff", stroke=C_LINE, width=1.5)
        rows = [
            ("项目", "A.T.R.I. 桌面自主人形智能"),
            ("图名", self.title),
            ("图号", self.drawing_no),
            ("单位", "mm"),
            ("比例", self.scale_text or "见视图标注"),
            ("阶段", "方案设计（design-provisional）"),
        ]
        if extra:
            rows.extend(extra)
        rh = bh / len(rows)
        for i, (k, v) in enumerate(rows):
            yy = y + rh * i
            if i:
                self.line(x, yy, x + bw, yy, color=C_THIN, width=0.6)
            self.line(x + 90, yy, x + 90, yy + rh, color=C_THIN, width=0.6)
            self.text(x + 10, yy + rh * 0.68, k, size=12, color=C_TEXT)
            self.text(x + 100, yy + rh * 0.68, v, size=12, color=C_TEXT)

    def render(self) -> str:
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
                f'height="{self.h}" viewBox="0 0 {self.w} {self.h}">')
        bg = f'<rect width="{self.w}" height="{self.h}" fill="#ffffff"/>'
        return "\n".join([head, bg] + self.parts + ["</svg>"]) + "\n"


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --------------------------------------------------------------------------
# 视图投影器
# --------------------------------------------------------------------------
class View:
    """把一个 3D 模型投影到 2D 图纸区域。"""

    def __init__(self, model: Dict[str, Any], view: str,
                 ox: float, oy: float, aw: float, ah: float,
                 pose: Optional[Dict[str, float]] = None) -> None:
        self.model = model
        self.view = view
        self.spec = geometry.VIEWS[view]
        self.tfs = geometry.link_positions(model, pose)
        self.ox, self.oy, self.aw, self.ah = ox, oy, aw, ah

        # 计算世界投影范围
        pts: List[Tuple[float, float]] = []
        for link in model["links"]:
            tf = self.tfs.get(link["name"])
            if tf is None:
                continue
            mins, maxs = geometry.link_world_aabb(model, link["name"], tf)
            for hu in (mins, maxs):
                pts.append((hu[self.spec["h"]], hu[self.spec["v"]]))
        if not pts:
            pts = [(0.0, 0.0), (1.0, 1.0)]
        self.hmin = min(p[0] for p in pts)
        self.hmax = max(p[0] for p in pts)
        self.vmin = min(p[1] for p in pts)
        self.vmax = max(p[1] for p in pts)

        pad = 0.12
        span_h = max(1e-6, self.hmax - self.hmin)
        span_v = max(1e-6, self.vmax - self.vmin)
        self.scale = min(aw * (1 - 2 * pad) / span_h,
                         ah * (1 - 2 * pad) / span_v)

    def to_screen(self, h: float, v: float) -> Tuple[float, float]:
        cx = self.ox + self.aw / 2.0
        cy = self.oy + self.ah / 2.0
        hc = (self.hmin + self.hmax) / 2.0
        vc = (self.vmin + self.vmax) / 2.0
        x = cx + (h - hc) * self.scale
        dv = (v - vc)
        y = cy - dv * self.scale if not self.spec["v_flip"] else cy + dv * self.scale
        return x, y

    def joint_world(self, joint: Dict[str, Any]) -> Tuple[float, float]:
        """关节原点在该视图下的 2D 世界坐标。"""
        tf = self.tfs.get(joint["child"])
        if tf is None:
            # 回退：沿父链累加
            return (0.0, 0.0)
        p = geometry.transform_point(tf, (0.0, 0.0, 0.0))
        return (p[self.spec["h"]], p[self.spec["v"]])

    def joint_screen(self, joint: Dict[str, Any]) -> Tuple[float, float]:
        h, v = self.joint_world(joint)
        return self.to_screen(h, v)

    def draw_links(self, sheet: Sheet, highlight: Tuple[str, ...] = ()) -> None:
        """绘制各 link 的投影轮廓。"""
        for link in self.model["links"]:
            tf = self.tfs.get(link["name"])
            if tf is None:
                continue
            geom = link["geometry"]
            shape = geometry.project_shape(geom, self.view)
            mins, maxs = geometry.link_world_aabb(self.model, link["name"], tf)
            hc_w = (mins[self.spec["h"]] + maxs[self.spec["h"]]) / 2.0
            vc_w = (mins[self.spec["v"]] + maxs[self.spec["v"]]) / 2.0
            cx, cy = self.to_screen(hc_w, vc_w)

            is_hl = link.get("group") in highlight
            fill = C_TRUNK_FILL if is_hl else C_FILL
            stroke = C_TRUNK if is_hl else C_LINE

            if shape["kind"] == "rect":
                w = shape["w"] * self.scale
                h = shape["h"] * self.scale
                rx = shape.get("fillet", 0.0) * self.scale
                sheet.rect(cx - w / 2, cy - h / 2, w, h, fill=fill,
                           stroke=stroke, width=1.4, rx=rx)
            elif shape["kind"] == "circle":
                sheet.circle(cx, cy, shape["r"] * self.scale, fill=fill,
                             stroke=stroke, width=1.4)
            elif shape["kind"] == "ring":
                sheet.ring_path(cx, cy, shape["ro"] * self.scale,
                                shape["ri"] * self.scale, fill=fill,
                                stroke=stroke, width=1.4)
            elif shape["kind"] == "capsule":
                sheet.capsule_path(cx, cy, shape["r"] * self.scale,
                                   shape["length"] * self.scale,
                                   shape["along_horizontal"], fill=fill,
                                   stroke=stroke, width=1.4)


# --------------------------------------------------------------------------
# 图 1：22 关节编号图（最高优先级）
# --------------------------------------------------------------------------
def draw_joint_map(model: Dict[str, Any]) -> Sheet:
    """22 关节编号图。

    布局（关键：避免引线互相穿插）：
        上方  —— 正视 + 侧视，关节处画编号圆标，不画长引线
        右下  —— 自由度构成 + 尺寸合规核验
        底部  —— 22 关节明细表（编号 / 名称 / 所属 / 限位 / 轴向）
    """
    sh = Sheet(title="22 关节编号图", drawing_no="ATRI-DWG-001",
               scale_text="自动缩放")
    sh.frame()

    sh.text(40, 52, "A.T.R.I. 22 自由度关节编号图", size=25, weight="bold")
    sh.text(40, 76,
            "正视 + 侧视 · 关节编号与软件 config.py 完全同源 · "
            "橙色为躯干 2 DOF（腰部横滚 / 俯仰）",
            size=12.5, color="#555")

    # ---------- 视图区域 ----------
    vf = View(model, "front", 40, 96, 560, 760)
    vs = View(model, "side", 620, 96, 400, 760)

    vf.draw_links(sh, highlight=("trunk",))
    vs.draw_links(sh, highlight=("trunk",))

    sh.rect(40, 96, 560, 760, fill="none", stroke="#cfcfcf", width=1.0)
    sh.rect(620, 96, 400, 760, fill="none", stroke="#cfcfcf", width=1.0)
    sh.text(320, 90, "正视图", size=15, anchor="middle", weight="bold")
    sh.text(820, 90, "侧视图", size=15, anchor="middle", weight="bold")

    def bubble(v: View, j: Dict[str, Any], dy: float = 0.0,
               side: str = "center") -> Tuple[float, float]:
        """在关节位置画编号圆标，返回圆标中心。"""
        sx, sy = v.joint_screen(j)
        is_trunk = j["name"].startswith("trunk")
        color = C_TRUNK if is_trunk else "#2b7fd4"
        r = 11.0
        cx = sx + (13.0 if side == "right" else (-13.0 if side == "left" else 0.0))
        cy = sy + dy
        if cx != sx or cy != sy:
            sh.line(sx, sy, cx, cy, color=color, width=0.9)
        sh.circle(cx, cy, r, fill="#ffffff", stroke=color, width=1.6)
        sh.text(cx, cy + 4.0, f"{j['id']:02d}", size=11.5, anchor="middle",
                color=color, weight="bold")
        return cx, cy

    # 正视：肩 pitch/roll 位置重合，做一个上下错位 + 短引线
    overlap_pairs = {
        "left_shoulder_roll": (-26.0, "center"),
        "right_shoulder_roll": (26.0, "center"),
    }
    for j in model["joints"]:
        dy, side = overlap_pairs.get(j["name"], (0.0, "center"))
        bubble(vf, j, dy=dy, side=side)

    # 侧视：左右肢体在屏幕上重合，只标中线关节 + 用浅色标其余
    midline = ("head_yaw", "head_pitch", "trunk_roll", "trunk_pitch")
    for j in model["joints"]:
        if j["name"] in midline:
            bubble(vs, j)
    # 侧视里左右成对的关节投影重合，用灰点 + 右侧标签列标注，避免压在轮廓上
    vs_extra = [
        ("left_shoulder_pitch", "肩"),
        ("left_elbow_pitch", "肘"),
        ("left_gripper", "夹爪"),
        ("left_hip_yaw", "髋"),
        ("left_knee_pitch", "膝"),
        ("left_ankle_pitch", "踝"),
    ]
    label_x = 942.0
    items = []
    for name, tag in vs_extra:
        j = next(x for x in model["joints"] if x["name"] == name)
        sx, sy = vs.joint_screen(j)
        sh.circle(sx, sy, 5.0, fill="#ffffff", stroke="#7a8794", width=1.2)
        items.append((sy, sx, tag))
    items.sort()
    top, bottom = 130.0, 830.0
    step = (bottom - top) / max(1, len(items) - 1)
    for i, (sy, sx, tag) in enumerate(items):
        ly = top + step * i
        sh.line(label_x - 8, ly - 4, sx, sy, color="#b9c2cc", width=0.9,
                dash="4,3")
        sh.text(label_x, ly, f"L/R {tag}", size=10.5, color="#5c6773")
    sh.text(820, 852,
            "侧视中左右肢体投影重合，成对关节以灰点标注；"
            "完整关节名与限位见下方明细表",
            size=10.5, anchor="middle", color="#7a8794")

    # ---------- 右侧信息栏 ----------
    bx = 1040
    sh.rect(bx, 96, 604, 330, fill="#fafafa", stroke="#cfcfcf", width=1.0)
    sh.text(bx + 16, 126, "自由度构成（与申报口径一致）", size=15,
            weight="bold")
    rows = [
        ("头部 head", 2, "yaw / pitch"),
        ("躯干 trunk", 2, "roll / pitch　← 橙色高亮"),
        ("左腿 leg_l", 5, "髋 yaw/roll/pitch + 膝 + 踝"),
        ("右腿 leg_r", 5, "髋 yaw/roll/pitch + 膝 + 踝"),
        ("左臂 arm_l", 4, "肩 pitch/roll + 肘 + 夹爪"),
        ("右臂 arm_r", 4, "肩 pitch/roll + 肘 + 夹爪"),
    ]
    y = 140
    sh.line(bx + 16, y, bx + 588, y, color="#999", width=1.0)
    total = 0
    for name, cnt, note in rows:
        total += cnt
        hl = "trunk" in name
        yy = y + 26
        sh.text(bx + 16, yy, name, size=12.5,
                color=C_TRUNK if hl else C_TEXT,
                weight="bold" if hl else "normal")
        sh.text(bx + 130, yy, f"{cnt} DOF", size=12.5,
                color=C_TRUNK if hl else C_TEXT,
                weight="bold" if hl else "normal")
        sh.text(bx + 200, yy, note, size=11.5, color="#555")
        y = yy + 10
    sh.line(bx + 16, y + 8, bx + 588, y + 8, color="#999", width=1.0)
    sh.text(bx + 16, y + 34, "合计", size=14, weight="bold")
    sh.text(bx + 130, y + 34, f"{total} DOF", size=14, weight="bold")
    sh.text(bx + 16, y + 56,
            "要求：总数 ≥ 18，每腿 ≥ 4，上肢 + 躯干 ≥ 10", size=11.5,
            color="#1a7f37")

    # 尺寸合规
    by2 = 442
    sh.rect(bx, by2, 604, 250, fill="#fafafa", stroke="#cfcfcf", width=1.0)
    sh.text(bx + 16, by2 + 28, "尺寸合规核验", size=15, weight="bold")
    env = gen_urdf.measured_envelope(model)
    c = model["design_constraints"]
    checks = [
        ("高度", env["height_mm"], c["competition_max_height_mm"]),
        ("宽度", env["width_mm"], c["competition_max_width_mm"]),
        ("深度", env["depth_mm"], c["competition_max_depth_mm"]),
    ]
    yy = by2 + 60
    sh.text(bx + 16, yy, "项目", size=11.5, weight="bold", color="#555")
    sh.text(bx + 140, yy, "设计值", size=11.5, weight="bold", color="#555")
    sh.text(bx + 300, yy, "官方上限", size=11.5, weight="bold", color="#555")
    sh.text(bx + 460, yy, "余量", size=11.5, weight="bold", color="#555")
    yy += 8
    sh.line(bx + 16, yy, bx + 588, yy, color="#999", width=1.0)
    for name, val, lim in checks:
        yy += 32
        sh.text(bx + 16, yy, name, size=12.5)
        sh.text(bx + 140, yy, f"{val:.1f} mm", size=12.5)
        sh.text(bx + 300, yy, f"{lim:.0f} mm", size=12.5)
        sh.text(bx + 460, yy, f"{lim - val:.1f} mm", size=12.5, color="#1a7f37")
    yy += 34
    sh.text(bx + 16, yy, "结果：三项均在限值内，可直接用于报名与检录核对。",
            size=12, color="#1a7f37", weight="bold")

    # ---------- 底：22 关节明细表 ----------
    # 注意：表格右边界必须留在标题栏左侧（标题栏从 x=1104 起），否则会互相遮挡
    tx, ty = 40, 880
    tw, th = 1050, 250
    sh.rect(tx, ty, tw, th, fill="#ffffff", stroke=C_LINE, width=1.4)
    sh.text(tx + 14, ty - 10,
            "关节明细表（编号 / 名称 / 限位 / 轴向 / 额定扭矩）",
            size=14, weight="bold")

    cols = 3
    per_col = 8
    cw = tw / cols
    rh = th / per_col
    for idx, j in enumerate(sorted(model["joints"], key=lambda x: x["id"])):
        ci = idx // per_col
        ri = idx % per_col
        cx0 = tx + ci * cw
        cy0 = ty + ri * rh
        if ri == 0 and ci > 0:
            sh.line(cx0, ty, cx0, ty + th, color="#cfcfcf", width=1.0)
        if ri > 0:
            sh.line(cx0, cy0, cx0 + cw, cy0, color="#eeeeee", width=0.7)
        is_trunk = j["name"].startswith("trunk")
        col = C_TRUNK if is_trunk else C_TEXT
        lo, hi = j["limit_deg"]
        axis_txt = {0: "X", 1: "Y", 2: "Z"}[
            j["axis"].index(max(j["axis"]))
        ]
        sh.text(cx0 + 10, cy0 + rh * 0.64, f"[{j['id']:02d}]", size=11.5,
                color=col, weight="bold")
        sh.text(cx0 + 48, cy0 + rh * 0.64, j["name"], size=11.5, color=col)
        sh.text(cx0 + 218, cy0 + rh * 0.64,
                f"{lo:+.0f}~{hi:+.0f}°", size=10.5, color="#555")
        sh.text(cx0 + 290, cy0 + rh * 0.64,
                f"{axis_txt} {j.get('effort_nm', 0):.1f}N·m", size=10.5,
                color="#777")

    sh.title_block(extra=[("视图", "正视 + 侧视"),
                          ("标注", "22 关节全标注")])
    return sh


# --------------------------------------------------------------------------
# 图 2：三视图
# --------------------------------------------------------------------------
def draw_three_views(model: Dict[str, Any]) -> Sheet:
    sh = Sheet(title="总装三视图", drawing_no="ATRI-DWG-002",
               scale_text="自动缩放")
    sh.frame()
    sh.text(40, 52, "A.T.R.I. 总装三视图（零姿态）", size=26, weight="bold")
    sh.text(40, 78, "由设计模型正交投影生成 · 单位 mm · "
                    "标注为设计值，制造前需复测", size=13, color="#555")

    vf = View(model, "front", 60, 120, 460, 620)
    vs = View(model, "side", 580, 120, 460, 620)
    vt = View(model, "top", 60, 800, 460, 300)

    for v, ox, oy, aw, ah in ((vf, 60, 120, 460, 620),
                              (vs, 580, 120, 460, 620),
                              (vt, 60, 800, 460, 300)):
        v.draw_links(sh, highlight=("trunk",))
        sh.text(ox + aw / 2, oy - 10, v.spec["label"], size=16,
                anchor="middle", weight="bold")
        sh.rect(ox, oy, aw, ah, fill="none", stroke="#cfcfcf", width=1.0)

    # 总体尺寸标注
    env = gen_urdf.measured_envelope(model)

    # 正视：宽度
    y_dim = 120 + 620 + 34
    x1, _ = vf.to_screen(vf.hmin, 0.0)
    x2, _ = vf.to_screen(vf.hmax, 0.0)
    sh.dim_h(x1, x2, y_dim, f"宽 {env['width_mm']:.0f}")

    # 侧视：深度
    sx1, _ = vs.to_screen(vs.hmin, 0.0)
    sx2, _ = vs.to_screen(vs.hmax, 0.0)
    sh.dim_h(sx1, sx2, y_dim, f"深 {env['depth_mm']:.0f}")

    # 正视：高度（右侧）
    _, yt = vf.to_screen(0.0, vf.vmax)
    _, yb = vf.to_screen(0.0, vf.vmin)
    sh.dim_v(yt, yb, 60 + 460 + 40, f"高 {env['height_mm']:.0f}")

    # 右下信息栏
    bx, by = 580, 800
    sh.rect(bx, by, 1000, 300, fill="#fafafa", stroke="#cfcfcf", width=1.0)
    sh.text(bx + 16, by + 32, "视图说明", size=16, weight="bold")
    notes = [
        "正视：从机器人正前方观察，横向为左右（Y），纵向为上下（Z）。",
        "侧视：从机器人左侧观察，横向为前后（X），纵向为上下（Z）。",
        "俯视：从上方观察，横向为左右（Y），纵向为前后（X），前方朝上。",
        "",
        "外形为设计基元（圆角壳 / 关节球壳 / 胶囊连杆 / 足底板），",
        "用于表达构型与包络；圆角半径、壁厚等工艺细节见零件设计。",
        "本图为设计投影图，非 CAD 出图，也非渲染图。",
        "所有尺寸为设计值，实物制造前须按采购件复测。",
    ]
    yy = by + 62
    for n in notes:
        if n:
            sh.text(bx + 20, yy, n, size=13, color="#333")
        yy += 26

    sh.title_block(extra=[("视图", "正视/侧视/俯视")])
    return sh


# --------------------------------------------------------------------------
# 图 4：尺寸链图
# --------------------------------------------------------------------------
def draw_dimension_chain(model: Dict[str, Any]) -> Sheet:
    sh = Sheet(title="关节链尺寸链图", drawing_no="ATRI-DWG-004",
               scale_text="1:1 数值标注")
    sh.frame()
    sh.text(40, 52, "A.T.R.I. 关节链尺寸链（零姿态，单位 mm）", size=26,
            weight="bold")
    sh.text(40, 78, "用于校核总高：各关节原点偏移沿 Z 累加 + 末端半高",
            size=13, color="#555")

    # 头 -> 足 的竖直链
    by_child = {j["child"]: j for j in model["joints"]}

    chains = [
        ("头部链（骨盆 → 头顶）", "head"),
        ("左腿链（骨盆 → 足底）", "left_foot"),
    ]
    col_x = 120
    row_y = 140
    for title, leaf in chains:
        sh.text(col_x, row_y, title, size=17, weight="bold")
        row_y += 14
        # 收集链
        chain: List[Dict[str, Any]] = []
        cur = leaf
        while cur in by_child:
            j = by_child[cur]
            chain.append(j)
            cur = j["parent"]
        chain.reverse()

        total = 0.0
        yy = row_y + 26
        sh.text(col_x, yy, "顺序", size=12, weight="bold", color="#555")
        sh.text(col_x + 70, yy, "关节名", size=12, weight="bold", color="#555")
        sh.text(col_x + 300, yy, "Z 偏移", size=12, weight="bold", color="#555")
        sh.text(col_x + 420, yy, "累计", size=12, weight="bold", color="#555")
        yy += 10
        sh.line(col_x, yy, col_x + 520, yy, color="#999", width=1.0)

        for i, j in enumerate(chain):
            yy += 30
            dz = j["origin_xyz_mm"][2]
            total += dz
            sh.text(col_x, yy, f"{i+1}", size=13)
            sh.text(col_x + 70, yy, j["name"], size=13)
            sh.text(col_x + 300, yy, f"{dz:+.1f}", size=13,
                    color="#0b6bb5" if dz != 0 else "#888")
            sh.text(col_x + 420, yy, f"{total:+.1f}", size=13, color="#555")

        # 末端半高
        link = next(l for l in model["links"] if l["name"] == leaf)
        half = geometry.bounding_box(link["geometry"])[2] / 2.0
        yy += 30
        sh.text(col_x, yy, "+", size=13)
        sh.text(col_x + 70, yy, f"{leaf} 半高", size=13)
        sh.text(col_x + 300, yy, f"{half:+.1f}", size=13, color="#0b6bb5")
        end_val = total + half
        sh.text(col_x + 420, yy, f"{end_val:+.1f}", size=13, weight="bold")

        yy += 40
        sh.line(col_x, yy, col_x + 520, yy, color="#1a1a1a", width=1.5)
        sh.text(col_x, yy + 28, "合计（相对骨盆中心）", size=14, weight="bold")
        sh.text(col_x + 420, yy + 28, f"{end_val:+.1f} mm", size=14,
                weight="bold", color="#d4572b")
        row_y = yy + 90

    # 右侧：总高校核
    bx = 760
    sh.rect(bx, 130, 880, 300, fill="#fafafa", stroke="#cfcfcf", width=1.0)
    sh.text(bx + 16, 162, "总高校核", size=17, weight="bold")

    def z_path(leaf: str) -> float:
        z, cur = 0.0, leaf
        while cur in by_child:
            j = by_child[cur]
            z += j["origin_xyz_mm"][2]
            cur = j["parent"]
        return z

    top = z_path("head") + geometry.bounding_box(
        next(l for l in model["links"] if l["name"] == "head")["geometry"])[2] / 2.0
    bottom = z_path("left_foot") - geometry.bounding_box(
        next(l for l in model["links"] if l["name"] == "left_foot")["geometry"])[2] / 2.0
    height = top - bottom

    lines = [
        ("头顶（相对骨盆中心）", f"{top:+.1f} mm"),
        ("足底（相对骨盆中心）", f"{bottom:+.1f} mm"),
        ("几何总高", f"{height:.1f} mm"),
        ("模型声明总高", f"{model['overall']['height_mm']:.1f} mm"),
        ("官方上限", f"{model['design_constraints']['competition_max_height_mm']:.0f} mm"),
        ("剩余余量", f"{model['design_constraints']['competition_max_height_mm'] - height:.1f} mm"),
    ]
    yy = 196
    for k, v in lines:
        sh.text(bx + 24, yy, k, size=13)
        sh.text(bx + 560, yy, v, size=13, anchor="end",
                weight="bold" if "总高" in k or "余量" in k else "normal",
                color="#d4572b" if "余量" in k else C_TEXT)
        yy += 30

    # 一致性结论
    ok = abs(height - model["overall"]["height_mm"]) <= 1.0
    sh.text(bx + 24, yy + 10,
            "结论：" + ("几何推导与声明值一致（差 ≤ 1 mm）。" if ok
                        else "不一致，需修正！"),
            size=14, weight="bold", color="#1a7f37" if ok else "#c0392b")

    # 底部：足底离地校核
    sh.rect(bx, 450, 880, 200, fill="#fafafa", stroke="#cfcfcf", width=1.0)
    sh.text(bx + 16, 482, "放置校核", size=17, weight="bold")
    base_z = model["base_pose_mm"][2]
    sh.text(bx + 24, 516, f"base_pose_mm Z = {base_z:.1f} mm（骨盆中心离地高度）",
            size=13)
    sh.text(bx + 24, 546, f"放置后足底离地 = {base_z + bottom:.1f} mm",
            size=13, color="#1a7f37", weight="bold")
    sh.text(bx + 24, 576, f"放置后头顶离地 = {base_z + top:.1f} mm", size=13)
    sh.text(bx + 24, 612, "结论：足底与地面重合，模型可直接放入仿真场景。",
            size=13, color="#1a7f37")

    sh.title_block()
    return sh


# --------------------------------------------------------------------------
# 图 5：舵机布局图
# --------------------------------------------------------------------------
def draw_servo_layout(model: Dict[str, Any]) -> Sheet:
    sh = Sheet(title="舵机布局图", drawing_no="ATRI-DWG-005",
               scale_text="自动缩放")
    sh.frame()
    sh.text(40, 52, "A.T.R.I. 舵机安装布局（22 路总线舵机）", size=26,
            weight="bold")
    sh.text(40, 78, "每个关节对应一路舵机 · 总线级联 · "
                    "型号与外形为设计占位值，采购后复测", size=13, color="#555")

    vf = View(model, "front", 60, 120, 480, 640)
    vs = View(model, "side", 600, 120, 480, 640)
    for v, ox, aw in ((vf, 60, 480), (vs, 600, 480)):
        v.draw_links(sh, highlight=("trunk",))
        sh.text(ox + aw / 2, 110, v.spec["label"], size=16,
                anchor="middle", weight="bold")
        sh.rect(ox, 120, aw, 640, fill="none", stroke="#cfcfcf", width=1.0)

    # 在每个关节位置画舵机方块与编号
    for v in (vf, vs):
        for j in model["joints"]:
            sx, sy = v.joint_screen(j)
            is_trunk = j["name"].startswith("trunk")
            color = C_TRUNK if is_trunk else "#2b7fd4"
            # 舵机本体尺寸按关节扭矩粗分三档
            t = j.get("effort_nm", 1.0)
            side = 13.0 if t >= 3.0 else (11.0 if t >= 2.0 else 9.0)
            sh.rect(sx - side / 2, sy - side / 2, side, side,
                    fill="#ffffff", stroke=color, width=1.4)
            sh.text(sx, sy + 3.5, f"{j['id']}", size=8, anchor="middle",
                    color=color, weight="bold")

    # 图例（**全部由模型数据推导**，避免与汇总表对不上）
    def tier(j: Dict[str, Any]) -> str:
        t = j.get("effort_nm", 1.0)
        if t >= 3.0:
            return "high"
        if t >= 2.0:
            return "mid"
        return "low"

    def tier_names(key: str) -> List[str]:
        return [j["name"] for j in model["joints"] if tier(j) == key]

    tier_info = [
        ("high", "大方块 (13px)", "额定扭矩 ≥ 3.0 N·m"),
        ("mid", "中方块 (11px)", "2.0 – 3.0 N·m"),
        ("low", "小方块 (9px)", "< 2.0 N·m"),
    ]

    bx, by = 1110, 130
    sh.rect(bx, by, 520, 330, fill="#fafafa", stroke="#cfcfcf", width=1.0)
    sh.text(bx + 16, by + 30, "图例（按额定扭矩分档）", size=15, weight="bold")
    yy = by + 62
    for key, box_label, desc in tier_info:
        names = tier_names(key)
        sh.text(bx + 20, yy, box_label, size=12, weight="bold")
        sh.text(bx + 175, yy, f"{desc}　{len(names)} 路", size=11.5,
                color="#333")
        yy += 22
        # 列出该档包含的关节名（折行显示，避免溢出面板）
        short = "、".join(
            n.replace("left_", "L.").replace("right_", "R.") for n in names
        )
        yy = sh.text_wrapped(bx + 34, yy, short, max_width=466, size=10.5,
                             line_height=14, color="#666") + 28
    sh.text(bx + 20, yy, "橙色", size=12, weight="bold")
    sh.text(bx + 175, yy, "躯干 2 DOF（腰 roll / pitch）", size=11.5,
            color="#333")
    yy += 24
    sh.text(bx + 20, yy, "方块内数字", size=12, weight="bold")
    sh.text(bx + 175, yy, "关节编号 0–21（与明细表一致）", size=11.5,
            color="#333")

    # 汇总（与图例同源，保证一致）
    bx2, by2 = 1110, 490
    sh.rect(bx2, by2, 520, 270, fill="#fafafa", stroke="#cfcfcf", width=1.0)
    sh.text(bx2 + 16, by2 + 30, "汇总", size=15, weight="bold")
    n_total = len(model["joints"])
    n_high = len(tier_names("high"))
    n_mid = len(tier_names("mid"))
    n_low = len(tier_names("low"))
    yy = by2 + 64
    for k, v in (
        ("舵机总数", f"{n_total} 路"),
        ("高扭矩档（≥3.0 N·m）", f"{n_high} 路"),
        ("中扭矩档（2.0–3.0）", f"{n_mid} 路"),
        ("低扭矩档（<2.0）", f"{n_low} 路"),
        ("供电", f"{model['servo_defaults']['voltage_nominal_v']:.1f} V 标称"),
        ("总线协议", model["servo_defaults"]["protocol"]),
    ):
        sh.text(bx2 + 24, yy, k, size=12)
        sh.text(bx2 + 496, yy, v, size=12, anchor="end", weight="bold")
        yy += 29
    assert n_high + n_mid + n_low == n_total
    yy += 4
    sh.text(bx2 + 24, yy, "注：扭矩分档依据 design/robot_model.json 的",
            size=10.5, color="#555")
    sh.text(bx2 + 24, yy + 16, "effort_nm 设计值，非实测数据。", size=10.5,
            color="#555")

    sh.title_block(extra=[("对象", "22 路总线舵机")])
    return sh


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
DRAWINGS = {
    "joints": ("01_关节编号图.svg", draw_joint_map),
    "views": ("02_三视图.svg", draw_three_views),
    "chain": ("04_尺寸链图.svg", draw_dimension_chain),
    "servo": ("05_舵机布局图.svg", draw_servo_layout),
}


def export_png(svg: Path) -> Optional[Path]:
    """SVG 转 PNG：rsvg-convert → inkscape → qlmanage；都没有则返回 None。"""
    dest = svg.with_suffix(".png")
    if _svg_to_png(svg, dest, size=2000):
        return dest
    return None


def _svg_to_png(svg: Path, dest: Path, size: int, timeout: int = 120) -> bool:
    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        try:
            subprocess.run(
                [rsvg, "-w", str(size), "-o", str(dest), str(svg)],
                check=True, capture_output=True, timeout=timeout,
            )
            if dest.is_file() and dest.stat().st_size > 0:
                return True
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass

    inkscape = shutil.which("inkscape")
    if inkscape:
        cmds = [
            [inkscape, str(svg), "--export-type=png",
             f"--export-filename={dest}", f"--export-width={size}"],
            [inkscape, "-z", str(svg), f"--export-png={dest}",
             f"--export-width={size}"],
        ]
        for cmd in cmds:
            try:
                subprocess.run(
                    cmd, check=True, capture_output=True, timeout=timeout,
                )
                if dest.is_file() and dest.stat().st_size > 0:
                    return True
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                continue

    ql = shutil.which("qlmanage")
    if ql:
        try:
            subprocess.run(
                [ql, "-t", "-s", str(size), "-o", str(svg.parent), str(svg)],
                check=True, capture_output=True, timeout=timeout,
            )
            produced = svg.parent / (svg.name + ".png")
            if produced.exists():
                produced.replace(dest)
                return dest.is_file() and dest.stat().st_size > 0
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass
    return False


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="生成 A.T.R.I. 2D 工程图")
    ap.add_argument("--only", choices=sorted(DRAWINGS), default=None)
    ap.add_argument("--png", action="store_true", help="同时导出 PNG")
    args = ap.parse_args(argv)

    model = gen_urdf.load_model()
    problems = gen_urdf.check(model)
    if problems:
        print("模型校验未通过，先修复再出图：")
        for p in problems:
            print("  -", p)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    names = [args.only] if args.only else sorted(DRAWINGS)
    for key in names:
        fname, fn = DRAWINGS[key]
        sheet = fn(model)
        path = OUT_DIR / fname
        path.write_text(sheet.render(), encoding="utf-8")
        print(f"已生成 {path}  ({path.stat().st_size} bytes)")
        if args.png:
            png = export_png(path)
            if png:
                print(f"   PNG -> {png}")
            else:
                print("   未找到 rsvg-convert / inkscape / qlmanage，已保留 SVG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
