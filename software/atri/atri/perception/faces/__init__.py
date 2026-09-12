"""人脸识别子模块（T-01）。

**注意：本子模块依赖 numpy / opencv，因此不在 ``atri.perception.__init__`` 里急切导入。**
核心包（任务卡/FSM/技能/无硬件演示）保持零第三方依赖，不装 numpy 也能跑。
需要人脸能力时显式导入::

    from atri.perception.faces import FaceRecognizer, YuNetDetector, SFaceEmbedder, FaceDB

模块构成：

- ``detector``  ：检测器（YuNet 主力 / Haar 对照）
- ``align``     ：5 关键点相似变换对齐到 112×112
- ``embedder``  ：特征提取器（SFace / Mock）
- ``face_db``   ：注册库与余弦比对
- ``pipeline``  ：三者组装成 FaceRecognizer

方案出处：``design/handoff/T-01-人脸识别-方案.md``
"""
from .align import FACE_TEMPLATE_112, OUTPUT_SIZE, align_5pt, crop_by_bbox, similarity_transform
from .detector import FaceBox, FaceDetector, HaarDetector, YuNetDetector
from .embedder import FaceEmbedder, MockEmbedder, SFaceEmbedder, l2_normalize
from .face_db import SCHEMA_VERSION, FaceDB, MatchResult, Person
from .pipeline import FaceRecognizer, FaceResult, FrameResult

__all__ = [
    "FACE_TEMPLATE_112",
    "OUTPUT_SIZE",
    "align_5pt",
    "crop_by_bbox",
    "similarity_transform",
    "FaceBox",
    "FaceDetector",
    "HaarDetector",
    "YuNetDetector",
    "FaceEmbedder",
    "MockEmbedder",
    "SFaceEmbedder",
    "l2_normalize",
    "SCHEMA_VERSION",
    "FaceDB",
    "MatchResult",
    "Person",
    "FaceRecognizer",
    "FaceResult",
    "FrameResult",
]
