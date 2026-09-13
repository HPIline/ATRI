"""娱乐交互技能：离线关键词 -> 20 DOF 短舞。可选播放本地 wav。

参数走 :mod:`atri.tuning`：**任务卡 params > ``config/dance.json`` > 代码默认值**
（与 ``skills/carry.py`` / ``skills/kick.py`` 同一口径）。默认数值与行为保持不变：
本文件只加一层"可标定"的读取与出处标注，不动判定逻辑。

为什么要可标定：白名单里放哪些说法、听不清说什么、跳几小节，都是**这台机器/这个现场**
的事，实物与引擎到位后应当**改 JSON 而不是改代码**（见 `config/dance.json`）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from ..config import MAX_BARS
from ..tuning import Tuning, effective_overrides, load_tuning, param_or, tuning_source_label
from .base import Skill, SkillContext, as_int_in_range, failed, perception_data

DEFAULT_KEYWORDS = ("跳舞", "挥手", "鞠躬")
UNKNOWN_SPEECH = "我没听清"

# 代码默认值 = 设计值（未标定）。键名即 config/dance.json 里可覆盖的键。
DANCE_DEFAULTS: Dict[str, Any] = {
    # 关键词白名单：**只决定"判定"，不决定"能不能听见"**（听见与否取决于识别引擎）。
    "keywords": "、".join(DEFAULT_KEYWORDS),
    # 听不清 / 未命中白名单时的播报语。
    "unknown_speech": UNKNOWN_SPEECH,
    # 一次舞蹈的默认小节数（任务卡 params.bars 优先）。
    "bars": 2,
    # 小节数上限：只能**收紧**，硬上限仍是 config.MAX_BARS（拓扑与时长约束）。
    "bars_max": MAX_BARS,
    # 是否播放任务卡 params.audio 指定的伴奏（本机没有播放器时结果里是 unavailable）。
    "audio_enabled": True,
}


def _parse_keywords(raw: Any, default: Dict[str, Any]) -> Tuple[str, ...]:
    """白名单解析：list/tuple 直接用；字符串按「、,，/ 空格」拆。

    tuning 文件只支持标量，所以 JSON 里写成 ``"跳舞、跳个舞"`` 这种字符串；
    空串/非法值回落到代码默认值（不因为一处笔误让技能拒识所有词）。
    """
    if isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw]
    elif isinstance(raw, str):
        text = raw.replace("，", "、").replace(",", "、").replace("/", "、").replace(" ", "、")
        items = [part.strip() for part in text.split("、")]
    else:
        items = []
    items = [item for item in items if item]
    if not items:
        return tuple(str(item) for item in str(default["keywords"]).split("、") if item)
    return tuple(items)


def _fail(t: Tuning, reason: str, params: Any = None) -> Dict[str, Any]:
    """失败结果也带参数出处与告警：否则现场"改了没生效"查不出来（与 carry/kick 同口径）。"""
    result = failed("dance", reason)
    result["tuning_source"] = tuning_source_label(t, params)
    result["tuning_overridden"] = list(effective_overrides(t, params))
    result["tuning_warnings"] = list(t.warnings)
    return result


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
        # warn=print：配置写错时现场要看得见（与 carry/kick 同口径）。
        t = load_tuning("dance", DANCE_DEFAULTS, warn=print)
        tuning = t.values
        def fail(reason: str) -> Dict[str, Any]:
            """本技能的失败出口：绑好本次的任务卡 params（出处标注要用）。"""
            return _fail(t, reason, ctx.params)

        unknown_speech = str(param_or(ctx.params, tuning, "unknown_speech", UNKNOWN_SPEECH))

        obs, reason = perception_data(ctx, "speech", optional=True)
        if reason:
            return fail(reason)

        allowed = _parse_keywords(
            param_or(ctx.params, tuning, "keywords", DANCE_DEFAULTS["keywords"]), DANCE_DEFAULTS
        )

        keyword = obs.get("keyword")
        source = "perception"
        if not keyword:
            if ctx.channel_ready("speech"):
                ctx.tts(unknown_speech)
                return fail("语音通道已接入但未识别到关键词")
            keyword = ctx.params.get("keyword") or "跳舞"
            source = "params"
        keyword = str(keyword)
        if allowed and keyword not in allowed:
            ctx.tts(unknown_speech)
            return fail(f"关键词 {keyword!r} 不在白名单 {list(allowed)}")

        # bars_max 只能收紧硬上限（MAX_BARS）：配置不该放宽拓扑约束。
        raw_max = as_int_in_range(param_or(ctx.params, tuning, "bars_max", MAX_BARS), 1, MAX_BARS)
        bars_max = min(raw_max if raw_max is not None else MAX_BARS, MAX_BARS)
        default_bars = as_int_in_range(
            param_or(ctx.params, tuning, "bars", DANCE_DEFAULTS["bars"]), 1, bars_max
        )
        bars = as_int_in_range(ctx.params.get("bars", default_bars), 1, bars_max)
        if bars is None:
            return fail(
                f"bars 非法: {ctx.params.get('bars')!r}（应为 1..{bars_max} 整数）"
            )

        audio_status = "skipped"
        enabled = param_or(ctx.params, tuning, "audio_enabled", True)
        audio_enabled = enabled if isinstance(enabled, bool) else True
        audio_path: Optional[str] = ctx.params.get("audio")
        if audio_path and not audio_enabled:
            audio_status = "disabled"
        elif audio_path:
            wav = Path(str(audio_path))
            if wav.exists():
                audio_status = _play_wav(wav)
            else:
                audio_status = "missing"

        # —— 诚实记账：这次关键词到底是"听出来的"还是"Mock 吐出来的" ——
        # 观测自报 asr_engine 才算真识别前端；没自报的一律按 Mock 记账（不是识别）。
        # 参数兜底（source=params）根本没有识别过 → engine=none。
        if source == "params":
            engine, real = "none", False
        else:
            declared = str(obs.get("asr_engine") or "").strip()
            if declared:
                engine = declared
                real = bool(obs.get("asr_real", declared not in ("mock", "none")))
            else:
                engine, real = "mock", False

        print(
            f"  [Dance] 关键词 {keyword} | 来源 {source} | 引擎 {engine} | 真识别 {real} | {bars} 小节"
        )
        dance_result = ctx.cerebellum.dance(bars=bars)
        ctx.tts("舞蹈结束，谢谢观看")
        return {
            "skill": self.name,
            "status": "ok",
            "keyword": keyword,
            "source": source,
            "audio": audio_status,
            "bars": bars,
            "dance": dance_result,
            "asr_engine": engine,
            "asr_real": real,
            # 参数出处：让报告能说清"这些是设计值还是标定值"。
            "tuning_source": tuning_source_label(t, ctx.params),
            "tuning_overridden": list(effective_overrides(t, ctx.params)),
            "tuning_warnings": list(t.warnings),
        }
