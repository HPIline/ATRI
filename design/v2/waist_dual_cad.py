"""Waist roll rear stock-angle support on the moving roll link."""
import math
import cadquery as cq
from v2.pelvis_cad import cyl,screw

from .profile import WAIST_DUAL as D, SERVO

def build_waist_dual_items():
    parts=[]
    def add(name,kind,wp,**kw):parts.append(dict(name='waist-dual-'+name,link='trunk_roll_link',kind=kind,wp=wp,**kw))
    t=D['plate_t_mm']; rear_x=D['rear_outer_x_mm']; y_side=D['side_outer_y_mm']; bolt_z=D['clamp_z_mm']
    # One stock-angle shell: rear YZ wing and XZ return wing, through cutouts only.
    rear=cyl(D['disc_pad_radius_mm'],t,'x',(rear_x,0,0))
    for (a,b) in [((0,0),((y_side+D['rear_web_mm']/2),0)),(((y_side+D['rear_web_mm']/2),0),((y_side+D['rear_web_mm']/2),D['return_center_z_mm']))]:
        dy,dz=b[0]-a[0],b[1]-a[1]
        w=cq.Workplane('XY').box(math.hypot(dy,dz),D['rear_web_mm'],t,centered=(True,True,False)).rotate((0,0,0),(0,0,1),math.degrees(math.atan2(dz,dy))).translate(((a[0]+b[0])/2,(a[1]+b[1])/2,0))
        rear=rear.union(w.rotate((0,0,0),(1,1,1),120).translate((rear_x,0,0)))
    rear=rear.union(cq.Workplane('XY').box(t,D['return_join_mm'],D['return_width_mm']).translate((rear_x+t/2,y_side+D['return_join_mm']/2,D['return_center_z_mm'])))
    rear=rear.intersect(cq.Workplane('XY').box(200,150,200,centered=(True,False,True)).translate((0,y_side,0)))
    side=cq.Workplane('XY').box(D['side_length_mm'],t,D['return_width_mm']).translate((D['side_center_x_mm'],y_side+t/2,D['return_center_z_mm']))
    support=rear.union(side)
    r=D['inside_radius_mm']; ix=rear_x+t; iy=y_side+t
    zlow=D['return_center_z_mm']-D['return_width_mm']/2
    fillet=cq.Workplane('XY').box(r,r,D['return_width_mm'],centered=(False,False,False)).translate((ix,iy,zlow)).cut(cyl(r,D['return_width_mm'],'z',(ix+r,iy+r,zlow)))
    support=support.union(fillet)
    end_edges=[e for e in support.edges('|Y').vals() if abs(e.Center().x-(D['side_center_x_mm']+D['side_length_mm']/2))<1e-5]
    support=support.newObject(end_edges).fillet(D['end_radius_mm'])
    a=SERVO['horn_hole_square_mm']/2
    for y,z in ((-a,-a),(-a,a),(a,-a),(a,a)):
        support=support.cut(cyl(1.6,t+2,'x',(rear_x-1,y,z)))
        start=rear_x+t
        for k,length in enumerate(D['pcd_spacer_stack_mm']):
            add(f'pcd-spacer-{y}-{z}-{k}','al',cyl(2.5,length,'x',(start,y,z)).cut(cyl(1.6,length,'x',(start,y,z))),spec=f'M3 OD5 ID3.2 spacer {length:g} mm')
            start+=length
        wt=D['head_washer_mm']
        add(f'pcd-washer-{y}-{z}','fastener',cyl(3.5,wt,'x',(rear_x-wt,y,z)).cut(cyl(1.6,wt,'x',(rear_x-wt,y,z))),spec='M3 washer 0.5 mm')
        add(f'pcd-screw-{y}-{z}','fastener',screw(D['pcd_bolt_mm'],'x',(rear_x-wt,y,z)),spec='M3x12; 3 mm nominal projection through rear flange; qualify sample thread fit')
    support=support.cut(cyl(D['centre_clear_mm']/2,t+2,'x',(rear_x-1,0,0)))
    support=support.cut(cyl(1.6,t+2,'y',(D['clamp_x_mm'],y_side-1,bolt_z)))
    # Orthographic cutting templates taken from finished outer flange faces.
    def flange_template(axis, value, transform):
        faces=[f for f in support.val().Faces() if abs(getattr(f.Center(),axis)-value)<1e-5 and abs(getattr(f.normalAt(),axis))>.999]
        face=max(faces,key=lambda f:f.Area())
        face=transform(face)
        return cq.Workplane('XY').newObject([cq.Solid.extrudeLinear(face.outerWire(),face.innerWires(),cq.Vector(0,0,t))])
    rear_flat=flange_template('x',rear_x,lambda f:f.translate((-rear_x,0,0)).rotate((0,0,0),(1,1,1),-120))
    side_flat=flange_template('y',y_side,lambda f:f.translate((0,-y_side,0)).rotate((0,0,0),(1,0,0),90))
    add('rear-angle','al',support,output_flat=rear_flat,side_flat=side_flat,manufacturing='Saw/drill 75x50x3 stock angle, 55 mm axial blank; open trim, PCD14, clamp hole; retain inside R3. Verify supplied corner radius before cutting.', stock_section_mm=(75,50,3), stock_cut_length_mm=55, qualification='Stock availability, material certificate, bearing rating and clamp preload require qualification')
    start=y_side+t
    for k,length in enumerate(D['clamp_spacer_stack_mm']):
        add(f'clamp-spacer-{k}','al',cyl(3.5,length,'y',(D['clamp_x_mm'],start,bolt_z)).cut(cyl(1.6,length,'y',(D['clamp_x_mm'],start,bolt_z))),spec=f'M3 OD7 ID3.2 spacer {length:g} mm')
        start+=length
    clamp_bolt=screw(D['clamp_bolt_mm'],'-x',(20,0,0)).rotate((0,0,0),(0,0,1),90).translate((-D['clamp_x_mm'],0,-15)).rotate((0,0,0),(0,1,0),180).translate((0,0,25))
    add('clamp-replacement-bolt','fastener',clamp_bolt,replaces='case-trunk-pitch-bolt-0',spec=f"M3x{D['clamp_bolt_mm']:g}; rear support through bolt")
    nut=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'z',(0,0,0)))
    nut=nut.rotate((0,0,0),(1,0,0),-90).translate((D['clamp_x_mm'],y_side-2.4,bolt_z))
    add('clamp-replacement-nut','fastener',nut,replaces='case-trunk-pitch-nut-0',spec='M3 ISO4032, relocated behind new rear angle')
    return parts
