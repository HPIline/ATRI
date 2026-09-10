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

    def __post_init__(self) -> None:
        if self.log is None:
            self.log = []

    def perceive(self, key: str) -> Dict[str, Any]:
        if self.observation and key in self.observation:
            return self.observation[key]
        return {}

    def tts(self, text: str) -> None:
        print(f"  [TTS] {text}")
        self.log.append(f"tts: {text}")


class Skill:
    name = "base"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        raise NotImplementedError
