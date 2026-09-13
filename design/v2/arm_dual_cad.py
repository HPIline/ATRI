"""Two-sided arm support candidate; rear discs are free radial bearings.

The rear stock-angle leg overlaps the existing case cheek as a bolted lap,
not an unsupported butt joint. Integration must use the updated through bolts
and add C018 passive discs/retainers on the shoulder and elbow axes.
"""
from copy import deepcopy
import math
import cadquery as cq
from .profile import ARM, ARM_DUAL as D, CASE_MOUNT, K, SERVO
from .arm_cad import _orthogonal, _transform, build_arm_items
from .pelvis_cad import screw, cyl


def build_arm_dual_items():
    parts = build_arm_items()
    for side in ('left', 'right'):
        for segment, link, target, clock, swapped in (
            ('shoulder', side+'_upper', (ARM['shoulder_offset_mm'],0,0), -90, True),
            ('upper', side+'_fore', (0,0,-K['upper_arm']), 0, False),
            ('fore', side+'_hand', (0,0,K['forearm']), 180, True),
        ):
            tag=side+'-'+segment
            design=deepcopy(ARM)
            design['output_front_mm']=D['rear_outer_mm']
            # Both PCD rings use plain clearance holes, with separate screws.
            design['plain_output']=True
            if segment=='shoulder':
                design['bridge_z_override']=D['shoulder_bridge_z_mm']
                design['output_path_override']=D['shoulder_output_route_mm']
            if segment=='upper':
                design['upper_bridge_drop_mm']=D['upper_bridge_drop_mm']
                design['web_mm']=D['upper_web_mm'][side]
                route=D['upper_route_y_mm'][side]
                design['output_path_override']=[(0,0),(route,D['upper_route_elbow_z_mm']),(route,D['upper_route_bottom_z_mm']),(D['lap_outer_y_mm']-ARM['angle_t_mm'],D['upper_route_bottom_z_mm'])]
                design['allow_output_outside_case']=True
            case=deepcopy(CASE_MOUNT)
            case['front_face_mm']+=ARM['angle_t_mm']
            # Suppress fore-specific countersinks: back face takes ISO4762.
            buildtag='left-'+segment if segment=='shoulder' else tag
            rear=_orthogonal(buildtag,link,target,clock,swapped,design=design,case=case)
            angle=next(p for p in rear if p['name'].endswith('-angle'))
            angle['name']='arm-'+tag+'-rear-angle'
            angle['qualification']='Rear free-bearing lap support candidate; full assembly sweep and preload qualification required'
            if side=='right' and segment=='shoulder':
                angle['wp']=angle['wp'].mirror('XZ')
            original=next(p for p in parts if p['name']=='arm-'+tag+'-angle')
            # The stock inside radius needs open relief where the original
            # angle crosses the new lap. This is a trim, not a hidden overlap.
            angle['wp']=angle['wp'].cut(original['wp'])
            canonical=angle['wp']
            if side=='right' and segment=='shoulder':canonical=canonical.mirror('XZ')
            canonical=_transform(canonical,swapped)
            # Turn radius relief into a through-cut contour, so the output
            # cheek has one real 2-D template rather than a hidden pocket.
            flat=None
            for depth in (.001,.75,1.5,2.25,2.999):
                section=cq.Workplane('YZ',origin=(design['output_front_mm']+depth,0,0)).newObject([canonical.val()]).section()
                candidate=section.wires().toPending().extrude(ARM['angle_t_mm'],combine=False).translate((-design['output_front_mm']-depth,0,0)).rotate((0,0,0),(1,1,1),-120)
                flat=candidate if flat is None else flat.intersect(candidate)
            extent=ARM['clip_extent_mm']
            slab=cq.Workplane('XY').box(ARM['angle_t_mm'],extent,extent,centered=(False,True,True)).translate((design['output_front_mm'],0,0))
            canonical=canonical.cut(slab).union(flat.rotate((0,0,0),(1,1,1),120).translate((design['output_front_mm'],0,0)))
            angle['output_flat']=flat
            angle['wp']=_transform(canonical,swapped)
            # Rear shoulder cheek must clear torso shell; trim the outer rear edge.
            if segment=='shoulder':
                relief=cq.Workplane('XY').box(8.,80.,80.,centered=(False,True,True)).translate((-31.,0,0))
                angle['wp']=angle['wp'].cut(relief)
            if side=='right' and segment=='shoulder':angle['wp']=angle['wp'].mirror('XZ')
            angle['manufacturing']=angle['manufacturing'].replace('; four DIN7991 countersinks after drilling','')+'; use updated output through-cut template, no countersinks'
            parts.append(angle)
            def posed(wp):
                wp=wp.rotate((0,0,0),(0,1,0),clock).translate(target)
                wp=_transform(wp,swapped)
                if side=='right' and segment=='shoulder':wp=wp.mirror('XZ')
                return wp
            for k,zbolt in enumerate(CASE_MOUNT['bolt_z_mm']):
                name=f'case-{tag}-bolt-{k}'
                old=next((p for p in parts if p['name']==name),None)
                if old is not None:
                    old['wp']=posed(screw(D['case_bolt_mm'],'-x',(D['lap_outer_y_mm'],0,0)).rotate((0,0,0),(0,0,1),90).translate((CASE_MOUNT['bolt_x_mm'],0,zbolt)))
                    old['spec']='M3x45 ISO4762 through both 3 mm cheeks; sample preload required'
                    if side=='left' and segment=='shoulder' and k==0:
                        cap=cq.Workplane('XY').newObject([cq.Solid.makeCone(3.,1.5,1.5)])
                        shaft=cyl(1.5,D['case_bolt_mm'],'z',(0,0,0))
                        socket=cq.Workplane('XY').polygon(6,2/math.cos(math.pi/6)).extrude(1.1)
                        fast=cap.union(shaft).cut(socket).rotate((0,0,0),(1,0,0),90).translate((CASE_MOUNT['bolt_x_mm'],D['lap_outer_y_mm'],zbolt))
                        old['wp']=posed(fast)
                        old['spec']='M3x45 DIN7991 countersunk, length includes head; left shoulder folded-arm clearance'
                        sink=cq.Workplane('XY').newObject([cq.Solid.makeCone(3.,1.6,1.4)]).rotate((0,0,0),(1,0,0),90).translate((CASE_MOUNT['bolt_x_mm'],D['lap_outer_y_mm'],zbolt))
                        angle['wp']=angle['wp'].cut(posed(sink))
                        angle['manufacturing']+='; countersink first case-lap hole DIN7991 D6 90deg after drilling'

                if side=='right' and segment=='upper':
                    nut=next(p for p in parts if p['name']==f'case-{tag}-nut-{k}')
                    wp=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'z',(0,0,0)))
                    nut['wp']=posed(wp.rotate((0,0,0),(1,0,0),-90).translate((CASE_MOUNT['bolt_x_mm'],-21.6,zbolt)))
            if segment=='fore':
                for old in parts:
                    if old['name'].startswith(f'arm-{side}-gripper-fixed-spacer-'):
                        old['wp']=old['wp'].cut(angle['wp'])
                        old['spec']='M3 plain spacer shortened to 2 mm for rear-cheek lap'

            a=SERVO['horn_hole_square_mm']/2
            face=design['output_front_mm']
            for n,(y,z) in enumerate(((a,a),(a,-a),(-a,a),(-a,-a))):
                wp=screw(D['rear_horn_bolt_mm'],'x',(face-D['rear_head_washer_mm'],y,z))
                wp=_transform(wp,swapped)
                if side=='right' and segment=='shoulder':wp=wp.mirror('XZ')
                parts.append(dict(name=f'arm-{tag}-rear-output-bolt-{n}',link=link,kind='fastener',wp=wp,spec='M3x8 ISO4762; 0.5 mm washer + 3 mm cheek + 2.5 mm spacers + 2 mm C018 passive-disc thread; free radial bearing'))
                for label,start,span,kind in [('head-washer',face-.5,.5,'fastener'),('spacer',face+3,2.,'al'),('shim',face+5,.5,'fastener')]:
                    ring=cyl(2.5,span,'x',(start,y,z)).cut(cyl(1.6,span,'x',(start,y,z)))
                    ring=_transform(ring,swapped)
                    if side=='right' and segment=='shoulder':ring=ring.mirror('XZ')
                    parts.append(dict(name=f'arm-{tag}-rear-{label}-{n}',link=link,kind=kind,wp=ring,spec=f'M3 plain {label} OD5 ID3.2 length{span:g}mm'))

    return parts

