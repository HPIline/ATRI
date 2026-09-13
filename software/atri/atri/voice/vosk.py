"""可选离线关键词后端：Vosk 小模型风格，惰性导入。

核心包**不依赖** vosk。本模块在 import 时也不 import vosk：
只有构造后调用 ``available()`` / ``recognize()`` 才尝试加载引擎与模型。

没装 vosk、没设模型路径时：
- ``available()`` 为 False
- ``recognize()`` 抛 ``VoiceError``
- ``build_recognizer()`` 返回 None（不静默降级成 Mock）

这是给样机 / 开发机后装引擎用的；无引擎时 T-05 仍走
``MockKeywordRecognizer`` 或任务卡 ``params`` 兜底。
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional, Sequence

from .base import KeywordRecognizer, VoiceError
from ..perception.base import PerceptionResult

# 与 DanceSkill 白名单对齐；评测与识别共用这一份。
DEFAULT_KEYWORDS = ("跳舞", "挥手", "鞠躬")
DEFAULT_SAMPLE_RATE = 16000
ENV_MODEL = "ATRI_VOSK_MODEL"


def match_keyword(text: str, keywords: Sequence[str]) -> str:
    """从转写文本里取白名单命中：优先最长词，避免短词误吞。"""
    blob = str(text or "").strip()
    if not blob or not keywords:
        return ""
    hits = [str(word) for word in keywords if str(word) and str(word) in blob]
    if not hits:
        return ""
    hits.sort(key=len, reverse=True)
    return hits[0]


def vosk_available(vosk_module: Any = None, model_path: Optional[str] = None) -> bool:
    """探测引擎 + 模型是否都在；缺任一项都算不可用。"""
    rec = VoskKeywordRecognizer(model_path=model_path, vosk_module=vosk_module)
    return rec.available()


class VoskKeywordRecognizer(KeywordRecognizer):
    """Vosk 离线关键词识别。第三方包与模型都是可选的。

    ``vosk_module`` / ``model`` 仅供测试注入假引擎；正常使用传 None，
    首次 ``available()`` / ``recognize()`` 再 import vosk。
    """

    name = "vosk"

    def __init__(
        self,
        model_path: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        keywords: Sequence[str] = DEFAULT_KEYWORDS,
        vosk_module: Any = None,
        model: Any = None,
    ) -> None:
        self.model_path = model_path if model_path is not None else (os.environ.get(ENV_MODEL) or "")
        self.sample_rate = int(sample_rate)
        self.keywords = tuple(str(item) for item in keywords)
        self._vosk = vosk_module
        self._model = model
        self._load_error: Optional[str] = None

    def available(self) -> bool:
        try:
            self._get_vosk()
            self._get_model()
            return True
        except VoiceError as exc:
            self._load_error = str(exc)
            return False

    def recognize(self, audio: Any = None) -> str:
        """识别一段 PCM 音频；未命中白名单时返回空串，不编造关键词。"""
        rec = self._make_recognizer()
        pcm = _as_pcm16(audio)
        if not pcm:
            return ""
        try:
            rec.AcceptWaveform(pcm)
        except Exception as exc:  # pragma: no cover - 引擎内部错误
            raise VoiceError(f"vosk 识别失败：{exc}") from exc
        payload = _result_payload(rec)
        text = str(payload.get("text") or payload.get("partial") or "")
        return match_keyword(text, self.keywords)

    def _get_vosk(self) -> Any:
        if self._vosk is not None:
            return self._vosk
        try:
            import vosk  # type: ignore
        except ImportError as exc:
            raise VoiceError(
                "vosk 未安装：请在项目虚拟环境中安装 vosk（核心包不依赖它，禁止装到系统路径）"
            ) from exc
        self._vosk = vosk
        return vosk

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        vosk = self._get_vosk()
        path = str(self.model_path or "").strip()
        if not path:
            raise VoiceError(
                f"未指定 Vosk 模型路径：设置环境变量 {ENV_MODEL} 或构造时传入 model_path"
            )
        if not os.path.isdir(path):
            raise VoiceError(f"Vosk 模型目录不存在: {path}")
        try:
            self._model = vosk.Model(path)
        except Exception as exc:
            raise VoiceError(f"Vosk 模型加载失败: {path} ({exc})") from exc
        return self._model

    def _make_recognizer(self) -> Any:
        vosk = self._get_vosk()
        model = self._get_model()
        grammar = json.dumps(list(self.keywords), ensure_ascii=False)
        try:
            return vosk.KaldiRecognizer(model, self.sample_rate, grammar)
        except TypeError:
            return vosk.KaldiRecognizer(model, self.sample_rate)
        except Exception as exc:
            raise VoiceError(f"vosk KaldiRecognizer 创建失败：{exc}") from exc


class KeywordSpeechPerception:
    """把 KeywordRecognizer 接到感知通道 ``detect_speech``。

    没装引擎时 ``available()`` 为假，``detect_speech`` 返回 found=False，
    技能层据此失败，而不是假装听清了。name 不含 ``mock``，避免被当成常量后端。
    """

    name = "keyword-speech"

    def __init__(self, recognizer: KeywordRecognizer) -> None:
        self.recognizer = recognizer
        rec_name = str(getattr(recognizer, "name", "") or "keyword")
        self.name = f"speech-{rec_name}"

    def available(self) -> bool:
        method = getattr(self.recognizer, "available", None)
        if method is None:
            return True
        return bool(method())

    def detect_speech(self, audio: Any = None) -> PerceptionResult:
        if not self.available():
            detail = getattr(self.recognizer, "_load_error", None) or "离线识别引擎不可用"
            return PerceptionResult(
                kind="speech",
                data={"found": False, "keyword": "", "error": detail},
                confidence=0.0,
            )
        try:
            keyword = str(self.recognizer.recognize(audio) or "").strip()
        except VoiceError as exc:
            return PerceptionResult(
                kind="speech",
                data={"found": False, "keyword": "", "error": str(exc)},
                confidence=0.0,
            )
        found = bool(keyword)
        return PerceptionResult(
            kind="speech",
            data={"keyword": keyword, "found": found},
            confidence=1.0 if found else 0.0,
        )


def build_recognizer(
    *,
    model_path: Optional[str] = None,
    keywords: Optional[Sequence[str]] = None,
    vosk_module: Any = None,
    model: Any = None,
) -> Optional[VoskKeywordRecognizer]:
    """有引擎+模型才返回识别器，否则 None。不静默降级成 Mock。"""
    rec = VoskKeywordRecognizer(
        model_path=model_path,
        keywords=DEFAULT_KEYWORDS if keywords is None else keywords,
        vosk_module=vosk_module,
        model=model,
    )
    return rec if rec.available() else None


def _as_pcm16(audio: Any) -> bytes:
    if audio is None:
        return b""
    if isinstance(audio, bytes):
        return audio
    if isinstance(audio, bytearray):
        return bytes(audio)
    tobytes = getattr(audio, "tobytes", None)
    if callable(tobytes):
        try:
            return tobytes()
        except Exception as exc:
            raise VoiceError(f"无法把 audio 转为 PCM 字节：{exc}") from exc
    raise VoiceError(f"audio 类型不支持: {type(audio).__name__}（需要 bytes / 有 tobytes 的缓冲）")


def _result_payload(rec: Any) -> dict:
    raw = None
    for name in ("FinalResult", "Result"):
        method = getattr(rec, name, None)
        if not callable(method):
            continue
        try:
            raw = method()
        except Exception:
            continue
        if raw:
            break
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"text": str(raw)}
    return data if isinstance(data, dict) else {"text": str(data)}
