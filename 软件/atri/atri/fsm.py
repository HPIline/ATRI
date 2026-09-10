"""任务有限状态机：待机 → 任务进入 → 技能执行 → 结果反馈。"""
from __future__ import annotations

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


class TaskFSM:
    def __init__(self, name: str = "task-fsm", verbose: bool = True) -> None:
        self.name = name
        self.verbose = verbose
        self.state = FSMState.STANDBY
        self.history = [self.state]

    def transition(self, target: FSMState) -> FSMState:
        if target not in _TRANSITIONS[self.state]:
            raise FSMError(f"{self.name}: illegal transition {self.state.value} -> {target.value}")
        self.state = target
        self.history.append(target)
        if self.verbose:
            print(f"  [FSM:{self.name}] -> {target.value}")
        return self.state

    def run(self, enter: Callable[[], None], execute: Callable[[], Any]) -> Dict[str, Any]:
        """按状态机执行一个任务。enter/execute 抛异常时进入 ERROR 并重新抛出。"""
        self.transition(FSMState.ENTERING)
        try:
            enter()
            self.transition(FSMState.EXECUTING)
            result = execute()
            self.transition(FSMState.FEEDBACK)
            self.transition(FSMState.DONE)
            return {"ok": True, "result": result, "history": [s.value for s in self.history]}
        except Exception as exc:
            if self.state not in (FSMState.ERROR, FSMState.DONE):
                self.transition(FSMState.ERROR)
            return {"ok": False, "error": str(exc), "history": [s.value for s in self.history]}
