"""语音交互模块：离线关键词识别 + TTS。

- MockKeywordRecognizer / MockTTS：无硬件开发与测试
- MacOSTTS：macOS 本地 say 命令实现
- VoiceService：识别 -> 回复 -> 播报组合
"""
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
]
