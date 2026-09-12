"""人脸对齐：把任意姿态的人脸裁成 112×112 的标准正面图。

为什么需要：识别模型是在**对齐后**的人脸上训练的。直接按 bbox 裁图，
角度/尺度一变，特征就飘。所以裁剪必须按关键点做相似变换。

两种裁剪方式：
- ``SFaceAligner``：优先用 SFace 自带的 ``alignCrop``（模型作者实现，与训练口径一致）
- ``align_5pt`` / ``crop_by_bbox``：本模块自己实现，用于没有关键点的检测器、
  以及纯几何单元测试（不依赖 cv2 也能测变换矩阵）

坐标点顺序：统一按 **图像 x 从小到大** 排成
（左眼、右眼、鼻尖、左嘴角、右嘴角）后再对齐模板，
这样不依赖各检测器对"左右眼"的命名约定。
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from ..base import PerceptionError

# ArcFace 标准 112×112 五点模板（左眼、右眼、鼻尖、左嘴角、右嘴角）
FACE_TEMPLATE_112 = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float64,
)

OUTPUT_SIZE = 112


def order_landmarks(landmarks: Sequence[Sequence[float]]) -> np.ndarray:
    """把 5 个关键点排成（左眼、右眼、鼻尖、左嘴角、右嘴角）。

    检测器对"左右眼"的命名各执一词，但图像里谁在左边是确定的：
    眼睛两点按 x 排序，嘴角两点按 x 排序。鼻尖是第 3 点。
    """
    pts = np.asarray(landmarks, dtype=np.float64)
    if pts.shape != (5, 2):
        raise PerceptionError(f"需要 5 个 (x, y) 关键点，实际收到 shape={pts.shape}")
    eyes = pts[:2]
    nose = pts[2:3]
    mouth = pts[3:5]
    eyes = eyes[np.argsort(eyes[:, 0])]
    mouth = mouth[np.argsort(mouth[:, 0])]
    return np.vstack([eyes, nose, mouth])


def similarity_transform(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """求把 src 点集映射到 dst 点集的**相似变换**（旋转+等比缩放+平移）2×3 矩阵。

    用 Umeyama 的最小二乘解，纯 numpy，便于单测。
    """
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    if src.shape != dst.shape or src.shape[1] != 2:
        raise PerceptionError("src/dst 必须是同形状的 (N, 2) 点集")
    n = src.shape[0]
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_c = src - src_mean
    dst_c = dst - dst_mean

    cov = dst_c.T @ src_c / n
    u, s, vt = np.linalg.svd(cov)
    d = np.ones(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        d[-1] = -1.0
    rot = u @ np.diag(d) @ vt

    var_src = (src_c ** 2).sum() / n
    if var_src <= 1e-12:
        raise PerceptionError("源点集退化（所有点重合），无法求相似变换")
    scale = float((s * d).sum() / var_src)
    t = dst_mean - scale * (rot @ src_mean)
    matrix = np.zeros((2, 3), dtype=np.float64)
    matrix[:, :2] = scale * rot
    matrix[:, 2] = t
    return matrix


def align_5pt(frame: Any, landmarks: Sequence[Sequence[float]], size: int = OUTPUT_SIZE) -> Any:
    """按 5 关键点做相似变换，输出 size×size 的正面人脸（BGR）。"""
    try:
        import cv2  # type: ignore
    except ImportError as exc:  # pragma: no cover - 环境问题
        raise PerceptionError("对齐需要 OpenCV（cv2.warpAffine）") from exc

    pts = order_landmarks(landmarks)
    template = FACE_TEMPLATE_112 * (size / float(OUTPUT_SIZE))
    matrix = similarity_transform(pts, template)
    return cv2.warpAffine(frame, matrix, (size, size), flags=cv2.INTER_LINEAR)


def crop_by_bbox(frame: Any, bbox: Sequence[int], margin: float = 0.0) -> Any:
    """按 bbox 直接裁图（无关键点时的退路）。超出边界的部分会被截断。"""
    height, width = int(frame.shape[0]), int(frame.shape[1])
    x, y, w, h = (int(v) for v in bbox[:4])
    if margin:
        dx, dy = int(w * margin), int(h * margin)
        x, y, w, h = x - dx, y - dy, w + 2 * dx, h + 2 * dy
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        raise PerceptionError(f"bbox {bbox} 落在画面外，裁不出人脸")
    return frame[y0:y1, x0:x1]
