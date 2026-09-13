"""用 CadQuery 出 STEP/STL，并刷新网页预览网格。

    .venv-cad/bin/python -m v2.cad_export
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .assembly3d import (  # noqa: F401
    HEAD_PITCH_Z,
    KINDS,
    TORSO_UP,
    fk,
    has_passive_support,
    kinematic_tree,
    m_apply,
    m_ident,
)
from .cad_parts import (
    horn_disc,
    limb_side_plate,
    m25_screw,
    orient_y_to_axis,
    orient_z_to_axis,
    plate_solid,
    sts3215,
    sts3215_components,
    c018_accessories,
)
from .layout import SANDWICH, SERVO_AXIAL, horn_center, idle_center
from .plates import all_plates
from .audit3d import audit
from .preview3d import write_html
from .profile import K, PELVIS, CAD_INTERFACE, SERVO
from .urdf import write_urdf

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "out"


def _cq():
    import cadquery as cq
    return cq


def _moved(wp: Any, m: List[float]) -> Any:
    cq = _cq()
    from OCP.gp import gp_Trsf
    tr = gp_Trsf()
    tr.SetValues(
        m[0], m[4], m[8], m[12],
        m[1], m[5], m[9], m[13],
        m[2], m[6], m[10], m[14],
    )
    return cq.Workplane("XY").newObject([wp.val().moved(cq.Location(tr))])


def _color(kind: str) -> Any:
    cq = _cq()
    rgb = [c / 255.0 for c in KINDS[kind]["color"]]
    a = 1.0
    return cq.Color(rgb[0], rgb[1], rgb[2], a)


def build_items() -> List[Dict[str, Any]]:
    """link 局部坐标系里的实体列表。"""
    tree = kinematic_tree()
    plates = {p.name: p for p in all_plates()}
    items: List[Dict[str, Any]] = []
    servo = sts3215_components()["body"]
    accessories = c018_accessories()

    def add(name: str, link: str, kind: str, wp: Any) -> None:
        items.append({"name": name, "link": link, "kind": kind, "wp": wp})

    def pcd_off(axis: Any, u: float, v: float):
        ax, ay, az = float(axis[0]), float(axis[1]), float(axis[2])
        if abs(ay) >= abs(ax) and abs(ay) >= abs(az):
            return (u, 0.0, v)
        if abs(ax) >= abs(az):
            return (0.0, u, v)
        return (u, v, 0.0)

    from .pelvis_cad import screw as mount_screw, cyl
    for j in tree["joints"]:
        jxyz = tuple(float(v) for v in j["xyz"])
        swp = orient_y_to_axis(servo, j["axis"])
        clock = CAD_INTERFACE["housing_clock_deg"].get(j["name"],PELVIS["housing_clock_deg"].get(j["name"],0))
        if clock: swp = swp.rotate((0,0,0),tuple(j["axis"]),clock)
        # The rear pivot is attached to the case. The accessory disc is free
        # to turn around it with the driven link; it is not a case flange.
        pivot = cyl(SERVO["idle_stub_mm"]/2,SERVO["rear_stub_length_mm"],"y",(0,CAD_INTERFACE["vendor_passive_body_face_mm"]-SERVO["rear_stub_length_mm"],0))
        swp = swp.union(orient_y_to_axis(pivot,j["axis"]))
        add(f"servo-{j['name']}",j["parent"],"servo",swp.translate(jxyz))
        for key,prefix in (("drive","horn"),("passive","passive-horn")):
            if key=='passive' and not has_passive_support(j):continue
            add(f"{prefix}-{j['name']}",j["child"],"horn",orient_y_to_axis(accessories[key],j["axis"]))
        if has_passive_support(j):
            tip=CAD_INTERFACE['vendor_passive_body_face_mm']-SERVO['rear_stub_length_mm']
            wt=SERVO['rear_retainer_washer_t_mm'];seat=tip-wt
            washer=cyl(SERVO['rear_retainer_washer_od_mm']/2,wt,'y',(0,seat,0)).cut(cyl(SERVO['rear_retainer_washer_id_mm']/2,wt,'y',(0,seat,0)))
            fast=cyl(1.5,SERVO['rear_retainer_screw_mm'],'y',(0,seat,0)).union(cyl(SERVO['rear_retainer_head_d_mm']/2,SERVO['rear_retainer_head_h_mm'],'y',(0,seat-SERVO['rear_retainer_head_h_mm'],0)))
            for suffix,shape in (('washer',washer),('screw',fast)):
                add(f'rear-retainer-{suffix}-{j["name"]}',j['parent'],'fastener',orient_y_to_axis(shape,j['axis']).translate(jxyz))
                items[-1]['spec']=SERVO['rear_retainer_status']
        shaft = cyl(SERVO["horn_spline_od_mm"]/2,SERVO["output_spline_length_mm"],"y",(0,CAD_INTERFACE["vendor_drive_body_face_mm"],0))
        add(f"shaft-{j['name']}",j["child"],"horn",orient_y_to_axis(shaft,j["axis"]))
        # Central retaining screw is shown separately from the moving disc.
        outer=CAD_INTERFACE["drive_hub_inner_y_mm"]+SERVO["horn_total_t_mm"]
        center=mount_screw(6,"-x",(outer,0,0)).rotate((0,0,0),(0,0,1),90)
        add(f"horn-center-screw-{j['name']}",j["child"],"fastener",orient_y_to_axis(center,j["axis"]))
        leg_joint=any(j['name'].endswith(suffix) for suffix in ('hip_pitch','knee_pitch','ankle_pitch'))
        if j["name"] not in PELVIS["housing_clock_deg"] and not leg_joint and j['name']!='trunk_pitch' and j['group'] not in ('arm_l','arm_r'):
            a=SERVO["horn_hole_square_mm"]/2
            for k,(u,v) in enumerate(((a,a),(a,-a),(-a,a),(-a,-a))):
                screw=mount_screw(4,"-x",(outer+1.5,0,0)).rotate((0,0,0),(0,0,1),90).translate((u,0,v))
                add(f"screw-h-{j['name']}-{k}",j["child"],"fastener",orient_y_to_axis(screw,j["axis"]))
            ic=(0,CAD_INTERFACE["limb_rear_plate_y_mm"],0)
            idle=orient_z_to_axis(plate_solid(plates["IDLE-PLATE"]),(0,1,0)).translate(ic)
            if j["name"] not in ("head_pitch","head_yaw"):
                add(f"idle-{j['name']}",j["child"],"al",orient_y_to_axis(idle,j["axis"]))

    from .leg_cad import build_leg_items
    items.extend(build_leg_items())
    from .arm_cad import build_arm_items
    items.extend(build_arm_items())

    cq = _cq()
    from .pelvis_cad import build_pelvis_items
    items.extend(build_pelvis_items())
    from .hip_dual_cad import build_hip_dual_items
    from .waist_dual_cad import build_waist_dual_items
    additions = build_hip_dual_items() + build_waist_dual_items()
    replaced = {item['replaces'] for item in additions if 'replaces' in item}
    items = [item for item in items if item['name'] not in replaced]
    items.extend(additions)

    from .torso_cad import build_torso_items
    items.extend(build_torso_items())
    from .electronics_mount import build_sbc_mount,build_bus_mount
    items.extend(build_sbc_mount())
    items.extend(build_bus_mount())
    from .battery_mount import build_battery_mount
    items.extend(build_battery_mount())
    from .neck_cad import build_neck_items
    items.extend(build_neck_items())

    from .head_cad import build_head_items
    items.extend(build_head_items())
    from .electronics_cad import build_electronics
    items.extend(build_electronics())
    from .regulator_mount import add_regulator_mount
    items=add_regulator_mount(items)
    from .torso_shell import add_torso_shell
    items=add_torso_shell(items)
    return items


def export_all(out: Path = DEFAULT_OUT) -> Dict[str, Any]:
    """Export every canonical solid through the strict shared review pipeline.

    Manufacturing and physical holds remain explicit; an export failure never
    falls back to a partial assembly or silently drops an STL/union operand.
    """
    from .review_export import export_review
    return export_review(Path(out), manufacturing=True)



def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dest = Path(argv[0]) if argv else DEFAULT_OUT
    info = export_all(dest)
    print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
