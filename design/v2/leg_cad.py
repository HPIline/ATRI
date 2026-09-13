"""Flat aluminium leg links with external case clamps and a bolted foot.

The clamp is a candidate mounting method, not a qualified friction joint.
Its preload, slip and plastic-case creep remain G2 sample requirements.
"""
from __future__ import annotations

import math
import cadquery as cq

from .profile import K, SERVO, CASE_MOUNT as C
from .case_mount import build_case_clamp
from .pelvis_cad import cyl, screw


def parameters():
    from .profile import LEG
    return LEG


def _nut():
    return (cq.Workplane("XY").polygon(6, 5.5 / math.cos(math.pi / 6))
            .extrude(2.4).cut(cq.Workplane("XY").circle(1.25).extrude(2.4)))


def _ring(outer, inner, length, y, x, z):
    return cyl(outer / 2, length, "y", (x, y, z)).cut(
        cyl(inner / 2, length, "y", (x, y, z)))


def _flat_path(points, thickness, width):
    shape = None
    for a, b in zip(points, points[1:]):
        dx, dz = b[0] - a[0], b[1] - a[1]
        bar = (cq.Workplane("XY").box(math.hypot(dx, dz), width, thickness,
                                     centered=(True, True, False))
               .rotate((0, 0, 0), (0, 0, 1), math.degrees(math.atan2(dz, dx)))
               .translate(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 0)))
        shape = bar if shape is None else shape.union(bar)
    for x, z in points:
        shape = shape.union(cq.Workplane("XY").center(x, z).circle(width / 2).extrude(thickness))
    return shape


def output_flat(length=None, foot=False, rear_thigh=False):
    p = parameters(); t = p["plate_t_mm"]
    plate = cq.Workplane("XY").circle(p["output_r_mm"]).extrude(t)
    if foot:
        z = -p["foot_height_mm"] + K["sole_t"] + p["foot_plate_t_mm"] + p["foot_angle_vertical_hole_mm"]
        points = [(0, 0), (0, z)]
        holes = [(x, z) for x in p["foot_angle_hole_x_mm"]]
        # A continuous lower flange carries two bracket bolts.
        plate = plate.union(cq.Workplane("XY").box(p["foot_angle_length_mm"], p["web_mm"], t,
                                                    centered=(True, True, False)).translate((0, z, 0)))
    else:
        holes = [(C["bolt_x_mm"], -length + z) for z in C["bolt_z_mm"]]
        points = [(0, 0)] + ([p["thigh_rear_web_waypoint_mm"]] if rear_thigh else []) + [holes[1], holes[0]]
    plate = plate.union(_flat_path(points, t, p["web_mm"]))
    for x, z in holes:
        plate = plate.union(cq.Workplane("XY").center(x, z).circle(p["pad_r_mm"]).extrude(t))
    a = SERVO["horn_hole_square_mm"] / 2
    holes += [(x, z) for x in (-a, a) for z in (-a, a)]
    for x, z in holes:
        plate = plate.cut(cq.Workplane("XY").center(x, z).circle(SERVO["horn_clear_mm"] / 2).extrude(t))
    return plate.cut(cq.Workplane("XY").circle(3.2).extrude(t))


def _side(flat, inner, front):
    t = parameters()["plate_t_mm"]
    return flat.rotate((0, 0, 0), (1, 0, 0), 90).translate((0, inner + t if front else inner, 0))


