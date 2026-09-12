"""语音交互接口：离线关键词识别 + TTS。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VoiceError(RuntimeError):
    """语音模块错误。"""


class KeywordRecognizer(ABC):
    """离线关键词识别接口。

    recognize(audio) 接收可选的音频数据；Mock 实现忽略 audio。
    后续可在 Windows 上接入 Vosk / sherpa-onnx 等离线引擎。
    """

    name: str = "base"

    @abstractmethod
    def recognize(self, audio: Any = None) -> str:
        """返回识别到的关键词。"""


class TTS(ABC):
    """文本转语音接口。

    实现包括 MockTTS、MacOSTTS（``say``）、LinuxTTS（系统 ``piper`` /
    ``espeak-ng`` / ``espeak`` / ``spd-say``）。接口仅 ``speak(text)``。
    """

    name: str = "base"

    @abstractmethod
    def speak(self, text: str) -> None:
        """播报文本。"""
