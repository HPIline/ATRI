"""语音交互模块：离线关键词识别 + TTS。

- MockKeywordRecognizer / MockTTS：无硬件开发与测试
- MacOSTTS：macOS 本地 say 命令实现
- LinuxTTS：Linux 系统 piper / espeak-ng / espeak / spd-say
- VoiceService：识别 -> 回复 -> 播报组合
- build_tts：按运行平台选择 TTS 实现

"""
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

from .base import KeywordRecognizer, TTS, VoiceError
from .linux import LinuxTTS
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
    "LinuxTTS",
    "VoiceService",
    "build_tts",
]


def build_tts(
    platform: Optional[str] = None,
    *,
    runner: Optional[Callable[..., Any]] = None,
    which: Optional[Callable[..., Optional[str]]] = None,
    looks: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> TTS:
    """按平台选择 TTS：darwin → MacOSTTS；linux 有引擎 → LinuxTTS，否则 MockTTS。"""
    target = sys.platform if platform is None else platform
    if target == "darwin":
        return MacOSTTS(is_darwin=True)
    if str(target).startswith("linux"):
        tts = LinuxTTS(runner=runner, which=which, looks=looks, env=env)
        if not tts.engine or tts.engine == "mock":
            return MockTTS()
        return tts
    return MockTTS()
