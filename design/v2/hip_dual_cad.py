"""Paired hip-roll support addition; passive side carries radial load only.

The rear angle bears through two spacers on the existing pitch-case rear jaw.
It belongs to hip_roll_link and never attaches the moving disc to the pelvis.
"""
import math
import cadquery as cq
from .profile import HIP_DUAL as D,PELVIS as P,CASE_MOUNT as C,K,SERVO
from .pelvis_cad import cyl,screw
from .cad_parts import c018_accessories,orient_y_to_axis
from .arm_cad import _path


def build_hip_dual_items():
    out=[];t=D['plate_t_mm'];rx=D['rear_outer_x_mm'];sy=D['side_outer_y_mm'];z=-K['hip_stack_z']
    for side in ('left','right'):
        link=side+'_hip_roll_link'
        def add(name,kind,wp,**meta):out.append(dict(name=f'hip-dual-{side}-{name}',link=link,kind=kind,wp=wp,**meta))
        rear=cq.Workplane('XY').circle(D['disc_pad_r_mm']).extrude(t)
        rear=rear.union(_path([(0,0),(sy+t,0),(sy+t,z)],D['web_mm'],t))
        rear=rear.intersect(cq.Workplane('XY').box(100,150,t,centered=(False,True,False)).translate((sy,0,0)))
        rear3=rear.rotate((0,0,0),(1,1,1),120).translate((rx,0,0))
        sideflat=cq.Workplane('XY').box(rx+t-C['x_span_mm'][0],C['height_mm'],t,centered=(True,True,False)).translate(((rx+t+C['x_span_mm'][0])/2,z,0))
        side3=sideflat.rotate((0,0,0),(1,0,0),90).translate((0,sy+t,0))
        angle=rear3.union(side3)
        corners=[e for e in angle.edges('|Z').vals() if abs(e.Center().x-rx)<1e-5 and abs(e.Center().y-(sy+t))<1e-5]
        if corners:angle=angle.newObject(corners).fillet(D['inside_radius_mm'])
        a=SERVO['horn_hole_square_mm']/2
        for yy,zz in ((-a,-a),(-a,a),(a,-a),(a,a)):
            hole=cyl(1.6,t+2,'x',(rx-1,yy,zz));angle=angle.cut(hole)
            rear=rear.cut(cyl(1.6,t,'z',(yy,zz,0)))
            start=rx+t
            for k,length in enumerate(D['pcd_spacer_stack_mm']):
                add(f'pcd-spacer-{yy}-{zz}-{k}','al',cyl(2.5,length,'x',(start,yy,zz)).cut(cyl(1.6,length,'x',(start,yy,zz))),spec=f'M3 OD5 ID3.2 spacer {length:g} mm')
                start+=length
            wt=D['pcd_head_washer_mm']
            add(f'pcd-head-washer-{yy}-{zz}','fastener',cyl(3.5,wt,'x',(rx-wt,yy,zz)).cut(cyl(1.6,wt,'x',(rx-wt,yy,zz))),spec='M3 washer 0.5 mm')
            add(f'pcd-bolt-{yy}-{zz}','fastener',screw(D['pcd_bolt_mm'],'x',(rx-wt,yy,zz)),spec='M3x12; nominal 3 mm projection through rear disc flange, sample fit required')
        angle=angle.cut(cyl(D['centre_clear_mm']/2,t+2,'x',(rx-1,0,0)))
        rear=rear.cut(cyl(D['centre_clear_mm']/2,t,'z',(0,0,0)))
        for k,zz in enumerate(C['bolt_z_mm']):
            pos=z+zz
            angle=angle.cut(cyl(1.6,t+2,'y',(C['bolt_x_mm'],sy-1,pos)))
            sideflat=sideflat.cut(cyl(1.6,t,'z',(C['bolt_x_mm'],pos,0)))
            # Flat-bottom spotface clears the stock-angle inside radius while
            # preserving the full 3 mm cheek under the spacer bearing face.
            # This is a real secondary machining operation, not an overlap filter.
            seat_r=D.get('case_seat_d_mm',7.4)/2
            angle=angle.cut(cyl(seat_r,D['inside_radius_mm']+.1,'y',(C['bolt_x_mm'],sy+t,pos)))
            span=D['case_spacer_mm']
            add(f'case-spacer-{k}','al',cyl(3.5,span,'y',(C['bolt_x_mm'],sy+t,pos)).cut(cyl(1.6,span,'y',(C['bolt_x_mm'],sy+t,pos))),spec=f'M3 OD7 ID3.2 spacer{span:g}')
            start=C['front_face_mm']+P['adapter_t_mm']
            bolt=screw(D['case_bolt_mm'],'-x',(start,0,0)).rotate((0,0,0),(0,0,1),90).translate((C['bolt_x_mm'],0,pos))
            add(f'case-bolt-{k}','fastener',bolt,replaces=f'case-{side}-pitch-bolt-{k}',spec=f"M3x{D['case_bolt_mm']:g} through paired front/rear support stack")
            nut=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'z',(0,0,0)))
            nut=nut.rotate((0,0,0),(1,0,0),-90).translate((C['bolt_x_mm'],sy-2.4,pos))
            add(f'case-nut-{k}','fastener',nut,replaces=f'case-{side}-pitch-nut-{k}',spec='M3 ISO4032')
        add('rear-angle','al',angle,side_flat=sideflat,output_flat=rear,manufacturing='3 mm stock angle, open trim, drill PCD14 and two clamp holes; insideR3; two D7.4 flat-bottom spotfaces to cheek inside plane for OD7 spacers; qualify stock section',qualification='Rear bearing and clamp preload still require sample')
    return out
