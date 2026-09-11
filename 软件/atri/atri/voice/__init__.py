"""语音交互模块：离线关键词识别 + TTS。

- MockKeywordRecognizer / MockTTS：无硬件开发与测试
- MacOSTTS：macOS 本地 say 命令实现
- VoiceService：识别 -> 回复 -> 播报组合
- build_tts：按运行平台选择 TTS 实现

"""
import sys
from typing import Optional

from .base import KeywordRecognizer, TTS, VoiceError
from .macos import MacOSTTS
from .mock import MockKeywordRecognizer, MockTTS
from .service import VoiceService

__all__ = [
    "KeywordRecognizer",
    "TTS",
    "VoiceError",
    "MockKeywordRecognizer",
    "MockTTS",
    "MacOSTTS",
    "VoiceService",
    "build_tts",
]


def build_tts(platform: Optional[str] = None) -> TTS:
    """按 ``sys.platform`` 选择 TTS：macOS 用系统 say，其余平台退回 MockTTS（无音频设备也能跑）。"""
    target = sys.platform if platform is None else platform
    if target == "darwin":
        return MacOSTTS(is_darwin=True)
    return MockTTS()