def build_leg_items():
    p = parameters(); t = p["plate_t_mm"]
    result = []
    def add(name, link, kind, wp, **metadata):
        result.append(dict(name=name, link=link, kind=kind, wp=wp, **metadata))

    def spacer_stack(name,link,outer,length,start,x,z):
        remaining=round(length,6);offset=0.;index=0
        for nominal in p['spacer_lengths_mm']:
            while remaining>=nominal-1e-6:
                kind='fastener' if nominal<=.5 else 'al'
                add(f'{name}-{index}',link,kind,_ring(outer,3.2,nominal,start+offset,x,z),
                    spec=f'M3 plain spacer/shim OD{outer:g} ID3.2 length {nominal:g} mm; supplier SKU to verify')
                remaining=round(remaining-nominal,6);offset+=nominal;index+=1
        if remaining>1e-6:raise ValueError(f'Unresolved spacer stack: {name} {length}')

    for side in ("left", "right"):
        for level, segment in enumerate(("thigh", "shank", "foot")):
            link = f"{side}_{segment}"
            length = K.get(segment)
            flat = output_flat(length, foot=segment == "foot")
            front, rear = p["front_inner_mm"][level], p["rear_inner_mm"][level]
            for is_front, inner, face in ((True, front, 19.2), (False, rear, -17.7)):
                tag = f"leg-{side}-{segment}-{'front' if is_front else 'rear'}"
                side_flat = output_flat(length, rear_thigh=True) if level == 0 and not is_front else flat
                add(tag, link, "al", _side(side_flat, inner, is_front), flat=side_flat,
                    manufacturing="laser 6061-T6 1.5 mm; deburr", connection="upper output to lower fixed case clamp" if level < 2 else "ankle output to foot angle")
                a = SERVO["horn_hole_square_mm"] / 2
                for n, (x, z) in enumerate(( (x, z) for x in (-a, a) for z in (-a, a) )):
                    spacer = abs(inner - face)
                    spacer_stack(f'{tag}-horn-spacer-{n}',link,5.,spacer,min(inner,face),x,z)
                    start = inner + t if is_front else inner - t
                    bolt = screw(p["horn_bolt_mm"][level], "-x", (0, 0, 0)).rotate((0, 0, 0), (0, 0, 1), 90)
                    if not is_front:
                        bolt = bolt.rotate((0, 0, 0), (1, 0, 0), 180)
                    add(f"{tag}-horn-bolt-{n}", link, "fastener", bolt.translate((x, start, z)),
                        spec=f"M3x{p['horn_bolt_mm'][level]:g} ISO4762; C018 PCD14 tapped disc")
            if level < 2:
                # Keep both clamp jaws, but replace the original bolts with
                # through bolts spanning the two structural side plates.
                for item in build_case_clamp(f"{side}-{segment}-lower", link):
                    if "-bolt-" in item["name"] or "-nut-" in item["name"]:
                        continue
                    item["wp"] = item["wp"].translate((0, 0, -length))
                    result.append(item)
                jaw_front = C["front_face_mm"] + C["plate_t_mm"]
                jaw_rear = C["rear_face_mm"]-C['plate_t_mm']
                for n, zz in enumerate(C["bolt_z_mm"]):
                    x, z = C["bolt_x_mm"], -length + zz
                    for label, start, end in (("front", jaw_front, front), ("rear", rear, jaw_rear)):
                        spacer_stack(f'leg-{side}-{segment}-clamp-spacer-{label}-{n}',link,6.,end-start,start,x,z)
                    washer = p["clamp_head_washer_mm"][level]
                    if washer:
                        add(f"leg-{side}-{segment}-clamp-head-spacer-{n}", link, "fastener",
                            _ring(7, 3.2, washer, front+t, x, z), spec=f"M3 spacer washer {washer:g} mm")
                    start = front+t+washer
                    bolt = screw(p["clamp_bolt_mm"][level], "-x", (0,0,0)).rotate((0,0,0),(0,0,1),90).translate((x,start,z))
                    add(f"leg-{side}-{segment}-clamp-bolt-{n}", link, "fastener", bolt,
                        spec=f"M3x{p['clamp_bolt_mm'][level]:g} ISO4762", qualification=C["qualification"])
                    add(f"leg-{side}-{segment}-clamp-nut-{n}", link, "fastener",
                        _nut().rotate((0,0,0),(1,0,0),-90).translate((x,rear-t-2.4,z)), spec="M3 ISO4032")
            else:
                result.extend(_foot_items(side))
    return result


