"""语音服务：关键词识别 + 应答播报的组合入口。"""
from __future__ import annotations

from typing import Any, Dict

from .base import KeywordRecognizer, TTS


class VoiceService:
    def __init__(self, recognizer: KeywordRecognizer, tts: TTS) -> None:
        self.recognizer = recognizer
        self.tts = tts

    def respond(self, audio: Any = None, reply_template: str = "{keyword}") -> Dict[str, Any]:
        keyword = self.recognizer.recognize(audio)
        try:
            text = reply_template.format(keyword=keyword)
        except (KeyError, IndexError, ValueError):
            # 模板含未知占位符时退回播报关键词本身，不中断整条语音链路
            text = keyword
        self.tts.speak(text)
        return {"keyword": keyword, "reply": text}
