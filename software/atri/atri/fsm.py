"""任务有限状态机：待机 → 任务进入 → 技能执行 → 结果反馈。"""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional


class FSMState(str, Enum):
    STANDBY = "STANDBY"
    ENTERING = "ENTERING"
    EXECUTING = "EXECUTING"
    FEEDBACK = "FEEDBACK"
    DONE = "DONE"
    ERROR = "ERROR"


_TRANSITIONS = {
    FSMState.STANDBY: {FSMState.ENTERING},
    FSMState.ENTERING: {FSMState.EXECUTING, FSMState.ERROR},
    FSMState.EXECUTING: {FSMState.FEEDBACK, FSMState.ERROR},
    FSMState.FEEDBACK: {FSMState.DONE, FSMState.ERROR},
    FSMState.DONE: set(),
    FSMState.ERROR: set(),
}


class FSMError(RuntimeError):
    pass


class TaskTimeoutError(RuntimeError):
    """任务执行超出 timeout_s 预算。"""


class TaskFSM:
    def __init__(self, name: str = "task-fsm", verbose: bool = True) -> None:
        self.name = name
        self.verbose = verbose
        self.state = FSMState.STANDBY
        self.history = [self.state]

    def reset(self) -> FSMState:
        """回到 STANDBY 并清空历史，允许同一实例复用。"""
        self.state = FSMState.STANDBY
        self.history = [self.state]
        return self.state

    def transition(self, target: FSMState) -> FSMState:
        if target not in _TRANSITIONS[self.state]:
            raise FSMError(f"{self.name}: illegal transition {self.state.value} -> {target.value}")
        self.state = target
        self.history.append(target)
        if self.verbose:
            print(f"  [FSM:{self.name}] -> {target.value}")
        return self.state

    def run(
        self,
        enter: Callable[[], None],
        execute: Callable[[], Any],
        timeout_s: Optional[float] = None,
        on_timeout: Optional[Callable[[], Any]] = None,
        abort_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """按状态机执行一个任务，返回结果 dict（异常转 ok=False，不重新抛出）。

        enter/execute 抛异常时进入 ERROR，错误信息带异常类型。
        timeout_s 为执行预算：到期只置位 ``self.abort_event``（不直接碰机器人），
        长轨迹由被调用方在帧边界协作中止；复位回调 on_timeout 只由主线程在
        execute 返回/抛出后调用一次，绝不从定时器线程执行。
        ``self.abort_event`` 是本次运行的 threading.Event，供协作式中止使用。
        execute 返回后仍判定为超时并进入 ERROR。
        实例处于 DONE/ERROR 时自动复位，可在同一实例上连续 run。
        """
        if self.state in (FSMState.DONE, FSMState.ERROR):
            self.reset()

        timed_out = False
        reset_done = False
        deadline = None
        timer = None
        event = abort_event if abort_event is not None else threading.Event()
        self.abort_event = event

        def reset_target() -> None:
            nonlocal reset_done
            if reset_done:
                return
            reset_done = True
            if on_timeout is not None:
                try:
                    on_timeout()
                except Exception as exc:  # 复位失败不能吞掉超时判定
                    print(f"  [FSM:{self.name}] 超时复位失败: {type(exc).__name__}: {exc}")

        if timeout_s is not None:
            deadline = time.monotonic() + float(timeout_s)

            def expire() -> None:
                nonlocal timed_out
                timed_out = True
                # 只置位，绝不从定时器线程调用 on_timeout：机器人动作必须留在主线程
                event.set()

            timer = threading.Timer(float(timeout_s), expire)
            timer.daemon = True
            timer.start()

        try:
            try:
                self.transition(FSMState.ENTERING)
                enter()
                self.transition(FSMState.EXECUTING)
                if timed_out or (deadline is not None and time.monotonic() > deadline):
                    raise TaskTimeoutError(
                        f"任务超时: 超过 {timeout_s}s 执行预算（技能开始前）"
                    )
                result = execute()
                if timed_out or (deadline is not None and time.monotonic() > deadline):
                    raise TaskTimeoutError(f"任务超时: 超过 {timeout_s}s 执行预算")
                self.transition(FSMState.FEEDBACK)
                self.transition(FSMState.DONE)
                return {
                    "ok": True,
                    "result": result,
                    "history": [s.value for s in self.history],
                }
            except Exception as exc:
                if isinstance(exc, TaskTimeoutError) or timed_out:
                    reset_target()
                if self.state not in (FSMState.ERROR, FSMState.DONE):
                    self.transition(FSMState.ERROR)
                return {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "history": [s.value for s in self.history],
                }
        finally:
            if timer is not None:
                timer.cancel()