def _foot_items(side):
    p=parameters(); link=f"{side}_foot"; parts=[]
    def add(name,kind,wp,**meta):
        parts.append(dict(name=f"leg-{side}-foot-{name}",link=link,kind=kind,wp=wp,**meta))
    h=p["foot_height_mm"]; t=p["foot_plate_t_mm"]; bottom=-h+K["sole_t"]; top=bottom+t
    cx=K["foot_l"]/2-K["ankle_from_heel"]
    plate=cq.Workplane("XY").box(K["foot_l"],K["foot_w"],t,centered=(True,True,False)).edges("|Z").fillet(p["foot_edge_r_mm"]).translate((cx,0,bottom))
    for xa,xb in p['foot_lightening_x_ranges_mm']:
        for yy in p['foot_lightening_y_mm']:
            window=cq.Workplane('XY').box(xb-xa,p['foot_lightening_width_mm'],t,centered=(True,True,False)).edges('|Z').fillet(p['foot_lightening_radius_mm']).translate(((xa+xb)/2,yy,bottom))
            plate=plate.cut(window)
    laser_blank=plate
    for front,inner in ((True,p["front_inner_mm"][2]),(False,p["rear_inner_mm"][2])):
        sign=1 if front else -1; label="front" if front else "rear"
        leg=p["foot_angle_leg_mm"]; at=p["foot_angle_t_mm"]; length=p["foot_angle_length_mm"]
        center_y=inner-sign*leg/2
        angle=cq.Workplane("XY").box(length,leg,at,centered=(True,True,False)).translate((0,center_y,top))
        angle=angle.union(cq.Workplane("XY").box(length,at,leg,centered=(True,True,False)).translate((0,inner-sign*at/2,top)))
        corner=(0,inner-sign*at,top+at)
        angle=angle.edges(cq.selectors.NearestToPointSelector(corner)).fillet(p["foot_angle_inner_r_mm"])
        hole_y=inner-sign*p["foot_angle_horizontal_hole_mm"]
        hole_z=top+p["foot_angle_vertical_hole_mm"]
        for n,x in enumerate(p["foot_angle_hole_x_mm"]):
            angle=angle.cut(cyl(1.6,leg+2,"y",(x,inner-leg-1 if front else inner-1,hole_z)))
            angle=angle.cut(cq.Workplane("XY").center(x,hole_y).circle(1.6).extrude(at).translate((0,0,top)))
            # DIN 7991 nominal countersunk head keeps the sole unpunctured.
            hole=cq.Workplane("XY").center(x,hole_y).circle(1.6).extrude(t).translate((0,0,bottom))
            laser_blank=laser_blank.cut(hole)
            # A 90-degree countersink has axial depth equal to the radius
            # difference. The old 1.7 mm cone was only 82.8 degrees.
            cone=cq.Solid.makeCone(3.0,1.6,3.0-1.6).translate((x,hole_y,bottom))
            plate=plate.cut(hole).cut(cone)
            fast=cq.Workplane("XY").newObject([cq.Solid.makeCone(3.,1.5,3.-1.5)]).union(cq.Workplane("XY").circle(1.5).extrude(8.0))
            fast=fast.cut(cq.Workplane("XY").polygon(6,2./math.cos(math.pi/6)).extrude(1.1))
            add(f"{label}-base-bolt-{n}","fastener",fast.translate((x,hole_y,bottom)),spec="M3x8 DIN7991 countersunk; nominal thread")
            add(f"{label}-base-nut-{n}","fastener",_nut().translate((x,hole_y,top+at)),spec="M3 ISO4032")
            bolt=screw(8,"-x",(0,0,0)).rotate((0,0,0),(0,0,1),90)
            if not front:bolt=bolt.rotate((0,0,0),(1,0,0),180)
            add(f"{label}-side-bolt-{n}","fastener",bolt.translate((x,inner+sign*p['plate_t_mm'],hole_z)),spec="M3x8 ISO4762")
            nut=_nut().rotate((0,0,0),(1,0,0),-90).translate((x,inner-at-2.4 if front else inner+at,hole_z))
            add(f"{label}-side-nut-{n}","fastener",nut,spec="M3 ISO4032")
        add(f"{label}-angle","al",angle,manufacturing="cut/drill stock 15x15x1.5 aluminium angle; 20 mm long; inside radius <=1.5 mm purchase constraint")
    add("plate","al",plate,flat=laser_blank.translate((0,0,-bottom)),manufacturing=f"laser 6061-T6 {t:g} mm; four M3 countersinks after cutting; deburr")
    sole=cq.Workplane("XY").box(K["foot_l"]-2,K["foot_w"]-2,K["sole_t"],centered=(True,True,False)).edges("|Z").fillet(6).translate((cx,0,-h))
    add("sole","tpu",sole,print_face='-Z',manufacturing="TPU95A; adhesive bond to aluminium; bond qualification required")
    return parts
