"""A 路线 SVG 工程图（示意图 + 标注，激光以 DXF 为准）。"""
from __future__ import annotations

from typing import Dict, List

from .plates import Plate, all_plates, bbox
from .profile import JOINTS, SERVO, envelope_mm, standing_height_mm
from .verify import report as eng_report

FONT = "Microsoft YaHei, PingFang SC, Noto Sans SC, sans-serif"


class Sheet:
    def __init__(self, w: int, h: int, title: str, no: str) -> None:
        self.w, self.h, self.title, self.no = w, h, title, no
        self.parts: List[str] = []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def line(self, x1, y1, x2, y2, c="#1a1a1a", w=1.2, dash=None) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{c}" stroke-width="{w}"{d}/>'
        )

    def rect(self, x, y, w, h, fill="none", stroke="#1a1a1a", sw=1.0) -> None:
        self.add(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
        )

    def circle(self, x, y, r, fill="none", stroke="#1a1a1a", sw=1.0) -> None:
        self.add(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>'
        )

    def text(self, x, y, s, size=12, fill="#1a1a1a", anchor="start", weight="normal") -> None:
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}" font-family="{FONT}">{s}</text>'
        )

    def poly(self, pts, fill="none", stroke="#1a1a1a", sw=1.2) -> None:
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.add(f'<polygon points="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def dumps(self) -> str:
        self.rect(18, 18, self.w - 36, self.h - 36, stroke="#111", sw=1.6)
        self.rect(18, self.h - 70, self.w - 36, 52, fill="#f4f6f8", stroke="#111", sw=1.0)
        self.text(32, self.h - 42, "HPIline / ATRI-v2  A路线  铝夹层+PETG", 13, weight="bold")
        self.text(32, self.h - 24, f"{self.no}    {self.title}    单位 mm    2026-09-12    未过 G1 不得投产", 11)
        self.text(self.w - 40, self.h - 24, "比例 示意", 11, anchor="end")
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}">\n{body}\n</svg>\n'
        )


def _title(sh: Sheet) -> None:
    sh.text(40, 48, sh.title, 22, weight="bold")
    sh.text(40, 70, sh.no, 13, fill="#444")


def cover() -> str:
    sh = Sheet(1400, 990, "总装示意图（零位）", "ATRI-v2-00")
    _title(sh)
    env = envelope_mm()
    r = eng_report()
    # 正视火柴人
    cx, gy, sc = 280, 820, 1.7
    h = standing_height_mm()
    top = gy - h * sc
    sh.line(cx, gy, cx, top + 40 * sc, "#222", 3)
    sh.rect(cx - 35 * sc, gy - 22 * sc, 70 * sc, 10 * sc, fill="#cfd8dc")  # feet
    sh.rect(cx - 8 * sc, gy - (22 + 78) * sc, 16 * sc, 78 * sc, fill="#90a4ae")
    sh.rect(cx - 8 * sc, gy - (22 + 78 + 78) * sc, 16 * sc, 78 * sc, fill="#78909c")
    sh.rect(cx - 40 * sc, gy - (22 + 78 + 78 + 32 + 36) * sc, 80 * sc, 72 * sc, fill="#546e7a")
    sh.circle(cx, top + 24 * sc, 22 * sc, fill="#eceff1")
    sh.line(cx - 75 * sc, gy - 220 * sc, cx - 20 * sc, gy - 280 * sc, "#546e7a", 6)
    sh.line(cx + 75 * sc, gy - 220 * sc, cx + 20 * sc, gy - 280 * sc, "#546e7a", 6)
    sh.text(cx, gy + 24, "正视", 14, anchor="middle")
    sh.text(40, 110, f"包络 {env['height_mm']:.0f} × {env['width_mm']:.0f} × {env['depth_mm']:.0f} mm", 16)
    sh.text(40, 132, f"20 DOF  ·  上肢躯干 10（不含头）  ·  设计质量 {r['mass_design_g']:.0f} g", 14)
    notes = [
        "承力：1.5 mm 6061 平板夹层，舵机壳体当连杆。禁止 MG995 耳孔支架。",
        "安装：端面 PCD Φ14 / 4×M2.5（9.90 方阵）。副轴 MF106ZZ。",
        "外观：PETG 两色壳 + 舱盖；膝/肘露出铝边。TPU 鞋底。",
        f"踝慢步 {r['ankle_walk_nm']:.2f} N·m（{r['ankle_walk_util']*100:.0f}% 额定）。站立保持仍超额定，见工程验证。",
        "软件仍为 22 DOF，直到 G4 转向门禁关闭。",
    ]
    for i, t in enumerate(notes):
        sh.text(520, 200 + i * 28, t, 14)
    sh.rect(520, 360, 820, 480, fill="#fafafa", stroke="#90a4ae")
    sh.text(540, 390, "本周只做", 16, weight="bold")
    for i, t in enumerate((
        "1. 买 1 只 STS3215-C018 12V + 官方 25T 盘 + 1 套面安装板，量孔。",
        "2. 锁 G0 购物车（12V SKU 截图）。retail ¥109×20 超预算。",
        "3. 电话/邮件问赛方 G3（头、夹爪、量法、换电）。",
        "4. 发 DXF 给激光店出 1.5 mm 样板，先做单腿骡机。",
        "5. 禁止一次下 20 只舵机。",
    )):
        sh.text(540, 430 + i * 32, t, 14)
    return sh.dumps()


