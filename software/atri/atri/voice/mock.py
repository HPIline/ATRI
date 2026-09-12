"""Mock 语音：无硬件时用确定性关键词和内存 TTS。"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from .base import KeywordRecognizer, TTS

DEFAULT_KEYWORDS = ("跳舞", "前进", "抓取")


class MockKeywordRecognizer(KeywordRecognizer):
    name = "mock-keyword"

    def __init__(
        self,
        keywords: Sequence[str] = DEFAULT_KEYWORDS,
        default: Optional[str] = None,
    ) -> None:
        self.keywords = tuple(keywords)
        self.default = default or (self.keywords[0] if self.keywords else "跳舞")
        self._index = 0

    @property
    def next_keyword(self) -> str:
        if not self.keywords:
            return self.default
        value = self.keywords[self._index % len(self.keywords)]
        self._index += 1
        return value

    def recognize(self, audio: Any = None) -> str:
        return self.next_keyword


class MockTTS(TTS):
    name = "mock-tts"

    def __init__(self) -> None:
        self.spoken: List[str] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)
        print(f"  [TTS] {text}")
