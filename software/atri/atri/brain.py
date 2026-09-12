"""大脑计算层：任务注册、FSM 调度与技能执行。"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from .fsm import TaskFSM, TaskTimeoutError
from .skills import DEFAULT_SKILLS, SkillContext
from .task_card import TaskCard


class Brain:
    def __init__(
        self,
        cerebellum: Any,
        perception: Any = None,
        tts: Any = None,
        gait: Optional[Dict[str, Any]] = None,
        fsm_verbose: bool = True,
        face_recognizer: Any = None,
        frame_source: Any = None,
    ) -> None:
        self.cerebellum = cerebellum
        self.perception = perception
        self.tts = tts
        self.gait = dict(gait or {})
        self.fsm_verbose = fsm_verbose
        # 真识别通路（T-01）：两者都非空时 face 技能走真识别而不是 Mock 观测
        self.face_recognizer = face_recognizer
        self.frame_source = frame_source
        self.skills = {name: cls() for name, cls in DEFAULT_SKILLS.items()}

    def register_skill(self, skill: Any) -> None:
        self.skills[skill.name] = skill

    def execute_task(
        self, card: TaskCard, observation: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """执行单张任务卡，返回 FSM 历史与各技能执行结果。

        技能返回 status != "ok" 时任务判定失败（ok=False）并中止后续技能；
        执行超出 card.timeout_s 预算时进入 ERROR：定时器只置位中止信号，
        长轨迹（Cerebellum.execute_trajectory）在帧边界协作停止，复位 home()
        由主线程在技能返回后调用一次。注意：阻塞式第三方调用无法被抢占，
        需等其自行返回后才复位。
        """
        fsm = TaskFSM(name=card.task_id, verbose=self.fsm_verbose)
        abort_event = threading.Event()
        set_abort = getattr(self.cerebellum, "set_abort_event", None)
        if set_abort is not None:
            set_abort(abort_event)

        def enter() -> None:
            self.cerebellum.home()
            print(f"  [Brain] 进入任务 {card.task_id}: {card.name}")

        def execute() -> Dict[str, Any]:
            results = []
            failures = []
            for skill_name in card.skills:
                # 用 FSM 定时器置位的中止信号判超时，不再自算 deadline：
                # execute() 在 enter() 之后才开始，自算的基准比定时器晚了整个
                # enter()（含首次 home() 写 22 路总线），会放过一个技能。
                if abort_event.is_set():
                    raise TaskTimeoutError(
                        f"任务超时: 超过 {card.timeout_s:g}s 预算，中止技能 {skill_name}"
                    )
                skill = self.skills.get(skill_name)
                if skill is None:
                    raise KeyError(f"未注册的技能: {skill_name}")
                ctx = SkillContext(
                    task_id=card.task_id,
                    task_name=card.name,
                    params=card.params,
                    cerebellum=self.cerebellum,
                    observation=observation,
                    perception=self.perception,
                    tts_engine=self.tts,
                    gait=self.gait,
                    face_recognizer=self.face_recognizer,
                    frame_source=self.frame_source,
                )
                result = skill.run(ctx)
                results.append(result)
                if not isinstance(result, dict) or result.get("status") != "ok":
                    reason = result.get("reason") if isinstance(result, dict) else repr(result)
                    failures.append(f"{skill_name}: {reason}")
                    break
            return {"task_id": card.task_id, "results": results, "failures": failures}

        try:
            outcome = fsm.run(
                enter,
                execute,
                timeout_s=card.timeout_s,
                on_timeout=self.cerebellum.home,
                abort_event=abort_event,
            )
        finally:
            if set_abort is not None:
                set_abort(None)
        payload = outcome.get("result")
        failures = payload.get("failures") if isinstance(payload, dict) else None
        if failures:
            outcome["ok"] = False
            outcome["error"] = "技能执行失败: " + "; ".join(str(item) for item in failures)
        return outcome
