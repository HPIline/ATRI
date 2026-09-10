"""标准件参数库（CAD 建模的输入）。

**本文件是"外部世界知识"的落地处。**
参数来自部件库/厂商资料，每一项都标注 `verify` 状态：
    verified     已核对官方图纸或实物实测
    provisional  来自厂商公开规格或同级别典型值，未实物核对
    unknown      尚无数据，建模时用占位值并在图纸标注

⚠️ 建模前必须确认用到的参数不是 unknown。`assert_verified()` 会在
构建时拦截：宁可构建失败，也不要产出一个基于臆测尺寸的零件。
"""
from __future__ import annotations

from typing import Any, Dict, List


class SpecError(RuntimeError):
    """标准件参数缺失或未经验证。"""


# --------------------------------------------------------------------------
# FDM 打印工艺容差（3D 打印件的配合基准）
# --------------------------------------------------------------------------
FDM = {
    "nozzle_mm": 0.4,
    "layer_height_mm": 0.2,
    "wall_count": 3,
    "wall_mm": 1.2,              # 3 × 0.4
    "min_wall_mm": 1.2,
    "clearance_loose_mm": 0.4,   # 活动配合（轴在孔里转）
    "clearance_snug_mm": 0.2,    # 定位配合（手压入）
    "clearance_press_mm": 0.05,  # 过盈配合（需敲入）
    "min_feature_mm": 0.8,       # 最小可靠特征
    "fillet_min_mm": 1.0,
    "fillet_struct_mm": 2.0,     # 承力件圆角
    "boss_od_factor": 2.0,       # 螺钉柱外径 = 2 × 螺钉直径
    "verify": "provisional",
    "source": "FDM 通用工艺经验值",
}


# --------------------------------------------------------------------------
# 紧固件
# --------------------------------------------------------------------------
FASTENERS: Dict[str, Dict[str, Any]] = {
    "M2": {
        "major_dia_mm": 2.0,
        "tap_drill_mm": 1.6,       # 自攻/热熔铜螺母底孔
        "clearance_hole_mm": 2.2,
        "head_dia_mm": 3.8,        # 内六角圆柱头
        "head_height_mm": 2.0,
        "verify": "provisional",
    },
    "M2.5": {
        "major_dia_mm": 2.5,
        "tap_drill_mm": 2.05,
        "clearance_hole_mm": 2.7,
        "head_dia_mm": 4.5,
        "head_height_mm": 2.5,
        "verify": "provisional",
        "note": "舵机厂商标配规格（飞特 STS 系列用 M2.5）",
    },
    "M3": {
        "major_dia_mm": 3.0,
        "tap_drill_mm": 2.5,
        "clearance_hole_mm": 3.2,
        "head_dia_mm": 5.5,
        "head_height_mm": 3.0,
        "verify": "provisional",
    },
}


# --------------------------------------------------------------------------
# 轴承（关节副轴支撑）
# --------------------------------------------------------------------------
BEARINGS: Dict[str, Dict[str, Any]] = {
    "MF105ZZ": {
        "type": "flanged_miniature_ball",
        "bore_mm": 5.0,
        "od_mm": 10.0,
        "width_mm": 4.0,
        "flange_od_mm": 11.6,
        "flange_width_mm": 0.8,
        "verify": "provisional",
        "note": "法兰微型轴承，适合打印件的薄壁轴承位",
    },
    "MR105ZZ": {
        "type": "miniature_ball",
        "bore_mm": 5.0,
        "od_mm": 10.0,
        "width_mm": 4.0,
        "verify": "provisional",
    },
    "608ZZ": {
        "type": "skate_bearing",
        "bore_mm": 8.0,
        "od_mm": 22.0,
        "width_mm": 7.0,
        "verify": "verified",
        "note": "最通用的标准件，货源极广",
    },
    "MR63ZZ": {
        "type": "miniature_ball",
        "bore_mm": 3.0,
        "od_mm": 6.0,
        "width_mm": 2.5,
        "verify": "provisional",
    },
}


