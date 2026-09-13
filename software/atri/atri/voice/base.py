"""语音交互接口：离线关键词识别 + TTS。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VoiceError(RuntimeError):
    """语音模块错误。"""


class KeywordRecognizer(ABC):
    """离线关键词识别接口。

    recognize(audio) 接收可选的音频数据；Mock 实现忽略 audio。
    可选离线后端见 ``atri.voice.vosk.VoskKeywordRecognizer``（惰性导入 vosk，
    没装引擎时 ``available()`` 为假，不静默假装听清）。
    """

    name: str = "base"

    def available(self) -> bool:
        """当前环境是否能真正识别；需要第三方引擎的实现覆盖它。"""
        return True

    @abstractmethod
    def recognize(self, audio: Any = None) -> str:
        """返回识别到的关键词；未命中时实现应返回空串，不要编造。"""


class TTS(ABC):
    """文本转语音接口。

    实现包括 MockTTS、MacOSTTS（``say``）、LinuxTTS（系统 ``piper`` /
    ``espeak-ng`` / ``espeak`` / ``spd-say``）。接口仅 ``speak(text)``。
    """

    name: str = "base"

    @abstractmethod
    def speak(self, text: str) -> None:
        """播报文本。"""
