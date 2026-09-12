"""Bolted neck fork: laser-cut cheeks and base, two stock angle brackets."""
import math
import cadquery as cq
from .profile import NECK as N,CASE_MOUNT as C,PELVIS,SERVO
from .case_mount import build_case_clamp
from .pelvis_cad import cyl,screw


def build_neck_items():
    items=[]
    def add(name,kind,wp,**meta):items.append(dict(name=name,link='head_yaw_link',kind=kind,wp=wp,**meta))
    t=N['base_t_mm'];z0=N['base_z_mm'];top=z0+t
    x0,x1=N['base_x_mm'];y0,y1=N['base_y_mm'];mx=C['bolt_x_mm']
    base=cq.Workplane('XY').box(x1-x0,y1-y0,t,centered=(True,True,False)).translate(((x0+x1)/2,0,0))
    a=SERVO['horn_hole_square_mm']/2
    for x,y in ((a,a),(a,-a),(-a,a),(-a,-a)):
        base=base.cut(cyl(N['bolt_clear_mm']/2,t,'z',(x,y,0)))
    base=base.cut(cyl(3.2,t,'z',(0,0,0)))
    countersinks=[]
    for front in (True,False):
        face=C['front_face_mm'] if front else C['rear_face_mm']
        inward=-1 if front else 1
        yy=face+inward*N['angle_hole_offset_mm']
        base=base.cut(cyl(N['bolt_clear_mm']/2,t,'z',(mx,yy,0)))
        sink=cq.Solid.makeCone(N['csk_head_mm']/2,N['bolt_clear_mm']/2,N['csk_depth_mm'])
        countersinks.append(cq.Workplane('XY').newObject([sink]).translate((mx,yy,0)))
    blank=base
    for sink in countersinks:base=base.cut(sink)
    add('neck-base','al',base.translate((0,0,z0)),flat=blank,manufacturing='laser 6061-T6 2 mm; two underside countersinks after cutting')
    for front in (True,False):
        tag='front' if front else 'rear';face=C['front_face_mm'] if front else C['rear_face_mm']
        inward=-1 if front else 1
        xx0,xx1=C['x_span_mm'];height=PELVIS['head_pitch_z_mm']+C['height_mm']/2-top
        flat=cq.Workplane('XY').box(xx1-xx0,height,C['plate_t_mm'],centered=(True,False,False)).translate(((xx0+xx1)/2,top,0))
        holes=[PELVIS['head_pitch_z_mm']+v for v in C['bolt_z_mm']]+[top+N['angle_hole_z_mm']]
        for zz in holes:flat=flat.cut(cyl(N['bolt_clear_mm']/2,C['plate_t_mm'],'z',(mx,zz,0)))
        cheek=flat.rotate((0,0,0),(1,0,0),90).translate((0,face+C['plate_t_mm'] if front else face,0))
        add('neck-cheek-'+tag,'al',cheek,flat=flat,manufacturing='laser 6061-T6 1.5 mm; external case clamp')
        leg=N['angle_leg_mm'];at=N['angle_t_mm'];length=N['angle_length_mm']
        horizontal=cq.Workplane('XY').box(length,leg,at).translate((mx,face+inward*leg/2,top+at/2))
        vertical=cq.Workplane('XY').box(length,at,leg).translate((mx,face+inward*at/2,top+leg/2))
        bracket=horizontal.union(vertical)
        corner=(mx,face+inward*at,top+at)
        bracket=bracket.edges(cq.selectors.NearestToPointSelector(corner)).fillet(N['angle_inner_r_mm'])
        yy=face+inward*N['angle_hole_offset_mm'];zz=top+N['angle_hole_z_mm']
        bracket=bracket.cut(cyl(N['bolt_clear_mm']/2,leg,'z',(mx,yy,top)))
        bracket=bracket.cut(cyl(N['bolt_clear_mm']/2,2*leg,'y',(mx,face-leg,zz)))
        add('neck-angle-'+tag,'al',bracket,stock_angle_mm=(leg,leg,at),stock_cut_length_mm=length,manufacturing=f'stock {leg:g}x{leg:g}x{at:g} angle, saw {length:g} mm; inner R{N["angle_inner_r_mm"]:g}; drill two 3.2 mm holes')
        # Countersunk bolt is flush below the base, above the yaw case.
        head=cq.Workplane('XY').newObject([cq.Solid.makeCone(N['csk_head_mm']/2,1.5,N['csk_depth_mm'])])
        fast=head.union(cyl(1.5,N['base_screw_mm']-N['csk_depth_mm'],'z',(0,0,N['csk_depth_mm'])))
        fast=fast.cut(cq.Workplane('XY').polygon(6,N['csk_socket_af_mm']/math.cos(math.pi/6)).extrude(N['csk_socket_depth_mm']))
        add('neck-base-bolt-'+tag,'fastener',fast.translate((mx,yy,z0)),spec='M3x8 DIN7991; length includes countersunk head')
        nut=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'z',(0,0,0)))
        add('neck-base-nut-'+tag,'fastener',nut.translate((mx,yy,top+at)),spec='M3 ISO4032')
        outside=face+C['plate_t_mm'] if front else face-C['plate_t_mm']
        bolt=screw(N['side_screw_mm'],'-x' if front else 'x',(outside,0,0)).rotate((0,0,0),(0,0,1),90).translate((mx,0,zz))
        add('neck-side-bolt-'+tag,'fastener',bolt,spec='M3x8 ISO4762')
        ny=face-at-2.4 if front else face+at
        add('neck-side-nut-'+tag,'fastener',nut.rotate((0,0,0),(1,0,0),-90).translate((mx,ny,zz)),spec='M3 ISO4032')
    for p in build_case_clamp('head-pitch','head_yaw_link',False,False):
        p['wp']=p['wp'].translate((0,0,PELVIS['head_pitch_z_mm']));items.append(p)
    return items