# --------------------------------------------------------------------------
# 舵机
# --------------------------------------------------------------------------
SERVOS: Dict[str, Dict[str, Any]] = {
    "STS3215": {
        "vendor": "飞特 Feetech",
        "protocol": "TTL 半双工串行总线",
        "baud_bps": 1_000_000,
        "body_mm": [45.2, 24.7, 35.0],           # 长 × 宽 × 高
        "mass_g": 55.0,
        "rated_torque_nm": 1.0,
        "stall_torque_nm": 3.0,
        "speed_s_per_60deg": 0.18,
        "voltage_v": 12.0,

        # —— 机械接口（建模必需）——
        "horn_spline": "25T",
        "horn_spline_od_mm": 5.9,
        "horn_pcd_mm": 14.0,
        "horn_hole_count": 4,
        "horn_hole_thread": "M2.5",
        "horn_screw": "M3",
        "horn_verify": "provisional",
        "horn_note": "白皮书给出 Φ5.9 / 25T / Φ14 或 Φ16 节圆；"
                     "两个 PCD 值不一致，实物到手必须复测",

        "body_mount_hole_thread": "M2.5",
        "body_mount_spacing_mm": None,            # ← 未知
        "body_mount_verify": "unknown",
        "body_mount_note": "机身安装孔位间距未获得数据；"
                           "这是建模的**阻塞项**，必须实测",

        "shaft_dia_mm": 5.9,
        "cable_exit": "side",
        "verify": "provisional",
        "source": "外部部件库白皮书（Gemini）+ 厂商公开规格",
    },
}


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def assert_verified(entry: Dict[str, Any], name: str,
                    allow: List[str] | None = None) -> None:
    """确保参数不是 unknown；provisional 默认允许但会告警。"""
    allow = allow or ["verified", "provisional"]
    status = entry.get("verify", "unknown")
    if status not in allow:
        raise SpecError(
            f"{name} 的参数状态为 '{status}'，缺失关键尺寸，无法可靠建模。\n"
            f"  说明: {entry.get('note', entry.get('body_mount_note', '无'))}\n"
            f"  处理: 实测后回填 standards.py，或在零件里显式留占位并标注。"
        )


def servo(name: str) -> Dict[str, Any]:
    if name not in SERVOS:
        raise SpecError(f"未收录舵机 {name}")
    return SERVOS[name]


def servo_horn_interface(name: str) -> Dict[str, Any]:
    """舵机输出轴接口（舵盘侧），建模必需。"""
    s = servo(name)
    assert_verified(
        {"verify": s.get("horn_verify"), "note": s.get("horn_note")},
        f"{name} 舵盘接口",
    )
    return {
        "spline": s["horn_spline"],
        "spline_od_mm": s["horn_spline_od_mm"],
        "pcd_mm": s["horn_pcd_mm"],
        "hole_count": s["horn_hole_count"],
        "hole_thread": s["horn_hole_thread"],
        "screw": s["horn_screw"],
    }


def fastener(name: str) -> Dict[str, Any]:
    if name not in FASTENERS:
        raise SpecError(f"未收录紧固件 {name}")
    return FASTENERS[name]


def bearing(name: str) -> Dict[str, Any]:
    if name not in BEARINGS:
        raise SpecError(f"未收录轴承 {name}")
    return BEARINGS[name]


def summary() -> str:
    """打印所有标准件的验证状态，便于快速看出哪些还缺数据。"""
    lines = ["标准件参数状态", "=" * 58]
    lines.append(f"{'名称':<16}{'状态':<14}{'备注'}")
    lines.append("-" * 58)
    for name, s in SERVOS.items():
        lines.append(f"{name:<16}{s.get('verify','?'):<14}"
                     f"舵盘 {s.get('horn_verify','?')} / "
                     f"机身孔 {s.get('body_mount_verify','?')}")
    for name, f in FASTENERS.items():
        lines.append(f"{name:<16}{f.get('verify','?'):<14}紧固件")
    for name, b in BEARINGS.items():
        lines.append(f"{name:<16}{b.get('verify','?'):<14}{b.get('type','')}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
