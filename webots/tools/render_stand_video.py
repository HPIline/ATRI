"""把静立姿态日志画成能看见机器人的盒体视频。

本机 Webots 无头 3D/Camera 拍不到连杆（只见天空和地面）。这段重建用的是
仿真里真实记下的关节角和骨盆位姿，不是另做的假动画。
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_atri_world as gen  # noqa: E402


def _rot_axis(axis: Sequence[float], rad: float) -> np.ndarray:
    ax = np.asarray(axis, dtype=float)
    n = float(np.linalg.norm(ax))
    if n < 1e-12:
        return np.eye(3)
    x, y, z = ax / n
    c, s = math.cos(rad), math.sin(rad)
    C = 1.0 - c
    return np.array(
        [
            [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
        ]
    )


def _rpy_mat(roll: float, pitch: float, yaw: float) -> np.ndarray:
    return _rot_axis((0, 0, 1), yaw) @ _rot_axis((0, 1, 0), pitch) @ _rot_axis((1, 0, 0), roll)


def _T(R: np.ndarray, p: Sequence[float]) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = R
    out[:3, 3] = p
    return out


def _color_for(name: str) -> Tuple[float, float, float]:
    if name in {"pelvis", "trunk_roll", "trunk_pitch"}:
        return (0.86, 0.32, 0.18)
    if "head" in name:
        return (0.95, 0.82, 0.35)
    if "hip" in name or "knee" in name or "ankle" in name:
        return (0.18, 0.42, 0.86)
    return (0.55, 0.58, 0.62)


def link_boxes(pose_deg: Dict[str, float]) -> List[Dict[str, Any]]:
    """正运动学：每个连杆盒在骨盆系里的中心、旋转、尺寸。"""
    boxes: List[Dict[str, Any]] = []
    pelvis_size = gen.robot_body()[1]
    boxes.append(
        {
            "name": "pelvis",
            "center": np.zeros(3),
            "R": np.eye(3),
            "size": pelvis_size,
            "color": _color_for("pelvis"),
        }
    )

    def walk(node: Dict[str, Any], parent: np.ndarray) -> None:
        q = math.radians(float(pose_deg.get(node["name"], 0.0)))
        joint = parent @ _T(np.eye(3), node["anchor"]) @ _T(_rot_axis(node["axis"], q), (0, 0, 0))
        boxes.append(
            {
                "name": node["name"],
                "center": joint[:3, 3].copy(),
                "R": joint[:3, :3].copy(),
                "size": node["size"],
                "color": _color_for(node["name"]),
            }
        )
        for child in node["children"]:
            walk(child, joint)

    for root in gen.robot_children():
        walk(root, np.eye(4))
    return boxes


def world_boxes(
    pose_deg: Dict[str, float],
    xyz: Sequence[float],
    rpy: Sequence[float],
) -> List[Dict[str, Any]]:
    Tw = _T(_rpy_mat(float(rpy[0]), float(rpy[1]), float(rpy[2])), xyz)
    out = []
    for box in link_boxes(pose_deg):
        R = Tw[:3, :3] @ box["R"]
        c = Tw[:3, 3] + Tw[:3, :3] @ box["center"]
        out.append({**box, "center": c, "R": R})
    return out


def _box_faces(center: np.ndarray, R: np.ndarray, size: Sequence[float]) -> List[np.ndarray]:
    hx, hy, hz = [float(s) / 2.0 for s in size]
    corners = np.array(
        [[sx * hx, sy * hy, sz * hz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    )
    pts = (R @ corners.T).T + center
    # indices of 8 corners in the loop order above
    faces_i = (
        (0, 1, 3, 2),
        (4, 5, 7, 6),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (0, 2, 6, 4),
        (1, 3, 7, 5),
    )
    return [pts[list(idx)] for idx in faces_i]


def render_frame(
    boxes: List[Dict[str, Any]],
    path: Path,
    title: str = "",
) -> None:
    fig = plt.figure(figsize=(10.24, 5.76), dpi=125)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor((0.62, 0.72, 0.88))
    fig.patch.set_facecolor((0.92, 0.93, 0.95))
    all_faces = []
    all_colors = []
    for box in boxes:
        for face in _box_faces(box["center"], box["R"], box["size"]):
            all_faces.append(face)
            all_colors.append(box["color"])
    coll = Poly3DCollection(
        all_faces, facecolors=all_colors, edgecolors=(0.15, 0.15, 0.18), linewidths=0.4, alpha=1.0
    )
    ax.add_collection3d(coll)
    pelvis = next((b for b in boxes if b["name"] == "pelvis"), boxes[0])
    cx, cy = float(pelvis["center"][0]), float(pelvis["center"][1])
    span = 0.35
    ground = np.array(
        [
            [cx - span, cy - span, 0],
            [cx + span, cy - span, 0],
            [cx + span, cy + span, 0],
            [cx - span, cy + span, 0],
        ]
    )
    ax.add_collection3d(
        Poly3DCollection([ground], facecolors=(0.86, 0.82, 0.74), edgecolors="none", alpha=0.9)
    )
    ax.set_xlim(cx - span, cx + span)
    ax.set_ylim(cy - span, cy + span)
    ax.set_zlim(0.0, 0.45)
    try:
        ax.set_box_aspect((1, 1, 0.65))
    except Exception:
        pass
    ax.view_init(elev=18, azim=-55)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")
    if title:
        ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=125)
    plt.close(fig)


def load_log(path: Path) -> List[Dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def encode_mp4(frame_dir: Path, out: Path, fps: int = 12) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(fps),
        "-i", str(frame_dir / "frame_%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, help="pose_log.jsonl")
    parser.add_argument("--out", required=True, help="mp4 路径")
    parser.add_argument("--work", default=None, help="帧目录（默认临时）")
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    rows = load_log(log_path)
    if not rows:
        print("姿态日志是空的", file=sys.stderr)
        return 2
    work = Path(args.work) if args.work else log_path.parent / "vis_frames"
    work.mkdir(parents=True, exist_ok=True)
    for i, row in enumerate(rows):
        xyz = row.get("xyz") or [0.0, 0.0, 0.20]
        rpy = row.get("rpy") or [0.0, 0.0, 0.0]
        pose = row.get("pose") or {}
        boxes = world_boxes(pose, xyz, rpy)
        title = f"t={row.get('t', 0):.2f}s  z={xyz[2]:.3f}m"
        render_frame(boxes, work / f"frame_{i:05d}.png", title=title)
        if i % 20 == 0:
            print(f"  渲染 {i + 1}/{len(rows)}")
    encode_mp4(work, Path(args.out))
    print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
