"""Test a provisional connector reservation; never add it to production geometry.

A passing reservation cannot qualify a real connector. A failed reservation is
an actionable packaging risk. The C018 supplier's plug drawing is still absent.
"""
from pathlib import Path
import json
import cadquery as cq
from .cad_export import build_items
from .cad_parts import orient_y_to_axis
from .profile import CAD_INTERFACE,PELVIS,CONNECTOR_STUDY as C
from .assembly3d import kinematic_tree
from .cad_audit import intersections


def reservations():
    items=[]
    for joint in kinematic_tree()['joints']:
        for index,z in enumerate(C['port_z_mm']):
            shape=cq.Workplane('XY').box(*C['body_xyz_mm']).translate((*C['center_xy_mm'],z))
            shape=orient_y_to_axis(shape,joint['axis'])
            clock=CAD_INTERFACE['housing_clock_deg'].get(joint['name'],PELVIS['housing_clock_deg'].get(joint['name'],0))
            if clock:shape=shape.rotate((0,0,0),tuple(joint['axis']),clock)
            items.append(dict(name=f'connector-reserve-{joint["name"]}-{index}',link=joint['parent'],kind='connector_white',wp=shape.translate(joint['xyz']),status=C['status']))
    return items


def report():
    items=build_items()+reservations();tree=kinematic_tree()
    result=dict(status=C['status'],source=C['source'],production_connector_verified=False,zero=intersections(items),poses=[])
    for joint in tree['joints']:
        for limit in joint['limit_deg']:
            angles=[limit if j['name']==joint['name'] else 0 for j in tree['joints']]
            hits=intersections(items,angles,include_same_link=False)
            result['poses'].append(dict(joint=joint['name'],angle_deg=limit,**hits))
    result['reservation_ok']=result['zero']['ok'] and all(p['ok'] for p in result['poses'])
    return result


if __name__=='__main__':
    r=report();path=Path(__file__).parent/'out/connector-reservation-audit.json'
    path.write_text(json.dumps(r,ensure_ascii=False,indent=2))
    print(json.dumps(dict(file=str(path),reservation_ok=r['reservation_ok'],production_connector_verified=False)))
