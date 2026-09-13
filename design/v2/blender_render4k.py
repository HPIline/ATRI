"""4K Cycles HIP review renders of the existing ATRI-v2 assembly blend.

Opens the CAD review scene, tightens materials, stores named cameras, renders
assembled and exploded 3840x2160 shots, then restores mesh locations. These
are CAD review images, not photographs or manufacturing qualification.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESIGN = HERE.parent
if str(DESIGN) not in sys.path:
    sys.path.insert(0, str(DESIGN))

OUT = HERE / "out" / "render4k"
BLEND = HERE / "out" / "blender" / "ATRI-v2-assembly-review.blend"
CJK_FONT = Path("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc")

CAM_FRONT = "ATRI_cam_assembled_front"
CAM_REAR = "ATRI_cam_assembled_rear"
CAM_DETAIL = "ATRI_cam_detail_waist_hand_sensor"
CAM_EXPLODED = "ATRI_cam_exploded"

FASTENER_TOKENS = ("-screw", "-bolt", "-nut", "-washer", "rear-retainer")
FASTENER_MATS = {"ATRI_fastener", "ATRI_standoff"}
FASTENER_SCALE = 1.3

# World-space explode offsets in metres. Robot bbox is ~0.16 x 0.30 x 0.47.
LAYER_OFFSETS = {
    "shell_front": (0.16, 0.0, 0.025),
    "shell_rear": (-0.16, 0.0, 0.025),
    "pelvis": (0.0, 0.0, -0.045),
    "waist_dual": (-0.11, 0.0, 0.09),
    "hip_dual_left": (0.0, 0.12, 0.0),
    "hip_dual_right": (0.0, -0.12, 0.0),
    "leg_left": (0.0, 0.14, -0.04),
    "leg_right": (0.0, -0.14, -0.04),
    "arm_left": (0.0, 0.16, 0.02),
    "arm_right": (0.0, -0.16, 0.02),
    "gripper_left": (0.0, 0.26, -0.02),
    "gripper_right": (0.0, -0.26, -0.02),
    "electronics": (-0.11, 0.0, 0.10),
    "battery": (-0.15, 0.0, 0.02),
    "sensor": (0.12, 0.0, 0.12),
    "core": (0.0, 0.0, 0.0),
}

LEG_STACK_Z = {
    "left_thigh": -0.03,
    "right_thigh": -0.03,
    "left_shank": -0.10,
    "right_shank": -0.10,
    "left_foot": -0.18,
    "right_foot": -0.18,
}

PARENT_LAYER = {
    "pelvis": "pelvis",
    "trunk_roll_link": "waist_dual",
    "left_hip_roll_link": "hip_dual_left",
    "right_hip_roll_link": "hip_dual_right",
    "left_thigh": "leg_left",
    "left_shank": "leg_left",
    "left_foot": "leg_left",
    "right_thigh": "leg_right",
    "right_shank": "leg_right",
    "right_foot": "leg_right",
    "left_upper": "arm_left",
    "left_fore": "arm_left",
    "left_hand": "arm_left",
    "left_grip": "gripper_left",
    "right_upper": "arm_right",
    "right_fore": "arm_right",
    "right_hand": "arm_right",
    "right_grip": "gripper_right",
    "torso": "core",
    "head": "core",
    "head_yaw_link": "core",
}

BOM_GROUPS = [
    (1, "外壳"),
    (2, "骨盆"),
    (3, "腰部双片"),
    (4, "髋部双片"),
    (5, "腿"),
    (6, "手臂"),
    (7, "夹爪"),
    (8, "电子件"),
    (9, "电池"),
    (10, "紧固件"),
    (11, "传感器"),
]


def _bsdf(mat):
    if mat.node_tree is None:
        mat.use_nodes = True
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def _set(node, name, value):
    if name not in node.inputs:
        return
    node.inputs[name].default_value = value


def _ensure_material(name):
    import bpy

    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, _bsdf(mat)


def apply_materials():
    """Opaque matte PETG, real aluminum, dark servos, teal ToF on vl53l1x only."""
    import bpy
    from v2.blender_build import linear_rgba

    petg, node = _ensure_material("ATRI_petg")
    white = linear_rgba((242, 242, 240))
    petg.diffuse_color = white
    _set(node, "Base Color", white)
    _set(node, "Metallic", 0.0)
    _set(node, "Roughness", 0.68)
    _set(node, "Specular IOR Level", 0.22)
    _set(node, "Coat Weight", 0.0)
    _set(node, "Transmission Weight", 0.0)
    _set(node, "Alpha", 1.0)
    _set(node, "Weight", 1.0)
    _set(node, "Subsurface Weight", 0.0)

    al, node = _ensure_material("ATRI_al")
    metal = linear_rgba((168, 176, 184))
    al.diffuse_color = metal
    _set(node, "Base Color", metal)
    _set(node, "Metallic", 1.0)
    _set(node, "Roughness", 0.22)
    _set(node, "Coat Weight", 0.0)
    _set(node, "Transmission Weight", 0.0)
    _set(node, "Weight", 1.0)

    servo, node = _ensure_material("ATRI_servo")
    dark = linear_rgba((36, 38, 42))
    servo.diffuse_color = dark
    _set(node, "Base Color", dark)
    _set(node, "Metallic", 0.08)
    _set(node, "Roughness", 0.48)
    _set(node, "Coat Weight", 0.0)
    _set(node, "Weight", 1.0)

    sensor, node = _ensure_material("ATRI_sensor")
    teal = linear_rgba((16, 186, 198))
    sensor.diffuse_color = teal
    _set(node, "Base Color", teal)
    _set(node, "Metallic", 0.12)
    _set(node, "Roughness", 0.38)
    _set(node, "Coat Weight", 0.0)
    _set(node, "Transmission Weight", 0.0)
    _set(node, "Weight", 1.0)

    tof = bpy.data.objects.get("vl53l1x")
    if tof is None or tof.type != "MESH":
        raise RuntimeError("vl53l1x mesh is required for the sensor callout")
    tof.data.materials.clear()
    tof.data.materials.append(sensor)

    # Keep remaining kinds assigned and opaque so they stay distinguishable.
    for name, metal_v, rough in (
        ("ATRI_pcb", 0.08, 0.48),
        ("ATRI_electronics_case", 0.0, 0.5),
        ("ATRI_optical", 0.3, 0.2),
        ("ATRI_horn", 0.95, 0.22),
        ("ATRI_fastener", 0.88, 0.32),
        ("ATRI_standoff", 0.92, 0.38),
        ("ATRI_tpu", 0.0, 0.78),
        ("ATRI_elec", 0.12, 0.48),
        ("ATRI_strap", 0.0, 0.9),
        ("ATRI_connector_metal", 0.9, 0.3),
        ("ATRI_connector_white", 0.0, 0.5),
        ("ATRI_cable", 0.05, 0.72),
    ):
        mat = bpy.data.materials.get(name)
        if mat is None:
            continue
        node = _bsdf(mat)
        _set(node, "Metallic", metal_v)
        _set(node, "Roughness", rough)
        _set(node, "Transmission Weight", 0.0)
        _set(node, "Alpha", 1.0)
        _set(node, "Weight", 1.0)


def configure_cycles_hip_4k(samples):
    """Cycles HIP GPU only, 3840x2160, denoising on. No Eevee, no CPU fallback."""
    import bpy
    from v2.blender_build import configure_studio

    if samples < 64:
        raise ValueError("4K review renders require samples>=64")
    devices = configure_studio(samples)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    if scene.render.engine != "CYCLES":
        raise RuntimeError("Cycles is required; Eevee is disabled")
    scene.render.resolution_x = 3840
    scene.render.resolution_y = 2160
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.use_file_extension = True
    scene.render.use_persistent_data = True
    scene.view_settings.view_transform = "AgX"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.device = "GPU"

    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "HIP"
    prefs.get_devices()
    hip = []
    cpu_enabled = False
    for device in prefs.devices:
        device.use = device.type == "HIP"
        if device.use:
            hip.append(device.name)
        if device.type == "CPU" and device.use:
            cpu_enabled = True
    if not hip:
        raise RuntimeError("A HIP GPU is required; CPU fallback is disabled")
    if cpu_enabled:
        raise RuntimeError("CPU device still enabled after HIP-only filter")
    scene.cycles.device = "GPU"
    print("CYCLES HIP ONLY 4K:", hip)
    return hip


def cad_parts():
    from v2.blender_build import assembly_objects

    parts = assembly_objects()
    if not parts:
        raise ValueError("No named CAD assembly in the visible scene")
    return parts


def _ensure_camera(name):
    import bpy

    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type == "CAMERA":
        data = obj.data
    else:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        data = bpy.data.cameras.new(name)
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
    data.type = "ORTHO"
    data.clip_start = 0.001
    data.clip_end = 40
    return obj


def _frame(cam, objects, direction, margin):
    import bpy
    from v2.blender_build import frame_shot

    bpy.context.scene.camera = cam
    frame_shot(objects, direction, margin)
    return cam


def _material_name(obj):
    if obj.data.materials and obj.data.materials[0]:
        return obj.data.materials[0].name
    return ""


def is_fastener(obj):
    if _material_name(obj) in FASTENER_MATS:
        return True
    return any(tok in obj.name for tok in FASTENER_TOKENS)


def structural_layer(obj):
    n = obj.name
    mat = _material_name(obj)
    parent = obj.parent.name if obj.parent else ""
    if n == "vl53l1x" or n.startswith("camera") or n.startswith("lens"):
        return "sensor"
    if n.startswith("shell-torso-front") or n.startswith("cover-head-f"):
        return "shell_front"
    if n.startswith("shell-torso-rear") or n.startswith("cover-head-b"):
        return "shell_rear"
    if n.startswith("battery") or mat in {"ATRI_elec", "ATRI_strap"}:
        return "battery"
    if n.startswith("sbc") or n.startswith("bus") or n.startswith("regulator"):
        return "electronics"
    if mat in {"ATRI_pcb", "ATRI_electronics_case"} and n != "vl53l1x":
        return "electronics"
    if n.startswith("pelvis-"):
        return "pelvis"
    if n.startswith("waist-"):
        return "waist_dual"
    if n.startswith("hip-dual-left") or (n.startswith("hip-") and "left" in n):
        return "hip_dual_left"
    if n.startswith("hip-dual-right") or (n.startswith("hip-") and "right" in n):
        return "hip_dual_right"
    if "gripper" in n and "left" in n:
        return "gripper_left"
    if "gripper" in n and "right" in n:
        return "gripper_right"
    if n.startswith("arm-left") or n.startswith("leg-left"):
        return "arm_left" if n.startswith("arm-left") else "leg_left"
    if n.startswith("arm-right") or n.startswith("leg-right"):
        return "arm_right" if n.startswith("arm-right") else "leg_right"
    return PARENT_LAYER.get(parent, "core")


def explode_offset(obj, layer):
    from mathutils import Vector

    delta = Vector(LAYER_OFFSETS[layer])
    parent = obj.parent.name if obj.parent else ""
    if layer in {"leg_left", "leg_right"}:
        delta.z += LEG_STACK_Z.get(parent, 0.0)
    if is_fastener(obj):
        delta *= FASTENER_SCALE
    return delta


def bom_number(obj, layer):
    if is_fastener(obj):
        return 10
    if layer == "sensor":
        return 11
    if layer in {"shell_front", "shell_rear", "core"}:
        return 1
    if layer == "pelvis":
        return 2
    if layer == "waist_dual":
        return 3
    if layer in {"hip_dual_left", "hip_dual_right"}:
        return 4
    if layer in {"leg_left", "leg_right"}:
        return 5
    if layer in {"arm_left", "arm_right"}:
        return 6
    if layer in {"gripper_left", "gripper_right"}:
        return 7
    if layer == "electronics":
        return 8
    if layer == "battery":
        return 9
    return 1


def apply_world_translation(obj, world_delta):
    """Store a world-space translation as parent-local location. Do not unparent."""
    from mathutils import Vector

    mw = obj.matrix_world.copy()
    target = mw.copy()
    target.translation = mw.translation + Vector(world_delta)
    if obj.parent is None:
        obj.location = target.translation
        return
    new_basis = obj.matrix_parent_inverse.inverted() @ obj.parent.matrix_world.inverted() @ target
    obj.location = new_basis.to_translation()


def explode_parts(parts):
    import bpy

    bpy.context.view_layer.update()
    for obj in parts:
        layer = structural_layer(obj)
        delta = explode_offset(obj, layer)
        obj["atri_layer"] = layer
        obj["atri_explode"] = [float(delta.x), float(delta.y), float(delta.z)]
        apply_world_translation(obj, delta)
        obj.hide_render = False
    bpy.context.view_layer.update()


def restore_parts(parts, original):
    import bpy

    for obj in parts:
        loc, parent = original[obj.name]
        obj.location = loc
        if obj.parent != parent:
            raise RuntimeError(f"{obj.name} parent changed during explode")
        obj.hide_render = False
    bpy.context.view_layer.update()


def assert_exploded(parts):
    missing = []
    for obj in parts:
        if obj.parent is None:
            missing.append(f"{obj.name}: unparented")
        if not obj.data.vertices:
            missing.append(f"{obj.name}: no vertices")
        if not any(obj.data.materials):
            missing.append(f"{obj.name}: no material")
        if obj.hide_render:
            missing.append(f"{obj.name}: hide_render")
    if missing:
        raise RuntimeError("Exploded assembly invalid:\n" + "\n".join(missing[:40]))
    return []


def _centroid(objects):
    from mathutils import Vector

    if not objects:
        return Vector((0, 0, 0.3))
    acc = Vector((0, 0, 0))
    n = 0
    for obj in objects:
        low = Vector(obj.bound_box[0])
        high = Vector(obj.bound_box[6])
        acc += obj.matrix_world @ ((low + high) / 2)
        n += 1
    return acc / n


def _label_material():
    from v2.blender_build import linear_rgba

    mat, node = _ensure_material("ATRI_label")
    color = linear_rgba((255, 214, 64))
    mat.diffuse_color = color
    _set(node, "Base Color", color)
    _set(node, "Metallic", 0.0)
    _set(node, "Roughness", 0.45)
    _set(node, "Emission Color", color)
    _set(node, "Emission Strength", 12.0)
    _set(node, "Weight", 1.0)
    return mat


def _load_cjk_font():
    import bpy

    if not CJK_FONT.is_file():
        raise RuntimeError(f"CJK font required for exploded labels: {CJK_FONT}")
    for font in bpy.data.fonts:
        if Path(getattr(font, "filepath", "")).name == CJK_FONT.name:
            return font
    return bpy.data.fonts.load(str(CJK_FONT))


def clear_labels():
    import bpy

    for obj in list(bpy.data.objects):
        if obj.name.startswith("ATRI_label_"):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.curves.remove(data)


def _label_cluster(number, group_parts):
    def layer_is(obj, layer):
        return obj.get("atri_layer", structural_layer(obj)) == layer

    if number == 1:
        cluster = [o for o in group_parts if layer_is(o, "shell_front")]
    elif number == 4:
        cluster = [o for o in group_parts if layer_is(o, "hip_dual_left")]
    elif number == 5:
        cluster = [o for o in group_parts if o.parent and o.parent.name == "left_shank"]
    elif number == 6:
        cluster = [o for o in group_parts if layer_is(o, "arm_left")]
    elif number == 7:
        cluster = [o for o in group_parts if layer_is(o, "gripper_left")]
    elif number == 10:
        cluster = [o for o in group_parts if layer_is(o, "electronics")]
    else:
        cluster = group_parts
    return cluster or group_parts


def _separate_labels(positions, cam, min_dist=0.085):
    from mathutils import Vector

    keys = list(positions)
    inverse = cam.matrix_world.inverted()
    world = cam.matrix_world
    for _ in range(16):
        moved = False
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                ia = inverse @ positions[a]
                ib = inverse @ positions[b]
                delta = Vector((ia.x - ib.x, ia.y - ib.y, 0.0))
                dist = delta.length
                if dist >= min_dist:
                    continue
                push = delta.normalized() if dist > 1e-6 else Vector((1.0, 0.0, 0.0))
                step = (min_dist - dist) * 0.5 + 0.003
                ia.x += push.x * step
                ia.y += push.y * step
                ib.x -= push.x * step
                ib.y -= push.y * step
                positions[a] = world @ ia
                positions[b] = world @ ib
                moved = True
        if not moved:
            break
    return positions


def make_labels(parts_by_number, cam):
    import bpy
    from mathutils import Vector

    clear_labels()
    font = _load_cjk_font()
    mat = _label_material()
    names = {n: label for n, label in BOM_GROUPS}
    cam_loc = cam.matrix_world.translation
    planned = {}
    for number, group_parts in sorted(parts_by_number.items()):
        if not group_parts:
            continue
        cluster = _label_cluster(number, group_parts)
        center = _centroid(cluster)
        mean = Vector((0.0, 0.0, 0.0))
        for obj in cluster:
            mean += Vector(obj.get("atri_explode", (0.0, 0.0, 0.0)))
        mean /= len(cluster)
        toward = cam_loc - center
        if toward.length < 1e-6:
            toward = Vector((1.0, -1.0, 0.4))
        push = mean.normalized() * 0.08 if mean.length > 1e-6 else Vector((0.0, 0.0, 0.04))
        planned[number] = center + push + toward.normalized() * 0.04 + Vector((0.0, 0.0, 0.03))
    planned = _separate_labels(planned, cam)

    labels = []
    for number, loc in planned.items():
        curve = bpy.data.curves.new(f"ATRI_label_{number}", "FONT")
        curve.body = f"{number} {names[number]}"
        curve.font = font
        curve.size = 0.046
        curve.align_x = "CENTER"
        curve.align_y = "CENTER"
        curve.extrude = 0.0018
        obj = bpy.data.objects.new(f"ATRI_label_{number}", curve)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = loc
        obj.rotation_euler = cam.rotation_euler.copy()
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        obj.visible_shadow = False
        obj.hide_render = False
        obj["atri_label_number"] = number
        labels.append(obj)
    bpy.context.view_layer.update()
    return labels


def hide_labels():
    import bpy

    for obj in bpy.data.objects:
        if obj.name.startswith("ATRI_label_"):
            obj.hide_render = True


def write_bom(parts):
    OUT.mkdir(parents=True, exist_ok=True)
    names = {n: label for n, label in BOM_GROUPS}
    rows = []
    for obj in sorted(parts, key=lambda o: o.name):
        layer = obj.get("atri_layer", structural_layer(obj))
        number = bom_number(obj, layer)
        rows.append(
            {
                "number": number,
                "group": names[number],
                "explode_layer": layer,
                "parent": obj.parent.name if obj.parent else "",
                "material": _material_name(obj),
                "name": obj.name,
            }
        )
    csv_path = OUT / "exploded-parts.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["number", "group", "explode_layer", "parent", "material", "name"],
        )
        writer.writeheader()
        writer.writerows(rows)
    by_num = defaultdict(list)
    for row in rows:
        by_num[row["number"]].append(row["name"])
    lines = [
        "# ATRI-v2 exploded parts",
        "",
        "CAD review mapping of exploded-view numbers to every mesh in the blend.",
        "Not a manufacturing bill of materials and not a physical qualification record.",
        "",
        f"Part count: {len(rows)}",
        "",
    ]
    for number, label in BOM_GROUPS:
        lines.append(f"## {number} {label} ({len(by_num[number])})")
        lines.append("")
        for name in by_num[number]:
            lines.append(f"- `{name}`")
        lines.append("")
    md_path = OUT / "exploded-parts.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return rows, csv_path, md_path


def _render(cam, path, objects, direction, margin):
    import bpy

    _frame(cam, objects, direction, margin)
    bpy.context.scene.camera = cam
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not path.is_file() or path.stat().st_size < 10_000:
        raise RuntimeError(f"Render wrote no usable image: {path}")
    return path.name


def detail_focus(parts):
    focus = []
    for obj in parts:
        n = obj.name
        if (
            n.startswith("waist-")
            or n.startswith("hip-dual")
            or n.startswith("arm-left-gripper")
            or n == "vl53l1x"
            or n.startswith("camera")
            or n.startswith("lens")
        ):
            focus.append(obj)
    if not focus:
        raise RuntimeError("Detail shot has no waist/hip/gripper/sensor meshes")
    return focus


def render4k(samples=64):
    import bpy

    OUT.mkdir(parents=True, exist_ok=True)
    apply_materials()
    devices = configure_cycles_hip_4k(samples)
    parts = cad_parts()
    for obj in parts:
        obj.location = (0.0, 0.0, 0.0)
        obj.hide_render = False
    bpy.context.view_layer.update()
    original = {obj.name: (obj.location.copy(), obj.parent) for obj in parts}

    ground = bpy.data.objects.get("ground")
    ground_hide = ground.hide_render if ground else False
    hide_labels()

    cam_front = _ensure_camera(CAM_FRONT)
    cam_rear = _ensure_camera(CAM_REAR)
    cam_detail = _ensure_camera(CAM_DETAIL)
    cam_exploded = _ensure_camera(CAM_EXPLODED)

    files = []
    files.append(
        _render(cam_front, OUT / "assembled_front.png", parts, (1.0, -0.85, 0.38), 1.28)
    )
    files.append(
        _render(cam_rear, OUT / "assembled_rear.png", parts, (-1.0, -0.85, 0.38), 1.28)
    )
    files.append(
        _render(
            cam_detail,
            OUT / "detail_waist_hand_sensor.png",
            detail_focus(parts),
            (0.35, 1.15, 0.22),
            1.2,
        )
    )

    explode_parts(parts)
    invalid = assert_exploded(parts)
    if ground:
        ground.hide_render = True
    files.append(
        _render(cam_exploded, OUT / "exploded.png", parts, (1.0, -1.05, 0.42), 1.14)
    )

    by_number = defaultdict(list)
    for obj in parts:
        by_number[bom_number(obj, obj["atri_layer"])].append(obj)
    labels = make_labels(by_number, cam_exploded)
    files.append(
        _render(
            cam_exploded,
            OUT / "exploded_numbered.png",
            parts,
            (1.0, -1.05, 0.42),
            1.16,
        )
    )

    rows, csv_path, md_path = write_bom(parts)
    restore_parts(parts, original)
    hide_labels()
    if ground:
        ground.hide_render = ground_hide
    bpy.context.scene.camera = cam_front
    bpy.context.view_layer.update()
    bpy.ops.wm.save_mainfile(filepath=str(BLEND))

    cpu_enabled = False
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for device in prefs.devices:
        if device.type == "CPU" and device.use:
            cpu_enabled = True
    report = {
        "engine": bpy.context.scene.render.engine,
        "device_names": list(devices),
        "cpu_enabled": cpu_enabled,
        "samples": int(bpy.context.scene.cycles.samples),
        "resolution": [
            int(bpy.context.scene.render.resolution_x),
            int(bpy.context.scene.render.resolution_y),
        ],
        "part_count": len(parts),
        "files": files,
        "hip_gpu": devices[0] if devices else "",
        "bom": [csv_path.name, md_path.name],
        "label_count": len(labels),
        "invalid_meshes": invalid,
        "note": (
            "CAD review renders, not photographs or manufacturing qualification. "
            "These images are produced from the exported assembly blend and do not "
            "claim the robot was manufactured or physically verified."
        ),
    }
    (OUT / "render-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=64)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    render4k(args.samples)