def joints() -> str:
    sh = Sheet(1400, 990, "关节编号（20 DOF）", "ATRI-v2-01")
    _title(sh)
    groups = {
        "head": ("头", "#6a1b9a"),
        "trunk": ("躯干", "#d4572b"),
        "leg_l": ("左腿", "#1565c0"),
        "leg_r": ("右腿", "#0277bd"),
        "arm_l": ("左臂", "#2e7d32"),
        "arm_r": ("右臂", "#558b2f"),
    }
    x0, y0 = 60, 110
    for i, j in enumerate(JOINTS):
        col, row = divmod(i, 10)
        x, y = x0 + col * 660, y0 + row * 72
        label, color = groups[j["group"]]
        sh.rect(x, y, 620, 62, fill="#fff", stroke=color, sw=2)
        sh.rect(x, y, 10, 62, fill=color)
        sh.text(x + 24, y + 26, f"ID {i:02d}  {j['name']}", 16, weight="bold")
        sh.text(x + 24, y + 48, f"{label}   限位 {j['limit_deg'][0]}° … {j['limit_deg'][1]}°", 13, fill="#444")
    sh.text(60, 870, "相对 v1 删除：left_hip_yaw、right_hip_yaw。G4 失败则加回，软件 config.py 暂不改。", 14)
    sh.text(60, 894, "上肢躯干 = 双臂 8 + 躯干 2 = 10。头 2 另计。", 14)
    return sh.dumps()


def views() -> str:
    sh = Sheet(1400, 990, "三视图与尺寸链", "ATRI-v2-02")
    _title(sh)
    env = envelope_mm()
    # 简单方块三视图
    def box(x, y, w, h, label):
        sh.rect(x, y, w, h, fill="#eceff1", stroke="#37474f", sw=1.6)
        sh.text(x + w / 2, y - 12, label, 13, anchor="middle")

    s = 1.2
    H, W, D = env["height_mm"] * s / 2, env["width_mm"] * s / 2, env["depth_mm"] * s / 2
    box(120, 200, W, H, "正视")
    box(120 + W + 80, 200, D, H, "侧视")
    box(120, 200 + H + 80, W, D, "俯视")
    sh.text(120, 160, f"H={env['height_mm']:.0f}  W={env['width_mm']:.0f}  T={env['depth_mm']:.0f}", 16, weight="bold")
    sh.text(120, 820, "足 120×70；踝距踵 42；髋宽 80；肩宽 150；小腿/大腿轴距 78；上臂 58 / 前臂 52。", 14)
    sh.text(120, 848, "官方上限 600×300×300。第三轴是厚度不是臂长。", 14)
    r = eng_report()
    sh.text(700, 200, "质量门", 16, weight="bold")
    sh.text(700, 228, f"设计 {r['mass_design_g']:.0f} g / 硬限 {r['mass_hard_g']:.0f} g / 铝 {r['aluminum_g']:.0f} g", 14)
    sh.text(700, 260, "力矩门（踝）", 16, weight="bold")
    sh.text(700, 288, f"慢步 {r['ankle_walk_nm']:.3f} N·m  {r['ankle_walk_util']*100:.1f}%", 14)
    sh.text(700, 312, f"保持 {r['ankle_hold_nm']:.3f} N·m  {r['ankle_hold_util']*100:.1f}%  （仍超额定）", 14)
    return sh.dumps()


