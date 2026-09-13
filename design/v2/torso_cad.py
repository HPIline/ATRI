"""Bolted torso frame, square-tube beams and externally clamped shoulder cases."""
import math
import cadquery as cq
from .profile import TORSO as T,CASE_MOUNT as C,K,PELVIS,SERVO
from .case_mount import build_case_clamp
from .pelvis_cad import cyl,screw


def build_torso_items():
    items=[]
    def add(name,kind,wp,**meta):items.append(dict(name=name,link='torso',kind=kind,wp=wp,**meta))
    t=T['plate_t_mm'];sh=K['pelvis_to_shoulder_z']-PELVIS['trunk_roll_z_mm']-PELVIS['trunk_pitch_offset_mm']
    bx=T['beam_x_mm'];zs=[sh+v for v in T['beam_z_offsets_mm']]
    # A plate connects the trunk output to both beams; all remaining plates
    # belong to the fixed cases of their own motors, never their passive discs.
    flat=cq.Workplane('XY').circle(T['output_radius_mm']).extrude(t)
    points=[(0,0),(bx,zs[0]),(bx,zs[1])]
    for a,b in zip(points,points[1:]):
        dx,dz=b[0]-a[0],b[1]-a[1]
        bar=cq.Workplane('XY').box(math.hypot(dx,dz),T['web_mm'],t,centered=(True,True,False)).rotate((0,0,0),(0,0,1),math.degrees(math.atan2(dz,dx))).translate(((a[0]+b[0])/2,(a[1]+b[1])/2,0))
        flat=flat.union(bar)
    for x,z in points[1:]:flat=flat.union(cyl(T['web_mm']/2,t,'z',(x,z,0)))
    a=SERVO['horn_hole_square_mm']/2
    holes=[(x,z) for x in (-a,a) for z in (-a,a)]+[(bx,z) for z in zs]
    for x,z in holes:flat=flat.cut(cyl(1.6,t,'z',(x,z,0)))
    flat=flat.cut(cyl(3.2,t,'z',(0,0,0)))
    for front,yy in ((True,T['front_inner_mm']),(False,T['rear_inner_mm'])):
        tag='front' if front else 'rear';outside=yy+t if front else yy
        add('torso-output-'+tag,'al',flat.rotate((0,0,0),(1,0,0),90).translate((0,outside,0)),flat=flat,manufacturing='laser 6061-T6 1.5 mm; deburr')
        face=19.2 if front else -17.7;length=abs(yy-face)
        for k,(x,z) in enumerate(holes[:4]):
            spacer=cyl(2.5,length,'y',(x,min(yy,face),z)).cut(cyl(1.6,length,'y',(x,min(yy,face),z)))
            add(f'torso-output-spacer-{tag}-{k}','al',spacer,spec=f'M3 OD5 ID3.2 spacer {length:g} mm; split into stocked lengths at release')
            start=yy+t if front else yy-t
            bolt=screw(8,'-x' if front else 'x',(start,0,0)).rotate((0,0,0),(0,0,1),90).translate((x,0,z))
            add(f'torso-output-bolt-{tag}-{k}','fastener',bolt,spec='M3x8 ISO4762')
    for side,yy in (('left',K['shoulder_width']/2),('right',-K['shoulder_width']/2)):
        for p in build_case_clamp(side+'-shoulder-pitch','torso'):
            if '-bolt-' in p['name'] or '-nut-' in p['name']:continue
            if side=='right':p['wp']=p['wp'].rotate((0,0,0),(1,0,0),180)
            p['wp']=p['wp'].translate((0,yy,sh));items.append(p)
    lower=-K['shoulder_width']/2-C['rear_face_mm']+C['plate_t_mm']
    upper=K['shoulder_width']/2+C['rear_face_mm']-C['plate_t_mm']
    by=T['battery_side_y_mm']
    segments=[(lower,-by-t/2),(-by+t/2,T['rear_inner_mm']-t),(T['rear_inner_mm'],T['front_inner_mm']),(T['front_inner_mm']+t,by-t/2),(by+t/2,upper)]
    w,h,wall=T['beam_width_mm'],T['beam_height_mm'],T['beam_wall_mm']
    from .electronics_mount import sbc_holes
    rail_ys=sorted({y for y,z in sbc_holes()})
    for k,z in enumerate(zs):
        for n,(lo,hi) in enumerate(segments):
            length=hi-lo
            tube=cq.Workplane('XZ').rect(w,h).rect(w-2*wall,h-2*wall).extrude(length).translate((bx,hi,z))
            for yy in rail_ys:
                if lo<yy<hi:tube=tube.cut(cyl(T['sbc_beam_clear_d_mm']/2,wall,'x',(bx-w/2,yy,z)))
            if k==1 and lo<0<hi:
                for dx in T['head_clamp_bolt_x_offsets_mm']:
                    for yy in T['head_clamp_bolt_y_mm']:tube=tube.cut(cyl(1.6,h+2,'z',(bx+dx,yy,z-h/2-1)))
            add(f'torso-beam-{k}-{n}','al',tube,stock_cut_length_mm=length,manufacturing=f'stock rectangular tube {w:g}x{h:g}x{wall:g}; saw {length:g} mm; top middle segment has four 3.2 mm vertical holes')
        add('torso-rod-'+str(k),'fastener',cyl(1.5,T['rod_length_mm'],'y',(bx,-T['rod_length_mm']/2,z)),spec=f'M3 threaded rod cut {T["rod_length_mm"]:g} mm; deburr ends')
        for side,start in [('left',K['shoulder_width']/2+C['front_face_mm']+C['plate_t_mm']),('right',-K['shoulder_width']/2-C['front_face_mm']-C['plate_t_mm']-2.4)]:
            nut=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'z',(0,0,0)))
            add(f'torso-rod-nut-{k}-{side}','fastener',nut.rotate((0,0,0),(1,0,0),-90).translate((bx,start,z)),spec='M3 ISO4032')
    yaw=sh+K['shoulder_to_head_yaw'];top_beam=zs[1]+h/2
    for front in (True,False):
        tag='front' if front else 'rear';zz=yaw+(C['front_face_mm'] if front else C['rear_face_mm']-t)
        jaw=cq.Workplane('XY').box(T['head_clamp_width_mm'],C['height_mm'],t,centered=(True,True,False)).translate((bx,0,zz))
        for dx in T['head_clamp_bolt_x_offsets_mm']:
            for yy in T['head_clamp_bolt_y_mm']:jaw=jaw.cut(cyl(1.6,t,'z',(bx+dx,yy,zz)))
        add('torso-head-case-'+tag,'al',jaw,flat=jaw.translate((0,0,-zz)),manufacturing='laser 6061-T6 1.5 mm; head-yaw case clamp')
    for ix,dx in enumerate(T['head_clamp_bolt_x_offsets_mm']):
        for iy,yy in enumerate(T['head_clamp_bolt_y_mm']):
            x=bx+dx;gap=yaw+C['rear_face_mm']-t-top_beam
            spacer=cyl(3.,gap,'z',(x,yy,top_beam)).cut(cyl(1.6,gap,'z',(x,yy,top_beam)))
            add(f'torso-head-spacer-{ix}-{iy}','al',spacer,spec=f'M3 spacer stack {gap:g} mm; source stack to verify')
            start=yaw+C['front_face_mm']+t
            bolt=screw(T['head_clamp_bolt_mm'],'-x',(start,0,0)).rotate((0,0,0),(0,1,0),-90).translate((x,yy,0))
            add(f'torso-head-bolt-{ix}-{iy}','fastener',bolt,spec='M3x55 ISO4762')
            nut=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'z',(0,0,0)))
            add(f'torso-head-nut-{ix}-{iy}','fastener',nut.translate((x,yy,zs[1]-h/2-2.4)),spec='M3 ISO4032')
    return items
