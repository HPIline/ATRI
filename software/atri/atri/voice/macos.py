"""macOS 本地 TTS：使用系统 say 命令。"""
from __future__ import annotations

import subprocess
import sys
from typing import Any, Callable, List, Optional

from .base import TTS, VoiceError


class MacOSTTS(TTS):
    name = "macos-say"

    def __init__(
        self,
        is_darwin: Optional[bool] = None,
        runner: Optional[Callable[..., Any]] = None,
        voice: Optional[str] = None,
    ) -> None:
        self.is_darwin = sys.platform == "darwin" if is_darwin is None else is_darwin
        self.runner = runner or subprocess.run
        self.voice = voice

    def speak(self, text: str) -> None:
        if not self.is_darwin:
            raise VoiceError("MacOSTTS 仅在 macOS 上可用，Windows 请接入相应 TTS 引擎")
        cmd: List[str] = ["say"]
        if self.voice:
            cmd += ["-v", self.voice]
        cmd.append(text)
        completed = self.runner(cmd, check=False)
        code = getattr(completed, "returncode", 0)
        if code != 0:
            raise VoiceError(f"say 执行失败（退出码 {code}）：{text}")
        print(f"  [TTS:say] {text}")