def sandwich() -> str:
    sh = Sheet(1400, 990, "夹层关节详图 STS3215", "ATRI-v2-03")
    _title(sh)
    # 侧视爆炸：idle plate | servo | horn disc | C-arm
    y = 420
    sh.rect(80, y - 70, 12, 140, fill="#90caf9", stroke="#1565c0")
    sh.text(86, y + 90, "IDLE 1.5", 11, anchor="middle")
    sh.rect(160, y - 80, 70, 160, fill="#455a64")
    sh.text(195, y + 100, "STS3215 沿轴 35", 12, anchor="middle")
    sh.circle(230, y, 18, stroke="#ffb300", sw=2)
    sh.text(230, y - 100, "输出凸台 Φ20", 12, anchor="middle")
    sh.rect(280, y - 50, 10, 100, fill="#ffe082", stroke="#f9a825")
    sh.text(285, y + 70, "25T", 11, anchor="middle")
    sh.rect(320, y - 70, 12, 140, fill="#a5d6a7", stroke="#2e7d32")
    sh.text(326, y + 90, "HORN 1.5", 11, anchor="middle")
    sh.rect(380, y - 16, 220, 32, fill="#c8e6c9", stroke="#2e7d32")
    sh.text(490, y - 28, "C-ARM 两侧板", 13, anchor="middle")
    sh.text(80, 160, "面安装：9.90×9.90 方阵 → PCD Φ14，4×M2.5 通孔 Φ2.7。无安装耳。", 15)
    sh.text(80, 188, "副轴 Φ6 → MF106ZZ。铝板轴承孔 Φ10.2（间隙，用法兰挡肩，不作过盈）。", 15)
    sh.text(80, 216, "1.5 mm 铝不攻 M3 承力螺纹：通孔 + 尼龙锁紧或铜柱。", 15)
    sh.text(80, 244, "PETG 壳不贴 12V 舵机壳体。线走 C-ARM 内侧。", 15)
    sh.text(80, 720, f"舵机 45.22×24.7×35 mm，55 g，额定 10 kg·cm = {SERVO['rated_nm']} N·m @12V，堵转 30 kg·cm。", 14)
    sh.text(80, 748, "3S 满电 12.6 V 落在 C018 / 微雪 6–12.6 V 范围内。禁止 4S。", 14)
    return sh.dumps()


def plate_svg(p: Plate) -> str:
    sh = Sheet(1000, 700, f"{p.name}  {p.material} {p.thickness_mm} mm", p.drawing_no)
    _title(sh)
    xmin, ymin, xmax, ymax = bbox(p)
    w, h = xmax - xmin, ymax - ymin
    scale = min(520 / max(w, 1), 380 / max(h, 1))
    ox, oy = 200 - xmin * scale, 400 - ymin * scale

    def xf(pt):
        return ox + pt[0] * scale, oy - pt[1] * scale

    sh.poly([xf(pt) for pt in p.outline], fill="#eceff1", stroke="#1565c0", sw=1.6)
    for hole in p.holes:
        x, y = xf((hole.x, hole.y))
        sh.circle(x, y, hole.d * scale / 2.0, stroke="#c62828", sw=1.0)
    sh.text(40, 100, f"数量 {p.qty}", 16, weight="bold")
    sh.text(40, 124, p.note, 13)
    sh.text(40, 148, "孔：红圈为切割；M2.5 通 2.7；M3 通 3.2；MF106 10.2。", 13)
    sh.text(40, 640, f"外廓约 {w:.1f} × {h:.1f} mm。激光后去毛刺，禁止再钻偏 PCD。", 13)
    return sh.dumps()


def all_svg() -> Dict[str, str]:
    out = {
        "drawings/ATRI-v2-00-封面装配图.svg": cover(),
        "drawings/ATRI-v2-01-关节编号.svg": joints(),
        "drawings/ATRI-v2-02-三视图.svg": views(),
        "drawings/ATRI-v2-03-夹层关节详图.svg": sandwich(),
    }
    for p in all_plates():
        out[f"drawings/{p.drawing_no}-{p.name}.svg"] = plate_svg(p)
    return out
