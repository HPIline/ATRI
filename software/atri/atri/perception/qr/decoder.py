"""二维码解码器：三个可替换实现 + 统一结果结构。

赛题②要的是「识别二维码并按指示路径行走」，识别这一步的**鲁棒性**直接决定成败：
现场会有倾斜、反光、距离远、运动模糊。所以解码器做成可替换单元，
并提供对照实测（见 ``software/atri/tools/qr_eval.py``），用数据决定主用哪个。

| 实现 | 依赖 | 特点 |
|---|---|---|
| ``OpenCVQrDecoder`` | opencv 自带 | 原始 ``QRCodeDetector``，零额外文件 |
| ``ArucoQrDecoder`` | opencv 自带 | ``QRCodeDetectorAruco``，自带检测器换成了 ArUco 风格 |
| ``WeChatQrDecoder`` | 4 个模型文件（共约 1 MB） | 面向手机扫码场景，带超分模型，通常最耐畸变/模糊 |

**cv2 一律惰性导入**：核心包不装 opencv 也能 import 本模块（CI 主 job 就是这种环境）。
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..base import PerceptionError

# WeChat 模型出处： https://github.com/opencv/opencv_zoo/tree/main/models/qrcode_wechatqrcode
# 文件名保留官方的 _2021nov 版本号，便于追溯。
WECHAT_MODEL_FILES: Tuple[Tuple[str, str, int], ...] = (
    # (文件名, sha256, 字节数)
    (
        "detect_2021nov.prototxt",
        "e8acfc395caf443a47f15686a9b9207b36cb8f7e6ceb8fbaf6466665e68a9466",
        42656,
    ),
    (
        "detect_2021nov.caffemodel",
        "cc49b8c9babaf45f3037610fe499df38c8819ebda29e90ca9f2e33270f6ef809",
        965430,
    ),
    (
        "sr_2021nov.prototxt",
        "8ae41acba97e8b4a8e741ee350481e49b8e01d787193f470a4c95ee1c02d5b61",
        5984,
    ),
    (
        "sr_2021nov.caffemodel",
        "e5d36889d8e6ef2f1c1f515f807cec03979320ac81792cd8fb927c31fd658ae3",
        23929,
    ),
)

# 模型目录按**包位置**解析成绝对路径：默认值若是相对路径，
# 从别的目录启动（或从仿真器里启动）就会找不到模型，而报错又会指向一个"看起来没错"的路径。
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[5] / "models" / "wechat_qrcode"


@dataclass
class QrResult:
    """一次解码的结果。"""

    found: bool
    data: str = ""
    points: Any = None
    decoder: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found,
            "data": self.data,
            "decoder": self.decoder,
            "bytes": len(self.data),
            "error": self.error,
        }


class QrDecoder(ABC):
    """二维码解码器接口。"""

    name: str = "base"
    requires_models: bool = False

    @abstractmethod
    def decode(self, frame: Any) -> QrResult:
        """解一帧里的二维码。解不出返回 ``found=False``，不抛异常。"""

    def available(self) -> Tuple[bool, str]:
        """返回 ``(可用?, 原因)``。原因要能指导下一步动作，不能只说"不可用"。"""
        return True, ""

    def _get_cv2(self) -> Any:
        try:
            import cv2  # type: ignore
        except ImportError as exc:  # pragma: no cover - 环境问题
            raise PerceptionError(
                "OpenCV 未安装：请执行 pip install \"opencv-contrib-python==4.11.0.86\""
            ) from exc
        return cv2

    @staticmethod
    def _check_frame(frame: Any) -> None:
        """只拒绝空帧。

        形状校验交给 cv2 自己 —— 它比我们清楚什么样的输入能解。
        cv2 抛的错由各 ``decode`` 捕获成 ``found=False`` + ``error``，
        不让异常冒到技能层（否则一张坏图会把整张任务卡推进 ERROR）。
        """
        if frame is None:
            raise PerceptionError("decode 需要传入图像帧")


class OpenCVQrDecoder(QrDecoder):
    """OpenCV 自带 ``QRCodeDetector``。零额外文件。"""

    name = "opencv"

    def __init__(self, cv2_module: Any = None) -> None:
        self._cv2 = cv2_module
        self._detector: Any = None

    def _ensure(self) -> Any:
        if self._detector is None:
            cv = self._cv2 or self._get_cv2()
            self._detector = cv.QRCodeDetector()
        return self._detector

    def decode(self, frame: Any) -> QrResult:
        self._check_frame(frame)
        try:
            data, points, _ = self._ensure().detectAndDecode(frame)
        except Exception as exc:  # cv2 在退化输入上会抛，不能让它冒到技能层
            return QrResult(found=False, decoder=self.name, error=f"{type(exc).__name__}: {exc}")
        if not data:
            return QrResult(found=False, decoder=self.name)
        return QrResult(found=True, data=str(data), points=points, decoder=self.name)


class ArucoQrDecoder(QrDecoder):
    """``cv2.QRCodeDetectorAruco``。同样零额外文件。"""

    name = "aruco"

    def __init__(self, cv2_module: Any = None) -> None:
        self._cv2 = cv2_module
        self._detector: Any = None

    def _ensure(self) -> Any:
        if self._detector is None:
            cv = self._cv2 or self._get_cv2()
            self._detector = cv.QRCodeDetectorAruco()
        return self._detector

    def decode(self, frame: Any) -> QrResult:
        self._check_frame(frame)
        try:
            data, points, _ = self._ensure().detectAndDecode(frame)
        except Exception as exc:
            return QrResult(found=False, decoder=self.name, error=f"{type(exc).__name__}: {exc}")
        if not data:
            return QrResult(found=False, decoder=self.name)
        return QrResult(found=True, data=str(data), points=points, decoder=self.name)


class WeChatQrDecoder(QrDecoder):
    """微信扫码解码器（detect + 超分），面向畸变/模糊/远距离场景。

    需要 4 个模型文件（共约 1 MB）；缺失时 :meth:`available` 会说明缺哪些，
    并且**不会**静默退化成别的解码器 —— 选型是调用方的事，不是解码器的事。
    """

    name = "wechat"
    requires_models = True

    def __init__(self, model_dir: str | Path = DEFAULT_MODEL_DIR, cv2_module: Any = None) -> None:
        self.model_dir = Path(model_dir)
        self._cv2 = cv2_module
        self._decoder: Any = None

    def available(self) -> Tuple[bool, str]:
        missing = [name for name, _, _ in WECHAT_MODEL_FILES if not (self.model_dir / name).exists()]
        if missing:
            return False, (
                f"缺少 {len(missing)} 个模型文件（{self.model_dir}）：{', '.join(missing)}；"
                "先运行 python software/atri/tools/fetch_models.py --wechat"
            )
        try:
            cv = self._cv2 or self._get_cv2()
        except PerceptionError as exc:
            return False, str(exc)
        if not hasattr(cv, "wechat_qrcode_WeChatQRCode"):
            return False, "当前 cv2 不含 wechat_qrcode（需要 opencv-contrib-python）"
        return True, ""

    def _ensure(self) -> Any:
        if self._decoder is None:
            ok, reason = self.available()
            if not ok:
                raise PerceptionError(f"WeChatQRCode 不可用: {reason}")
            cv = self._cv2 or self._get_cv2()
            self._decoder = cv.wechat_qrcode_WeChatQRCode(
                str(self.model_dir / "detect_2021nov.prototxt"),
                str(self.model_dir / "detect_2021nov.caffemodel"),
                str(self.model_dir / "sr_2021nov.prototxt"),
                str(self.model_dir / "sr_2021nov.caffemodel"),
            )
        return self._decoder

    def decode(self, frame: Any) -> QrResult:
        self._check_frame(frame)
        try:
            results, points = self._ensure().detectAndDecode(frame)
        except PerceptionError as exc:
            return QrResult(found=False, decoder=self.name, error=str(exc))
        except Exception as exc:
            return QrResult(found=False, decoder=self.name, error=f"{type(exc).__name__}: {exc}")
        if not results or not results[0]:
            return QrResult(found=False, decoder=self.name)
        return QrResult(found=True, data=str(results[0]), points=points, decoder=self.name)


DECODER_CLASSES: Dict[str, Any] = {
    "opencv": OpenCVQrDecoder,
    "aruco": ArucoQrDecoder,
    "wechat": WeChatQrDecoder,
}

DECODER_NAMES: Tuple[str, ...] = tuple(DECODER_CLASSES)


def build_qr_decoder(name: str = "opencv", **kwargs: Any) -> QrDecoder:
    """按名字构造解码器。名字不认识就报错并列出可选值，不静默兜底。"""
    cls = DECODER_CLASSES.get(name)
    if cls is None:
        raise PerceptionError(f"未知二维码解码器 {name!r}，可选: {sorted(DECODER_CLASSES)}")
    return cls(**kwargs)


def decoder_status(model_dir: str | Path = DEFAULT_MODEL_DIR) -> List[Dict[str, Any]]:
    """列出各解码器的可用性，供工具与报告打印。"""
    out: List[Dict[str, Any]] = []
    for name in DECODER_NAMES:
        kwargs = {"model_dir": model_dir} if name == "wechat" else {}
        try:
            decoder = build_qr_decoder(name, **kwargs)
            ok, reason = decoder.available()
        except Exception as exc:  # pragma: no cover - 构造失败也算不可用
            ok, reason = False, f"{type(exc).__name__}: {exc}"
        out.append({"decoder": name, "available": ok, "reason": reason})
    return out
