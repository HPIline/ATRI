#!/usr/bin/env python3
"""生成姿态动画视频（保底路线 B：CAD/预览驱动，非物理仿真）。

为什么需要它
------------
参赛要交 1 个视频，而**本机没有任何视频编码能力**（无 ffmpeg、无 PyObjC、
`/usr/bin/avconvert` 只吃单个媒体文件、不吃图片序列）。队友若来不及跑 Webots，
就必须有一条**不依赖任何人**的保底路线。本工具就是那条路线，全链路已在
2026-09-12 实测打通（见 `design/handoff/线程报告-视频保底路线.md`）。

原理
----
1. `design/cad/preview.py` 生成的自包含 HTML 支持 **URL 驱动姿态注入**：
   `file://…/ATRI-preview.html#pose=head_yaw:-14,right_shoulder_pitch:-88`
   （解析见 `preview.py` 的 `applyHash()`；逗号分隔、名字须与 `META.joints` 精确匹配）
2. 用 **Microsoft Edge 无头 + SwiftShader 软件渲染** 逐帧截图。
   ⚠️ 关键：**不能加 `--disable-gpu`**，那会把 WebGL 一起关掉 ⇒ 白屏
   （HTML 只显示"此浏览器不支持 WebGL"）。必须用 `--enable-unsafe-swiftshader`。
3. 用 `imageio-ffmpeg` 自带的 ffmpeg 二进制把 PNG 序列编码成 H.264 mp4。

⚠️ **诚实标注**：本工具产出的是**渲染动画**，不是物理仿真，更不是实测。
进材料时必须写明"渲染动画，非物理仿真"（本仓库第 4 条纪律）。

用法
----
    .venv-cad/bin/python design/cad/tools/make_pose_video.py \
        --html design/cad/out/preview/ATRI-preview.html \
        --out  design/cad/out/video/ATRI-pose-demo.mp4 \
        --frames 128 --fps 12

    # 先只渲 3 帧验证链路（约 45 秒），确认没问题再跑全套
    .venv-cad/bin/python design/cad/tools/make_pose_video.py --probe
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent          # design/cad/tools → 仓库根

EDGE = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"

# 与 preview.py 的 POSE_PRESETS 同源取值的姿态表（这里只列本工具要用的关键帧）。
# 关节名必须与 URDF / META.joints 精确一致，写错会被 applyHash 静默忽略。
POSE_ZERO: Dict[str, float] = {}

POSE_ATTENTION: Dict[str, float] = {
    "left_shoulder_pitch": -8.0, "right_shoulder_pitch": -8.0,
    "left_elbow_pitch": -12.0, "right_elbow_pitch": -12.0,
    "head_pitch": 3.0,
}

POSE_WAVE_UP: Dict[str, float] = {
    "right_shoulder_pitch": -88.0, "right_elbow_pitch": -90.0,
    "right_shoulder_roll": -12.0, "right_gripper": 15.0,
    "left_shoulder_pitch": -14.0, "left_elbow_pitch": -22.0,
    "left_shoulder_roll": 6.0, "head_yaw": -14.0, "head_pitch": 4.0,
    "trunk_roll": -3.0,
}

POSE_WAVE_SIDE: Dict[str, float] = dict(
    POSE_WAVE_UP, **{"right_shoulder_roll": -34.0, "head_yaw": -18.0}
)

POSE_KICK: Dict[str, float] = {
    "right_hip_pitch": -60.0, "right_knee_pitch": 62.0, "right_ankle_pitch": -24.0,
    "left_hip_pitch": 3.0, "left_knee_pitch": 3.0,
    "left_shoulder_pitch": -30.0, "left_elbow_pitch": -40.0,
    "right_shoulder_pitch": 20.0, "right_elbow_pitch": -30.0,
    "trunk_pitch": 8.0, "head_pitch": -6.0,
}


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease(t: float) -> float:
    """平滑插值（smoothstep），让姿态过渡不机械。"""
    return t * t * (3.0 - 2.0 * t)


def blend(pa: Dict[str, float], pb: Dict[str, float], t: float) -> Dict[str, float]:
    """两姿态按 t∈[0,1] 混合；只出现在一侧的关节从 0 起算（零位 = 0°）。"""
    keys = set(pa) | set(pb)
    return {k: lerp(pa.get(k, 0.0), pb.get(k, 0.0), t) for k in keys}


def build_keyframes(frames: int) -> List[Tuple[Dict[str, float], float]]:
    """返回 [(姿态, 镜头 yaw)] 的逐帧列表。

    编排：零位 → 立正 → 举右手 → 摆两下 → 收手 → 踢球 → 回零位。
    镜头 yaw 跟着做小幅摆动，避免画面完全静止。
    """
    # (姿态, 该段占的帧数比例)
    segments: List[Tuple[Dict[str, float], Dict[str, float], float]] = [
        (POSE_ZERO, POSE_ATTENTION, 0.10),
        (POSE_ATTENTION, POSE_WAVE_UP, 0.14),
        (POSE_WAVE_UP, POSE_WAVE_SIDE, 0.09),
        (POSE_WAVE_SIDE, POSE_WAVE_UP, 0.09),
        (POSE_WAVE_UP, POSE_WAVE_SIDE, 0.07),
        (POSE_WAVE_SIDE, POSE_ATTENTION, 0.13),
        (POSE_ATTENTION, POSE_KICK, 0.15),
        (POSE_KICK, POSE_ZERO, 0.23),
    ]
    out: List[Tuple[Dict[str, float], float]] = []
    for idx, (pa, pb, frac) in enumerate(segments):
        n = max(2, int(round(frames * frac)))
        for i in range(n):
            t = ease(i / (n - 1))
            out.append((blend(pa, pb, t), -20.0 + 40.0 * (i / max(1, n - 1)) * (1 if idx % 2 == 0 else -1) * 0.35))
    # 补/裁到目标帧数
    while len(out) < frames:
        out.append((POSE_ZERO, 0.0))
    return out[:frames]


def pose_to_hash(pose: Dict[str, float]) -> str:
    """姿态 → URL fragment。数值保留 2 位小数，避免长浮点串。"""
    if not pose:
        return "pose="
    items = ",".join("%s:%.2f" % (k, v) for k, v in sorted(pose.items()))
    return "pose=" + items


def make_clean_html(src: Path, dst: Path, mate_alpha: Optional[float] = None) -> None:
    """复制预览 HTML 并注入 CSS 隐藏 UI 面板，得到"只剩画面"的录制用副本。

    不修改 `preview.py`（那是别人的文件）：只对产物做后处理。

    `mate_alpha`：配合件半透明的 alpha（`preview.py` 的 `MATE_ALPHA = 0.5`）。
    传 1.0 即"关掉半透明"，让结构完整可见——**拍官图/宣传片时更干净**，
    但会遮住本该半透明显示的配合件（答辩讲干涉时应该保持 0.5）。
    """
    html = src.read_text(encoding="utf-8")
    css = (
        "<style id='__video_clean__'>"
        "#hud,#panel,#tip{display:none !important;}"
        "html,body{margin:0!important;padding:0!important;overflow:hidden!important;}"
        "canvas{width:100vw!important;height:100vh!important;display:block!important;}"
        "</style>"
    )
    if mate_alpha is not None:
        a = max(0.0, min(1.0, float(mate_alpha)))
        # ⚠️ 必须**精确替换**，不能全局换 "0.5"：实测该 HTML 里 "0.5" 出现 20 次，
        #    绝大多数是几何 AABB 坐标（如 -26.6 / 89.5）与 degMean，全局替换会把它们改坏。
        #    `preview.py` 用 f"{MATE_ALPHA:.2f}" 注入 ⇒ 字面量恰好是 "0.50" 且只有 2 处。
        #    用正则锚定 "mate" 上下文替换，避免依赖空白与分号的精确写法。
        pat = re.compile(r"(mate[^;\n]{0,24}?)(0\.50)")
        html, n = pat.subn(lambda m: m.group(1) + ("%.2f" % a), html)
        if n == 0:
            print("⚠️ 找不到配合件半透明字面量（正则命中 0 处）—— 跳过 --mate-alpha"
                  "（preview.py 可能已改版）", file=sys.stderr)
        else:
            print("已把配合件半透明 alpha 由 0.50 改为 %.2f（命中 %d 处）" % (a, n))
    if "</head>" in html:
        html = html.replace("</head>", css + "</head>", 1)
    else:
        html = css + html
    dst.write_text(html, encoding="utf-8")


def render_frame(html_path: Path, pose: Dict[str, float], out_png: Path,
                 size: Tuple[int, int], budget_ms: int, timeout_s: int,
                 edge: str) -> bool:
    """用无头 Edge 渲一帧。返回是否成功（PNG 存在且非空）。"""
    url = "file://%s#%s" % (html_path, pose_to_hash(pose))
    cmd = [
        edge,
        "--headless=new",
        "--no-sandbox",
        "--hide-scrollbars",
        # ⚠️ 不能加 --disable-gpu（会连 WebGL 一起关掉 ⇒ 白屏）
        "--enable-unsafe-swiftshader",
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--window-size=%d,%d" % size,
        "--virtual-time-budget=%d" % budget_ms,
        "--screenshot=%s" % out_png,
        url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False
    return out_png.exists() and out_png.stat().st_size > 2000


def encode(frames_dir: Path, out_mp4: Path, fps: int, size: Tuple[int, int],
           crf: int, ffmpeg: str) -> bool:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "f%04d.png"),
        "-vf", ("scale=%d:%d:force_original_aspect_ratio=decrease,"
                "pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (size[0], size[1], size[0], size[1])),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf),
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("[编码失败] ffmpeg 返回 %d\n%s" % (r.returncode, r.stderr[-1200:]),
              file=sys.stderr)
        return False
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="生成姿态动画视频（渲染动画，非仿真）")
    ap.add_argument("--html", default=str(REPO / "design/cad/out/preview/ATRI-preview.html"))
    ap.add_argument("--out", default=str(REPO / "design/cad/out/video/ATRI-pose-demo.mp4"))
    ap.add_argument("--frames", type=int, default=128)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--crf", type=int, default=23, help="越小越清晰/越大；23 约 1.5 Mbps")
    ap.add_argument("--budget-ms", type=int, default=25000,
                    help="每帧虚拟时间预算；太小会截到没渲染完的画面")
    ap.add_argument("--frame-timeout", type=int, default=120)
    ap.add_argument("--edge", default=EDGE)
    ap.add_argument("--workdir", default=None, help="帧临时目录（默认自动建）")
    ap.add_argument("--keep-frames", action="store_true")
    ap.add_argument("--probe", action="store_true", help="只渲 3 帧验证链路")
    ap.add_argument("--mate-alpha", type=float, default=None,
                    help="配合件半透明的 alpha（默认沿用 preview 的 0.50）。传 1.0 = 关掉半透明，"
                         "拍官图/宣传片更干净；讲干涉时保留默认")
    a = ap.parse_args(argv)

    src = Path(a.html)
    if not src.exists():
        print("找不到预览 HTML：%s\n先跑：.venv-cad/bin/python design/cad/preview.py --all" % src,
              file=sys.stderr)
        return 2
    if not Path(a.edge).exists():
        print("找不到 Edge：%s" % a.edge, file=sys.stderr)
        return 2
    try:
        import imageio_ffmpeg
    except ImportError:
        print("缺 imageio-ffmpeg。装：.venv-cad/bin/python -m pip install imageio-ffmpeg "
              "-i https://mirrors.aliyun.com/pypi/simple/", file=sys.stderr)
        return 2
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    w, h = (int(x) for x in a.size.lower().split("x"))
    n_frames = 3 if a.probe else a.frames
    plan = build_keyframes(max(n_frames, 8))[:n_frames] if a.probe else build_keyframes(n_frames)

    work = Path(a.workdir) if a.workdir else Path(tempfile.mkdtemp(prefix="atri-video-"))
    work.mkdir(parents=True, exist_ok=True)
    clean = work / "clean.html"
    make_clean_html(src, clean, mate_alpha=a.mate_alpha)
    print("预览源：%s" % src)
    print("录制用副本（已隐藏 UI）：%s" % clean)
    print("计划 %d 帧 @ %d fps → 约 %.1f 秒视频，%dx%d" %
          (len(plan), a.fps, len(plan) / a.fps, w, h))

    t0 = time.monotonic()
    fails = 0
    for i, (pose, _camyaw) in enumerate(plan):
        png = work / ("f%04d.png" % i)
        ok = render_frame(clean, pose, png, (w, h), a.budget_ms, a.frame_timeout, a.edge)
        if not ok:
            fails += 1
            print("  第 %d 帧渲染失败" % i, file=sys.stderr)
        if i == 0 or (i + 1) % 8 == 0 or i == len(plan) - 1:
            el = time.monotonic() - t0
            eta = el / (i + 1) * (len(plan) - i - 1)
            print("  帧 %3d/%d  已用 %.0fs  预计剩余 %.0fs  失败 %d" %
                  (i + 1, len(plan), el, eta, fails), flush=True)

    if fails:
        print("⚠️ 有 %d 帧失败——视频会有跳帧，建议提高 --budget-ms 或 --frame-timeout"
              % fails, file=sys.stderr)

    out = Path(a.out)
    if not encode(work, out, a.fps, (w, h), a.crf, ffmpeg):
        return 1
    dur = len(plan) / a.fps
    size_mb = out.stat().st_size / 1e6
    print("\n✅ 已写出 %s" % out)
    print("   %d 帧 @ %d fps = %.1f 秒 ｜ %.2f MB ｜ 约 %.1f Mbps" %
          (len(plan), a.fps, dur, size_mb, size_mb * 8 / max(dur, 0.1)))
    print("   ⚠️ 材料里必须标注：**渲染动画，非物理仿真**")
    if not a.keep_frames:
        shutil.rmtree(work, ignore_errors=True)
        print("   （帧临时目录已清理；要保留加 --keep-frames）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
