"""娱乐交互技能：离线关键词 -> 22 DOF 短舞。可选播放本地 wav。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import MAX_BARS
from .base import Skill, SkillContext, as_int_in_range, failed, perception_data

DEFAULT_KEYWORDS = ("跳舞", "挥手", "鞠躬")
UNKNOWN_SPEECH = "我没听清"


def _play_wav(path: Path) -> str:
    """尽力播放一段本地 wav。没有播放器就标 unavailable，不假装节拍同步。"""
    player = shutil.which("afplay") or shutil.which("ffplay") or shutil.which("aplay")
    if player is None:
        return "unavailable"
    cmd = [player, str(path)]
    if os.path.basename(player) == "ffplay":
        cmd = [player, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
    try:
        subprocess.run(cmd, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return "played"


class DanceSkill(Skill):
    name = "dance"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "speech", optional=True)
        if reason:
            return failed(self.name, reason)

        allowed = ctx.params.get("keywords") or list(DEFAULT_KEYWORDS)
        if isinstance(allowed, str):
            allowed = [allowed]
        allowed = [str(item) for item in allowed]

        keyword = obs.get("keyword")
        source = "perception"
        if not keyword:
            if ctx.channel_ready("speech"):
                ctx.tts(UNKNOWN_SPEECH)
                return failed(self.name, "语音通道已接入但未识别到关键词")
            keyword = ctx.params.get("keyword") or "跳舞"
            source = "params"
        keyword = str(keyword)
        if allowed and keyword not in allowed:
            ctx.tts(UNKNOWN_SPEECH)
            return failed(self.name, f"关键词 {keyword!r} 不在白名单 {allowed}")

        bars = as_int_in_range(ctx.params.get("bars", 2), 1, MAX_BARS)
        if bars is None:
            return failed(
                self.name, f"bars 非法: {ctx.params.get('bars')!r}（应为 1..{MAX_BARS} 整数）"
            )

        audio_status = "skipped"
        audio_path: Optional[str] = ctx.params.get("audio")
        if audio_path:
            wav = Path(str(audio_path))
            if wav.exists():
                audio_status = _play_wav(wav)
            else:
                audio_status = "missing"

        print(f"  [Dance] 识别到离线关键词: {keyword} (source={source})")
        dance_result = ctx.cerebellum.dance(bars=bars)
        ctx.tts("舞蹈结束，谢谢观看")
        return {
            "skill": self.name,
            "status": "ok",
            "keyword": keyword,
            "source": source,
            "audio": audio_status,
            "dance": dance_result,
        }
