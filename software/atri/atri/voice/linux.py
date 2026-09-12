"""Linux 本地 TTS：系统 piper / espeak-ng / espeak / spd-say。"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Callable, List, Mapping, Optional, Sequence

from .base import TTS, VoiceError

# 自动探测顺序；ATRI_TTS 可强制其中之一或 mock。
PROBE_ORDER = ("piper", "espeak-ng", "espeak", "spd-say")
FORCED_ENGINES = frozenset(PROBE_ORDER + ("mock",))


def _as_which(
    which: Optional[Callable[..., Optional[str]]],
    looks: Optional[Sequence[str]],
) -> Callable[..., Optional[str]]:
    if looks is not None:
        available = set(looks)

        def from_looks(cmd: str, *args: Any, **kwargs: Any) -> Optional[str]:
            return cmd if cmd in available else None

        return from_looks
    if which is not None:
        return which
    return shutil.which


def detect_linux_engine(
    which: Callable[..., Optional[str]],
    env: Mapping[str, str],
) -> Optional[str]:
    """返回引擎名：强制值、PATH 命中，或 mock/None（无引擎）。"""
    forced = (env.get("ATRI_TTS") or "").strip().lower()
    if forced:
        if forced in FORCED_ENGINES:
            return forced
        return "mock"
    for name in PROBE_ORDER:
        if which(name):
            return name
    return None


class LinuxTTS(TTS):
    name = "linux-tts"

    def __init__(
        self,
        runner: Optional[Callable[..., Any]] = None,
        which: Optional[Callable[..., Optional[str]]] = None,
        looks: Optional[Sequence[str]] = None,
        env: Optional[Mapping[str, str]] = None,
        engine: Optional[str] = None,
        voice: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.runner = runner or subprocess.run
        self.which = _as_which(which, looks)
        self.env = os.environ if env is None else env
        self.voice = voice
        self.model = model if model is not None else (self.env.get("ATRI_PIPER_MODEL") or None)
        self.spoken: List[str] = []
        if engine is not None:
            self.engine = engine
        else:
            self.engine = detect_linux_engine(self.which, self.env)
        if self.engine and self.engine != "mock":
            self.name = f"linux-{self.engine}"
        else:
            self.name = "linux-mock"

    def speak(self, text: str) -> None:
        if not self.engine or self.engine == "mock":
            self.spoken.append(text)
            print(f"  [TTS:linux-mock] {text}")
            return
        cmd = self._command(text)
        kwargs: dict = {"check": False}
        if self.engine == "piper":
            kwargs["input"] = text
            kwargs["text"] = True
        try:
            completed = self.runner(cmd, **kwargs)
        except OSError as exc:
            raise VoiceError(f"{self.engine} 执行失败：{exc}") from exc
        code = getattr(completed, "returncode", 0)
        if code != 0:
            raise VoiceError(f"{self.engine} 执行失败（退出码 {code}）：{text}")
        self.spoken.append(text)
        print(f"  [TTS:{self.engine}] {text}")

    def _command(self, text: str) -> List[str]:
        engine = self.engine
        if engine == "piper":
            cmd = ["piper"]
            if self.model:
                cmd += ["--model", self.model]
            return cmd
        if engine in ("espeak", "espeak-ng"):
            cmd = [engine]
            if self.voice:
                cmd += ["-v", self.voice]
            cmd.append(text)
            return cmd
        if engine == "spd-say":
            return ["spd-say", "-w", text]
        raise VoiceError(f"未知 TTS 引擎：{engine}")
