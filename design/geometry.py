"""几何基元与三维变换：设计模型的基础层。

纯标准库实现，无 numpy 依赖。

支持的基元
----------
    box           长方体
    rounded_box   圆角长方体（外壳）
    cylinder      圆柱（舵机本体、关节轴）
    sphere        球（关节）
    capsule       胶囊（连杆，两端圆头）
    sphere_shell  球壳（关节外壳，中空）

每个基元提供：
    bounding_box()   轴对齐包围盒尺寸 [x, y, z]（mm）
    inertia()        实心/等效惯量 (ixx, iyy, izz)（kg·m²）
    urdf_xml()       URDF <geometry> 片段
    half_extents()   半尺寸，用于 AABB 干涉检查
    project()        正交投影轮廓，用于 2D 工程图

单位纪律
--------
模型内部长度一律 **mm**；惯量计算时换算成 **m**（URDF 要求 kg·m²）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

# --------------------------------------------------------------------------
# 三维变换（齐次坐标，4x4）
# --------------------------------------------------------------------------
Matrix = List[List[float]]
Vec3 = Sequence[float]


def identity() -> Matrix:
    return [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


def translation(x: float, y: float, z: float) -> Matrix:
    m = identity()
    m[0][3], m[1][3], m[2][3] = float(x), float(y), float(z)
    return m


def mat_mul(a: Matrix, b: Matrix) -> Matrix:
    out = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            out[i][j] = sum(a[i][k] * b[k][j] for k in range(4))
    return out


def _normalize(v: Vec3) -> Tuple[float, float, float]:
    x, y, z = (float(c) for c in v)
    n = math.sqrt(x * x + y * y + z * z)
    if n == 0.0:
        return (0.0, 0.0, 1.0)
    return (x / n, y / n, z / n)


def rotation_matrix(axis: Vec3, angle_rad: float) -> Matrix:
    """绕任意轴旋转（罗德里格斯公式）。"""
    x, y, z = _normalize(axis)
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    C = 1.0 - c
    r = [
        [x * x * C + c, x * y * C - z * s, x * z * C + y * s, 0.0],
        [y * x * C + z * s, y * y * C + c, y * z * C - x * s, 0.0],
        [z * x * C - y * s, z * y * C + x * s, z * z * C + c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return r


def transform_point(m: Matrix, p: Vec3) -> Tuple[float, float, float]:
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    return (
        m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
        m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
        m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
    )


def joint_transform(origin_mm: Vec3, axis: Vec3, angle_deg: float) -> Matrix:
    """关节变换 = 先平移到关节原点，再绕轴旋转。"""
    t = translation(origin_mm[0], origin_mm[1], origin_mm[2])
    r = rotation_matrix(axis, math.radians(angle_deg))
    return mat_mul(t, r)


# --------------------------------------------------------------------------
# 几何基元
# --------------------------------------------------------------------------
SUPPORTED_TYPES = (
    "box",
    "rounded_box",
    "cylinder",
    "sphere",
    "capsule",
    "sphere_shell",
)


class GeometryError(ValueError):
    """几何定义错误。"""


def _axis_of(geom: Dict[str, Any]) -> str:
    axis = str(geom.get("axis", "z")).lower()
    if axis not in ("x", "y", "z"):
        raise GeometryError(f"axis 必须是 x/y/z，收到 {axis!r}")
    return axis


def bounding_box(geom: Dict[str, Any]) -> List[float]:
    """返回轴对齐包围盒尺寸 [x, y, z]（mm）。"""
    gtype = geom.get("type")
    if gtype in ("box", "rounded_box"):
        size = geom.get("size_mm")
        if not size or len(size) != 3:
            raise GeometryError(f"{gtype} 需要 size_mm: [x, y, z]")
        return [float(v) for v in size]

    if gtype == "cylinder":
        r = float(geom.get("radius_mm", 0.0))
        h = float(geom.get("height_mm", 0.0))
        if r <= 0 or h <= 0:
            raise GeometryError("cylinder 需要正的 radius_mm 与 height_mm")
        axis = _axis_of(geom)
        d = 2.0 * r
        return {
            "x": [h, d, d],
            "y": [d, h, d],
            "z": [d, d, h],
        }[axis]

    if gtype == "sphere":
        r = float(geom.get("radius_mm", 0.0))
        if r <= 0:
            raise GeometryError("sphere 需要正的 radius_mm")
        return [2.0 * r] * 3

    if gtype == "capsule":
        r = float(geom.get("radius_mm", 0.0))
        length = float(geom.get("length_mm", 0.0))
        if r <= 0 or length < 0:
            raise GeometryError("capsule 需要正的 radius_mm 与非负 length_mm")
        axis = _axis_of(geom)
        d = 2.0 * r
        total = length + d
        return {
            "x": [total, d, d],
            "y": [d, total, d],
            "z": [d, d, total],
        }[axis]

    if gtype == "sphere_shell":
        ro = float(geom.get("outer_r_mm", 0.0))
        ri = float(geom.get("inner_r_mm", 0.0))
        if ro <= 0 or ri < 0 or ri >= ro:
            raise GeometryError("sphere_shell 需要 0 <= inner_r_mm < outer_r_mm")
        return [2.0 * ro] * 3

    raise GeometryError(f"不支持的几何类型: {gtype!r}；支持 {SUPPORTED_TYPES}")


def half_extents(geom: Dict[str, Any]) -> List[float]:
    return [v / 2.0 for v in bounding_box(geom)]


def equivalent_box(geom: Dict[str, Any]) -> Dict[str, Any]:
    """把任意基元退化为等效 box —— 用于 collision 与 AABB 干涉检查。

    这是标准工程做法：碰撞检测用简化体，既快又稳。
    """
    size = bounding_box(geom)
    color = geom.get("color")
    out: Dict[str, Any] = {"type": "box", "size_mm": list(size)}
    if color:
        out["color"] = list(color)
    return out


def inertia(geom: Dict[str, Any], mass_kg: float) -> Tuple[float, float, float]:
    """返回 (ixx, iyy, izz)，单位 kg·m²。

    部分基元使用等效近似，已在返回值下方注释说明：
      - rounded_box 按等尺寸 box 计算（圆角去掉的质量很少，偏保守）
      - capsule     按圆柱 + 两端半球用平行轴定理合成
      - sphere_shell按中空球精确公式
    """
    m = float(mass_kg)
    gtype = geom.get("type")

    def box_i(sx: float, sy: float, sz: float) -> Tuple[float, float, float]:
        w, d, h = sx / 1000.0, sy / 1000.0, sz / 1000.0
        return (
            m * (d * d + h * h) / 12.0,
            m * (w * w + h * h) / 12.0,
            m * (w * w + d * d) / 12.0,
        )

    if gtype in ("box", "rounded_box"):
        return box_i(*bounding_box(geom))

    if gtype == "cylinder":
        r = float(geom["radius_mm"]) / 1000.0
        h = float(geom["height_mm"]) / 1000.0
        i_axial = 0.5 * m * r * r
        i_radial = m * (3.0 * r * r + h * h) / 12.0
        axis = _axis_of(geom)
        return {
            "x": (i_axial, i_radial, i_radial),
            "y": (i_radial, i_axial, i_radial),
            "z": (i_radial, i_radial, i_axial),
        }[axis]

    if gtype == "sphere":
        r = float(geom["radius_mm"]) / 1000.0
        i = 0.4 * m * r * r  # 2/5 m r²
        return (i, i, i)

    if gtype == "capsule":
        r = float(geom["radius_mm"]) / 1000.0
        length = float(geom["length_mm"]) / 1000.0
        axis = _axis_of(geom)
        # 体积分解：圆柱 + 两个半球
        v_cyl = math.pi * r * r * length
        v_sph = (4.0 / 3.0) * math.pi * r ** 3
        v_tot = v_cyl + v_sph
        if v_tot <= 0:
            raise GeometryError("capsule 体积为 0")
        m_cyl = m * v_cyl / v_tot
        m_sph = m * v_sph / v_tot

        i_axial = 0.5 * m_cyl * r * r + (2.0 / 5.0) * m_sph * r * r
        # 径向：圆柱项 + 半球质心偏移的平行轴项
        i_cyl_rad = m_cyl * (3.0 * r * r + length * length) / 12.0
        d = length / 2.0 + 3.0 * r / 8.0  # 半球质心到轴线中心距离
        i_sph_rad = (2.0 / 5.0) * m_sph * r * r + m_sph * d * d
        i_radial = i_cyl_rad + i_sph_rad

        return {
            "x": (i_axial, i_radial, i_radial),
            "y": (i_radial, i_axial, i_radial),
            "z": (i_radial, i_radial, i_axial),
        }[axis]

    if gtype == "sphere_shell":
        ro = float(geom["outer_r_mm"]) / 1000.0
        ri = float(geom["inner_r_mm"]) / 1000.0
        num = ro ** 5 - ri ** 5
        den = ro ** 3 - ri ** 3
        i = (2.0 / 5.0) * m * (num / den) if den > 0 else 0.4 * m * ro * ro
        return (i, i, i)

    raise GeometryError(f"不支持的几何类型: {gtype!r}")


def urdf_xml(geom: Dict[str, Any], indent: str = "      ") -> str:
    """生成 URDF <geometry> 片段。

    URDF 没有 capsule / rounded_box / sphere_shell 原生标签，
    采用**最接近的近似**而不是退化成长方体：
        rounded_box  -> box（去掉圆角，体积略偏大，保守）
        capsule      -> cylinder（轴向长度取 length + 2r，覆盖完整包络）
        sphere_shell -> sphere（外球半径，忽略中空）
    """
    gtype = geom.get("type")
    if gtype in ("box", "rounded_box"):
        sx, sy, sz = (v / 1000.0 for v in bounding_box(geom))
        note = "    <!-- rounded_box 近似为 box -->\n" if gtype == "rounded_box" else ""
        return (
            f"{indent}<geometry>\n"
            f"{note}"
            f"{indent}  <box size=\"{sx:.6f} {sy:.6f} {sz:.6f}\"/>\n"
            f"{indent}</geometry>"
        )
    if gtype == "cylinder":
        r = float(geom["radius_mm"]) / 1000.0
        h = float(geom["height_mm"]) / 1000.0
        return (
            f"{indent}<geometry>\n"
            f"{indent}  <cylinder radius=\"{r:.6f}\" length=\"{h:.6f}\"/>\n"
            f"{indent}</geometry>"
        )
    if gtype == "sphere":
        r = float(geom["radius_mm"]) / 1000.0
        return (
            f"{indent}<geometry>\n"
            f"{indent}  <sphere radius=\"{r:.6f}\"/>\n"
            f"{indent}</geometry>"
        )
    if gtype == "capsule":
        r = float(geom["radius_mm"]) / 1000.0
        length = float(geom["length_mm"]) / 1000.0
        axis = _axis_of(geom)
        # URDF cylinder 沿自身 z 轴；轴向不是 z 时用 rpy 旋转
        rpy = {
            "z": "0 0 0",
            "x": "0 1.570796 0",
            "y": "1.570796 0 0",
        }[axis]
        return (
            f"{indent}<geometry>\n"
            f"{indent}  <!-- capsule 近似为 cylinder（长度含两端球头） -->\n"
            f"{indent}  <cylinder radius=\"{r:.6f}\" length=\"{length + 2*r:.6f}\"/>\n"
            f"{indent}</geometry>\n"
            f"{indent}<!-- 轴向 rpy: {rpy} -->"
        )
    if gtype == "sphere_shell":
        ro = float(geom["outer_r_mm"]) / 1000.0
        return (
            f"{indent}<geometry>\n"
            f"{indent}  <!-- sphere_shell 近似为外球 -->\n"
            f"{indent}  <sphere radius=\"{ro:.6f}\"/>\n"
            f"{indent}</geometry>"
        )
    # 兜底：等效 box
    sx, sy, sz = (v / 1000.0 for v in bounding_box(geom))
    return (
        f"{indent}<geometry>\n"
        f"{indent}  <!-- 未知基元 {gtype}，退化为 box -->\n"
        f"{indent}  <box size=\"{sx:.6f} {sy:.6f} {sz:.6f}\"/>\n"
        f"{indent}</geometry>"
    )


def describe(geom: Dict[str, Any]) -> str:
    """人类可读的几何描述，用于图纸标注与 BOM。"""
    gtype = geom.get("type")
    if gtype == "box":
        sx, sy, sz = geom["size_mm"]
        return f"长方体 {sx:g}×{sy:g}×{sz:g}"
    if gtype == "rounded_box":
        sx, sy, sz = geom["size_mm"]
        return f"圆角盒 {sx:g}×{sy:g}×{sz:g} R{geom.get('fillet_mm', 0):g}"
    if gtype == "cylinder":
        return f"圆柱 Ø{2*geom['radius_mm']:g}×{geom['height_mm']:g}"
    if gtype == "sphere":
        return f"球 Ø{2*geom['radius_mm']:g}"
    if gtype == "capsule":
        return f"胶囊 Ø{2*geom['radius_mm']:g} L{geom['length_mm']:g}"
    if gtype == "sphere_shell":
        return f"球壳 Ø{2*geom['outer_r_mm']:g}/Ø{2*geom['inner_r_mm']:g}"
    return str(gtype)


# --------------------------------------------------------------------------
# 正交投影轮廓（用于 2D 工程图）
# --------------------------------------------------------------------------
# 机器人朝向 +X，+Y 为左侧，+Z 向上。
#   front 正视：从正前方看（视线沿 -X），屏幕横向 = Y，纵向 = Z
#   side  侧视：从左侧看（视线沿 -Y），屏幕横向 = X，纵向 = Z
#   top   俯视：从上方看（视线沿 -Z），屏幕横向 = Y，纵向 = X（前方朝上，故 v_flip）
VIEWS: Dict[str, Dict[str, Any]] = {
    "front": {"h": 1, "v": 2, "look": 0, "v_flip": False, "label": "正视图"},
    "side": {"h": 0, "v": 2, "look": 1, "v_flip": False, "label": "侧视图"},
    "top": {"h": 1, "v": 0, "look": 2, "v_flip": True, "label": "俯视图"},
}


def project_shape(geom: Dict[str, Any], view: str) -> Dict[str, Any]:
    """把基元正交投影成 2D 轮廓描述。

    返回 {"kind": "rect"|"circle"|"ring"|"capsule",
          "w":..., "h":..., "r":...}
    坐标以基元包围盒中心为原点。
    """
    if view not in VIEWS:
        raise GeometryError(f"未知视角: {view}")
    spec = VIEWS[view]
    hi, vi, look_index = spec["h"], spec["v"], spec["look"]
    size = bounding_box(geom)
    w, h = size[hi], size[vi]
    gtype = geom.get("type")
    axis = _axis_of(geom) if gtype in ("cylinder", "capsule") else None

    # 圆/圆环：视线方向与旋转轴一致时投影为圆
    axis_index = {"x": 0, "y": 1, "z": 2}.get(axis) if axis else None

    if gtype == "sphere":
        return {"kind": "circle", "r": size[0] / 2.0, "w": w, "h": h}

    if gtype == "sphere_shell":
        return {
            "kind": "ring",
            "ro": float(geom["outer_r_mm"]),
            "ri": float(geom["inner_r_mm"]),
            "w": w,
            "h": h,
        }

    if gtype == "cylinder":
        if axis_index == look_index:
            return {"kind": "circle", "r": size[0] / 2.0, "w": w, "h": h}
        return {"kind": "rect", "w": w, "h": h}

    if gtype == "capsule":
        if axis_index == look_index:
            return {"kind": "circle", "r": size[0] / 2.0, "w": w, "h": h}
        r = float(geom["radius_mm"])
        length = float(geom["length_mm"])
        along_horizontal = (axis_index == hi)
        return {
            "kind": "capsule",
            "r": r,
            "length": length,
            "along_horizontal": along_horizontal,
            "w": w,
            "h": h,
        }

    # box / rounded_box
    return {
        "kind": "rect",
        "w": w,
        "h": h,
        "fillet": float(geom.get("fillet_mm", 0.0)),
    }


# --------------------------------------------------------------------------
# 运动学：零姿态下的 link 世界位置
# --------------------------------------------------------------------------
def link_positions(model: Dict[str, Any],
                   pose_deg: Dict[str, float] | None = None) -> Dict[str, Matrix]:
    """返回每个 link 的世界变换矩阵。

    pose_deg 为 None 时使用零位（所有关节 0°）。
    """
    pose = pose_deg or {}
    joints = sorted(model["joints"], key=lambda j: j["id"])
    by_child = {j["child"]: j for j in joints}

    # 建立父子关系，从根向下遍历
    children_of: Dict[str, List[Dict[str, Any]]] = {}
    for j in joints:
        children_of.setdefault(j["parent"], []).append(j)

    # 找根
    all_children = {j["child"] for j in joints}
    roots = [l["name"] for l in model["links"] if l["name"] not in all_children]
    root = roots[0] if roots else model["links"][0]["name"]

    out: Dict[str, Matrix] = {}

    def walk(link: str, parent_tf: Matrix) -> None:
        out[link] = parent_tf
        for j in children_of.get(link, []):
            angle = float(pose.get(j["name"], j.get("rest_deg", 0.0)))
            local = joint_transform(j["origin_xyz_mm"], j["axis"], angle)
            walk(j["child"], mat_mul(parent_tf, local))

    base = translation(*model.get("base_pose_mm", [0.0, 0.0, 0.0]))
    walk(root, base)
    return out


def link_world_aabb(model: Dict[str, Any], link_name: str,
                    tf: Matrix, geom_override: Dict[str, Any] | None = None
                    ) -> Tuple[Tuple[float, float, float],
                               Tuple[float, float, float]]:
    """计算某 link 在给定世界变换下的轴对齐包围盒（AABB）。

    返回 ((min_x,min_y,min_z), (max_x,max_y,max_z))。
    """
    link = next((l for l in model["links"] if l["name"] == link_name), None)
    if link is None:
        raise GeometryError(f"未找到 link: {link_name}")
    geom = geom_override or link["geometry"]
    hx, hy, hz = half_extents(geom)

    corners = [
        (sx * hx, sy * hy, sz * hz)
        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
    ]
    pts = [transform_point(tf, c) for c in corners]
    mins = tuple(min(p[i] for p in pts) for i in range(3))
    maxs = tuple(max(p[i] for p in pts) for i in range(3))
    return mins, maxs  # type: ignore[return-value]


def aabb_overlap(a: Tuple[Tuple[float, float, float], Tuple[float, float, float]],
                 b: Tuple[Tuple[float, float, float], Tuple[float, float, float]]
                 ) -> Tuple[bool, float]:
    """两个 AABB 是否重叠，以及最小重叠量（mm）。"""
    overlap = []
    for i in range(3):
        lo = max(a[0][i], b[0][i])
        hi = min(a[1][i], b[1][i])
        if hi <= lo:
            return False, 0.0
        overlap.append(hi - lo)
    return True, min(overlap)
