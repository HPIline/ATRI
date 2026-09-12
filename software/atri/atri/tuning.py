"""技能可调参数（tuning）：代码默认值 + ``config/<skill>.json`` 覆盖。

为什么要有这一层
----------------
机器人结构与零件**尚未定案**、且**没有实物**，所以现在写进代码的每一个控制常数
（对准死区、每轮偏航增益、抓取前的容许偏差……）都是**设计值 / 假设值**，
实物到手后必须标定回填。让"回填"= 改一行 JSON（而不是改代码、重新跑一遍推理），
是这一层存在的唯一理由：

    software/atri/config/carry.json
    {"deadband_cm": 1.5, "step_gain": 0.8}

优先级（高 → 低）：**任务卡 params** > ``config/<skill>.json`` > **代码默认值**。
前者是"这次任务要什么"（赛题给的），后者是"这台机器怎么动"（我们标定的），
两件事分开放，谁改了哪一层一眼能看出来。

设计约束（写给以后改这里的人）
------------------------------
- 只有一层字典，不做嵌套：联调时要能一眼看完。
- 缺键 = 用默认值；**写错的键告警但不抛异常**——配置文件不该把整张任务卡炸掉。
- 类型不符、非有限数、该正不正 → 回落到默认值并记一条 ``warnings``，不静默。
- **每次调用重新读文件**：改完 JSON 立刻生效，不用重启（联调常态）。
- ``ATRI_TUNING_DIR`` 可指向别的目录（现场联调不动仓库里的文件）。
- 文件不存在**不算错**：那就是"还没标定，用设计值"，`source_exists=False` 会说清。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
ENV_TUNING_DIR = "ATRI_TUNING_DIR"


def tuning_dir(path: Optional[str | Path] = None) -> Path:
    """tuning 文件所在目录：显式参数 > ``ATRI_TUNING_DIR`` > ``<包>/config``。"""
    if path is not None:
        return Path(path)
    env = (os.environ.get(ENV_TUNING_DIR) or "").strip()
    return Path(env) if env else CONFIG_DIR


def tuning_path(skill: str, path: Optional[str | Path] = None) -> Path:
    """某个技能的可调参数文件路径（``config/<skill>.json``）。"""
    return tuning_dir(path) / f"{skill}.json"


@dataclass(frozen=True)
class Tuning:
    """一次加载的结果：合并后的值 + 值从哪来 + 被拒的键。

    技能只用 ``values``；报告/评测工具用 ``provenance()`` 说明"这些数字是
    设计值还是标定值"，避免把没标定的参数当成实测能力写进材料。
    """

    skill: str
    values: Dict[str, Any]
    defaults: Dict[str, Any]
    source_path: Path
    source_exists: bool
    overridden: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = field(default=())

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def is_overridden(self, key: str) -> bool:
        """该键是否来自 tuning 文件（而不是代码默认值）。"""
        return key in self.overridden

    def provenance(self) -> str:
        """一行说明：值是标定回填的还是仍是代码里写的设计值。"""
        if not self.source_exists:
            return f"{self.skill}: 无 {self.source_path.name} → 全部为**代码默认值（设计值）**"
        if not self.overridden:
            return f"{self.skill}: 有 {self.source_path.name} 但未覆盖任何键 → 全部为代码默认值"
        return (
            f"{self.skill}: {self.source_path.name} 覆盖 "
            + "、".join(self.overridden)
            + "；其余为代码默认值"
        )


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _validate(key: str, value: Any, default: Any) -> Tuple[bool, Any, Optional[str]]:
    """按默认值的类型/正负性校验覆盖值；返回 ``(是否接受, 归一化值, 告警)``。"""
    want = _kind(default)
    got = _kind(value)
    if want == "bool":
        if got != "bool":
            return False, default, f"{key}: 期望 bool，收到 {got}（{value!r}）"
        return True, bool(value), None
    if want in ("int", "float"):
        if isinstance(value, bool) or got not in ("int", "float"):
            return False, default, f"{key}: 期望数值，收到 {got}（{value!r}）"
        number = float(value)
        if not math.isfinite(number):
            return False, default, f"{key}: 必须是有限数值，收到 {value!r}"
        # 默认值该正就保持正：0 当分母这类错误不该由配置文件引入。
        if float(default) > 0.0 and number <= 0.0:
            return False, default, f"{key}: 必须 > 0（默认 {default}），收到 {value!r}"
        if float(default) >= 0.0 and number < 0.0:
            return False, default, f"{key}: 必须 ≥ 0（默认 {default}），收到 {value!r}"
        if want == "int":
            # 非整数**不能静默取整**：2.5 被悄悄变成 2，现场会以为"写了就生效了"。
            if not number.is_integer():
                return False, default, f"{key}: 必须是整数，收到 {value!r}（不静默取整）"
            return True, int(number), None
        return True, number, None
    if want == "str":
        if got != "str":
            return False, default, f"{key}: 期望字符串，收到 {got}（{value!r}）"
        return True, str(value), None
    return False, default, f"{key}: 默认值类型 {want} 不支持覆盖（跳过）"


def load_tuning(
    skill: str,
    defaults: Mapping[str, Any],
    path: Optional[str | Path] = None,
    warn: Optional[Any] = None,
) -> Tuning:
    """读 ``config/<skill>.json`` 并按类型/范围覆盖 ``defaults``。

    永远不会抛异常：文件缺失、JSON 坏、键写错、值非法都只是"这次用默认值"
    ＋一条告警。理由见模块 docstring——联调现场不该因为一个逗号让整场演示停摆。
    ``warn`` 传 None 时不打印（评测工具要安静的、机器可读的输出）。
    """
    source = tuning_path(skill, path)
    defaults_dict = dict(defaults)
    warnings: list = []
    overridden: list = []

    def _warn(message: str) -> None:
        warnings.append(message)
        if warn is not None:
            warn(f"  [tuning:{skill}] {message}")

    data: Any = None
    exists = source.exists()
    if exists:
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _warn(f"{source.name} 读取失败（{type(exc).__name__}: {exc}）→ 全部用默认值")
            data = None
        if data is not None and not isinstance(data, dict):
            _warn(f"{source.name} 顶层必须是对象，收到 {type(data).__name__} → 全部用默认值")
            data = None
    if isinstance(data, dict):
        # 注释键：JSON 没有注释语法，约定 "_" 开头（如 "_note"）为说明文字。
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if key not in defaults_dict:
                _warn(f"未知键 {key!r}（不在 {skill} 的可调项里）→ 忽略")
                continue
            ok, normalized, message = _validate(key, value, defaults_dict[key])
            if not ok:
                _warn(f"{message} → 用默认值 {defaults_dict[key]!r}")
                continue
            defaults_dict[key] = normalized
            overridden.append(key)

    return Tuning(
        skill=skill,
        values=defaults_dict,
        defaults=dict(defaults),
        source_path=source,
        source_exists=exists,
        overridden=tuple(overridden),
        warnings=tuple(warnings),
    )


def load_tuning_values(
    skill: str,
    defaults: Mapping[str, Any],
    path: Optional[str | Path] = None,
    warn: Optional[Any] = None,
) -> Dict[str, Any]:
    """只要合并后的字典时的便捷入口。"""
    return load_tuning(skill, defaults, path=path, warn=warn).values


def param_or(
    params: Mapping[str, Any],
    tuning: Mapping[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    """按「任务卡 > tuning 文件 > 代码默认值」取值。

    技能里所有 ``ctx.params.get(...)`` 都该走这里：这样"现场改任务卡"与
    "标定这台机器"两条路都通，且优先级只有一处定义。
    """
    if key in params and params[key] is not None:
        return params[key]
    if key in tuning and tuning[key] is not None:
        return tuning[key]
    return default


TUNING_VERSION = 1


def dump_template(skill: str, defaults: Mapping[str, Any], notes: Optional[Mapping[str, str]] = None) -> str:
    """按默认值生成一份带说明的 tuning 文件内容（用于"复制到现场改"）。"""
    notes = notes or {}
    body: Dict[str, Any] = {"_note": f"{skill} 技能可调参数：实物/相机到位后在这里标定回填；缺键即用代码默认值。"}
    for key in sorted(defaults):
        if key in notes:
            body[f"_{key}_note"] = notes[key]
        body[key] = defaults[key]
    return json.dumps(body, ensure_ascii=False, indent=2) + "\n"
