"""技能基类与任务上下文。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SkillContext:
    task_id: str
    task_name: str
    params: Dict[str, Any]
    cerebellum: Any
    observation: Optional[Dict[str, Any]] = None
    log: List[str] = None
    perception: Any = None
    tts_engine: Any = None

    def __post_init__(self) -> None:
        if self.log is None:
            self.log = []

    def perceive(self, key: str) -> Dict[str, Any]:
        if self.observation and key in self.observation:
            return self.observation[key]
        if self.perception is not None:
            method = getattr(self.perception, f"detect_{key}", None)
            if method is not None:
                result = method()
                if result is not None and getattr(result, "data", None):
                    return result.data
        return {}

    def tts(self, text: str) -> None:
        if self.tts_engine is not None:
            self.tts_engine.speak(text)
        else:
            print(f"  [TTS] {text}")
        self.log.append(f"tts: {text}")


class Skill:
    name = "base"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        raise NotImplementedError
