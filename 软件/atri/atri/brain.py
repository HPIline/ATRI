"""大脑计算层：任务注册、FSM 调度与技能执行。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .fsm import TaskFSM
from .skills import CarrySkill, DanceSkill, FaceSkill, KickSkill, QRCodeSkill, SkillContext
from .task_card import TaskCard


class Brain:
    def __init__(self, cerebellum: Any) -> None:
        self.cerebellum = cerebellum
        self.skills = {
            FaceSkill.name: FaceSkill(),
            QRCodeSkill.name: QRCodeSkill(),
            CarrySkill.name: CarrySkill(),
            KickSkill.name: KickSkill(),
            DanceSkill.name: DanceSkill(),
        }

    def register_skill(self, skill: Any) -> None:
        self.skills[skill.name] = skill

    def execute_task(self, card: TaskCard, observation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行单张任务卡，返回 FSM 历史与各技能执行结果。"""
        fsm = TaskFSM(name=card.task_id)

        def enter() -> None:
            self.cerebellum.home()
            print(f"  [Brain] 进入任务 {card.task_id}: {card.name}")

        def execute() -> Dict[str, Any]:
            results = []
            for skill_name in card.skills:
                skill = self.skills.get(skill_name)
                if skill is None:
                    raise KeyError(f"未注册的技能: {skill_name}")
                ctx = SkillContext(
                    task_id=card.task_id,
                    task_name=card.name,
                    params=card.params,
                    cerebellum=self.cerebellum,
                    observation=observation,
                )
                result = skill.run(ctx)
                results.append(result)
            return {"task_id": card.task_id, "results": results}

        return fsm.run(enter, execute)
