"""连杆质量 / 质心 / 惯量：采购件点质量 + CAD 脚底板，不是样机称重。

网上常用做法（trimesh / urdf-mesh-inertia）：有网格就按体积×密度。本工作树
``out/sim/meshes`` 没有 STL，不能走那条。退一步：

* 每条关节连杆一只 STS3215（55 g，原点≈轴）；骨盆无舵机。
* 电池、Pi 放到胸腔图纸坐标。
* 脚：6061 底板（120×70×foot_t）+ TPU 鞋底预算，质心在踝下方近地面。
  不用 44 mm 碰撞盒当实心块去分结构质量。
* 剩下的铝/PETG/紧固件按**非脚**包围盒体积分配；沿子关节方向放结构质心。

惯量绕质心（Webots ``inertiaMatrix`` 也是绕 CoM）。
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Sequence, Tuple

from .profile import ELECTRONICS, K, MASS, MATERIALS, SERVO

# STS3215 壳体约 23×36×29 mm，不是质点（否则脚上 izz=0）。
SERVO_BOX_M = (0.023, 0.036, 0.029)

# 结构预算（g）：profile 单一事实来源。TPU 全部进两只脚，不参与体积分配。
STRUCTURE_G = (
    MASS["structure_al_budget_g"]
    + MASS["petg_budget_g"]
    + MASS["tpu_budget_g"]
    + MASS["fastener_budget_g"]
)


def foot_plate_g() -> float:
    """一只脚 6061 底板：图纸长×宽×foot_t，不是 44 mm 实心盒。"""
    lx = K["foot_l"] / 10.0
    ly = K["foot_w"] / 10.0
    lz = MATERIALS["6061-T6"]["foot_t_mm"] / 10.0
    return lx * ly * lz * MATERIALS["6061-T6"]["density_g_cm3"]


def foot_tpu_g() -> float:
    return MASS["tpu_budget_g"] / 2.0


def remaining_structure_g() -> float:
    """铝+PETG+紧固件减去两块脚底板。TPU 已从 STRUCTURE 里划走。"""
    used_al = 2.0 * foot_plate_g()
    return (
        MASS["structure_al_budget_g"]
        + MASS["petg_budget_g"]
        + MASS["fastener_budget_g"]
        - used_al
    )


def _box_inertia_center(mass: float, sx: float, sy: float, sz: float) -> Tuple[float, float, float]:
    return (
        mass * (sy * sy + sz * sz) / 12.0,
        mass * (sx * sx + sz * sz) / 12.0,
        mass * (sx * sx + sy * sy) / 12.0,
    )


def _shift_inertia(
    ixx: float, iyy: float, izz: float, ixy: float, ixz: float, iyz: float,
    mass: float, dx: float, dy: float, dz: float,
) -> Tuple[float, float, float, float, float, float]:
    """平行轴：把绕点 p 的惯量搬到 p+d。d 是从当前原点指向新原点的向量。"""
    return (
        ixx + mass * (dy * dy + dz * dz),
        iyy + mass * (dx * dx + dz * dz),
        izz + mass * (dx * dx + dy * dy),
        ixy - mass * dx * dy,
        ixz - mass * dx * dz,
        iyz - mass * dy * dz,
    )


def extras_for(name: str) -> List[Tuple[float, float, float, float, float, float, float]]:
    """额外质量 (kg, x, y, z, sx, sy, sz m)。尺寸为 0 则当质点。"""
    points: List[Tuple[float, float, float, float, float, float, float]] = []
    if name == "torso":
        bat = ELECTRONICS["battery"]
        sbc = ELECTRONICS["sbc"]
        bx, by, bz = (v / 1000.0 for v in bat["position_mm"])
        px, py, pz = (v / 1000.0 for v in sbc["position_mm"])
        bw, bh, bd = (v / 1000.0 for v in bat["body_mm"])
        sw, sh = (v / 1000.0 for v in sbc["pcb_mm"][:2])
        st = sbc["pcb_mm"][2] / 1000.0
        points.append((float(bat["mass_g"]) / 1000.0, bx, by, bz, bw, bh, bd))
        points.append((float(sbc["mass_g"]) / 1000.0, px, py, pz, sw, sh, st))
    if "foot" in name:
        sole = -K["foot_to_ankle_z"] / 1000.0
        tpu_t = K["sole_t"] / 1000.0
        plate_t = MATERIALS["6061-T6"]["foot_t_mm"] / 1000.0
        lx = K["foot_l"] / 1000.0
        ly = K["foot_w"] / 1000.0
        points.append((foot_tpu_g() / 1000.0, 0.0, 0.0, sole + tpu_t / 2.0, lx, ly, tpu_t))
        points.append((foot_plate_g() / 1000.0, 0.0, 0.0, sole + tpu_t + plate_t / 2.0, lx, ly, plate_t))
    return points


def structure_com_m(
    name: str,
    child_origins_mm: Sequence[Sequence[float]],
) -> Tuple[float, float, float]:
    """结构质心：单子关节则取半长；脚的质量在 extras 里，这里返回原点。"""
    if "foot" in name:
        return (0.0, 0.0, 0.0)
    if len(child_origins_mm) == 1:
        x, y, z = (float(v) for v in child_origins_mm[0])
        return (x / 2000.0, y / 2000.0, z / 2000.0)
    return (0.0, 0.0, 0.0)


def link_inertial(
    name: str,
    box_m: Sequence[float],
    volume_share: float,
    has_servo: bool,
    structure_com: Sequence[float] = (0.0, 0.0, 0.0),
) -> Dict[str, object]:
    """返回 mass_kg、com_m、inertia 六元组、breakdown_g。"""
    sx, sy, sz = (float(v) for v in box_m)
    if "foot" in name:
        structure_kg = 0.0
    else:
        structure_kg = (remaining_structure_g() / 1000.0) * float(volume_share)
    servo_kg = (SERVO["mass_g"] / 1000.0) if has_servo else 0.0
    points = list(extras_for(name))
    extra_kg = sum(p[0] for p in points)
    mass = structure_kg + servo_kg + extra_kg
    if mass <= 0.0:
        raise ValueError(f"{name}: 质量不能为 0")

    scx, scy, scz = (float(v) for v in structure_com)
    mx = structure_kg * scx + servo_kg * 0.0
    my = structure_kg * scy
    mz = structure_kg * scz
    for m, x, y, z, *_rest in points:
        mx += m * x
        my += m * y
        mz += m * z
    cx, cy, cz = mx / mass, my / mass, mz / mass

    ixx, iyy, izz = _box_inertia_center(structure_kg, sx, sy, sz)
    ixy = ixz = iyz = 0.0
    ixx, iyy, izz, ixy, ixz, iyz = _shift_inertia(
        ixx, iyy, izz, ixy, ixz, iyz, structure_kg, scx - cx, scy - cy, scz - cz
    )
    if servo_kg:
        bix, biy, biz = _box_inertia_center(servo_kg, *SERVO_BOX_M)
        ixx += bix
        iyy += biy
        izz += biz
        ixx, iyy, izz, ixy, ixz, iyz = _shift_inertia(
            ixx, iyy, izz, ixy, ixz, iyz, servo_kg, -cx, -cy, -cz
        )
    for m, x, y, z, bx, by, bz in points:
        if bx > 0.0 and by > 0.0 and bz > 0.0:
            pix, piy, piz = _box_inertia_center(m, bx, by, bz)
            ixx += pix
            iyy += piy
            izz += piz
        ixx, iyy, izz, ixy, ixz, iyz = _shift_inertia(
            ixx, iyy, izz, ixy, ixz, iyz, m, x - cx, y - cy, z - cz
        )

    return {
        "mass_kg": mass,
        "com_m": (cx, cy, cz),
        "inertia": (ixx, iyy, izz, ixy, ixz, iyz),
        "breakdown_g": {
            "structure": structure_kg * 1000.0,
            "servos": servo_kg * 1000.0,
            "electronics": extra_kg * 1000.0 if name == "torso" else 0.0,
            "foot": extra_kg * 1000.0 if "foot" in name else 0.0,
        },
    }


def volume_shares(boxes: Dict[str, Sequence[float]]) -> Dict[str, float]:
    vols = {n: max(float(b[0]) * float(b[1]) * float(b[2]), 1e-12) for n, b in boxes.items()}
    total = sum(vols.values())
    return {n: v / total for n, v in vols.items()}


def robot_inertials(
    boxes: Mapping[str, Sequence[float]],
    tree: Mapping[str, object],
) -> Dict[str, Dict[str, object]]:
    """整机每条 link 的惯量。脚不参与结构体积分配。"""
    joints = list(tree["joints"])  # type: ignore[index]
    non_foot = {n: b for n, b in boxes.items() if "foot" not in n}
    shares = volume_shares(non_foot)
    out: Dict[str, Dict[str, object]] = {}
    for name, box in boxes.items():
        kids = [j["xyz"] for j in joints if j["parent"] == name]
        out[name] = link_inertial(
            name,
            box,
            shares.get(name, 0.0),
            has_servo=(name != "pelvis"),
            structure_com=structure_com_m(name, kids),
        )
    return out


def principal_positive(inertia: Sequence[float]) -> bool:
    ixx, iyy, izz = inertia[0], inertia[1], inertia[2]
    return ixx > 0.0 and iyy > 0.0 and izz > 0.0
