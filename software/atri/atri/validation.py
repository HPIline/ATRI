"""通用取值校验：把外部输入（二维码 payload / 感知观测 / CLI 参数）转成可信的数值。

**为什么单独一个模块**：这些函数原本放在 ``atri/skills/base.py`` 里，
于是 ``qrgen → path_plan → skills.base`` 这条导入链会把整个 ``skills`` 包拉起来，
再绕回 ``odometry → path_plan``，形成循环导入。它们本身与"技能"无关，
放在中立位置才是对的。``skills/base.py`` 仍然原样再导出，
所以既有的 ``from .base import as_finite_float`` 写法不受影响。

设计取向：**转换失败返回 None，绝不猜**。调用方必须显式处理 None（判失败），
因为把 ``"3"``、``True``、``NaN`` 悄悄当成合法数值，最终会变成赛场上的一次越界动作。
"""
from __future__ import annotations

import math
from typing import Any, Optional


def as_finite_float(value: Any) -> Optional[float]:
    """把观测/指令里的值转成有限 float；非数值或 NaN/Inf 返回 None。

    ``bool`` 显式拒绝：``True`` 在 Python 里等于 1，但"真"和"1 度"是两回事。
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def as_int_in_range(value: Any, low: int, high: int) -> Optional[int]:
    """解析指定区间内的整数值；bool、字符串、非整数浮点与越界值返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        return None
    return number if low <= number <= high else None
