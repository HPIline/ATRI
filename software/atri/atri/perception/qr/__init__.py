"""二维码子模块：解码器。

- ``decoder``：三个可替换实现（opencv / aruco / wechat）+ 可用性探测

**不在 ``atri.perception.__init__`` 里急切导入 cv2**：本子模块自身只在调用时惰性 import，
可以安全导入；但为避免上层误以为"二维码一定要装 opencv"，这里只导出构造入口。

路径 payload 的解析与校验在 :mod:`atri.path_plan`（生成端与执行端共用同一口径）。
"""
from .decoder import (
    DECODER_CLASSES,
    DECODER_NAMES,
    DEFAULT_MODEL_DIR,
    WECHAT_MODEL_FILES,
    ArucoQrDecoder,
    OpenCVQrDecoder,
    QrDecoder,
    QrResult,
    WeChatQrDecoder,
    build_qr_decoder,
    decoder_status,
)

__all__ = [
    "DECODER_CLASSES",
    "DECODER_NAMES",
    "DEFAULT_MODEL_DIR",
    "WECHAT_MODEL_FILES",
    "ArucoQrDecoder",
    "OpenCVQrDecoder",
    "QrDecoder",
    "QrResult",
    "WeChatQrDecoder",
    "build_qr_decoder",
    "decoder_status",
]
