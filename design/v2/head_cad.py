"""Split PETG camera head and real output arms. All dimensions use profile.py."""
import math
import cadquery as cq
from .profile import HEAD as H,ELECTRONICS as E,SERVO
from .pelvis_cad import cyl,screw


def build_head_items():
    parts=[]
    def add(name,kind,wp,**meta):parts.append(dict(name=name,link='head',kind=kind,wp=wp,**meta))
    x0,y0,z0,x1,y1,z1=H['bounds_mm'];t=H['wall_mm'];margin=H['boolean_margin_mm']
    outer=cq.Workplane('XY').box(x1-x0,y1-y0,z1-z0).translate(((x0+x1)/2,0,(z0+z1)/2))
    outer=outer.edges('|X').fillet(H['outer_corner_r_mm'])
    inner=cq.Workplane('XY').box(x1-x0-2*t,y1-y0-2*t,z1-z0-2*t).translate(((x0+x1)/2,0,(z0+z1)/2))
    shell=outer.cut(inner)
    cx,cy,cz=E['camera']['position_mm']
    shell=shell.cut(cyl(H['lens_hole_mm']/2,t+2*margin,'x',(x1-t-margin,cy,cz)))
    # Cable slot opens downwards; the camera uses USB SH1.0, never a CSI ribbon.
    slot=cq.Workplane('XY').box(*H['usb_slot_xy_mm'],t+2*margin).translate((cx+H['usb_slot_x_offset_mm'],0,z0+t/2))
    shell=shell.cut(slot)
    mx,mz=H['mount_xz_mm']
    for yy in (H['front_arm_y_mm'],H['rear_arm_y_mm']):
        bottom_slot=cq.Workplane('XY').box(mx+H['arm_bottom_slot_end_mm']-x0,H['arm_slot_width_mm'],t+H['arm_slot_depth_extra_mm']).translate(((x0+mx+H['arm_bottom_slot_center_end_mm'])/2,yy,z0+t/2))
        rear_slot=cq.Workplane('XY').box(t+H['arm_slot_depth_extra_mm'],H['arm_slot_width_mm'],mz+H['arm_rear_slot_end_mm']-z0).translate((x0+t/2,yy,(z0+mz+H['arm_rear_slot_center_end_mm'])/2))
        shell=shell.cut(bottom_slot).cut(rear_slot)
    # Real bosses meet the outer faces of the two aluminium output arms.
    for tag,face,wall in [('front',H['front_arm_y_mm']+H['arm_t_mm']/2,y1-t),('rear',H['rear_arm_y_mm']-H['arm_t_mm']/2,y0+t)]:
        lo,hi=sorted((face,wall))
        boss=cyl(H['mount_boss_r_mm'],hi-lo,'y',(mx,lo,mz))
        shell=shell.union(boss)
        shell=shell.cut(cyl(H['mount_hole_d_mm']/2,y1-y0+2*margin,'y',(mx,y0-margin,mz)))
    a=E['camera']['hole_pitch_mm']/2
    for u,v in ((a,a),(a,-a),(-a,a),(-a,-a)):
        shell=shell.cut(cyl(H['camera_clear_d_mm']/2,t+2*margin,'x',(x0-margin,cy+u,cz+v)))
    seam=H['seam_x_mm'];gap=H['seam_gap_mm']
    rear=shell.intersect(cq.Workplane('XY').box(seam-x0-gap/2,y1-y0+4*margin,z1-z0+4*margin,centered=(False,True,True)).translate((x0,0,(z0+z1)/2)))
    front=shell.intersect(cq.Workplane('XY').box(x1-seam-gap/2,y1-y0+4*margin,z1-z0+4*margin,centered=(False,True,True)).translate((seam+gap/2,0,(z0+z1)/2)))
    # Two axial pillars close the front shell; two bottom tongues align it.
    # Both halves print with their broad outer face on the bed. Side-loaded
    # captive pillars bear against an axial lip rather than pulling out.
    for k,yy in enumerate(H['closure_y_mm']):
        zz=H['closure_z_mm']
        rear=rear.union(cyl(H['closure_tube_r_mm'],seam-x0,'x',(x0,yy,zz)))
        front=front.union(cyl(H['closure_tube_r_mm'],x1-seam,'x',(seam,yy,zz)))
        rear=rear.cut(cyl(H['closure_clear_d_mm']/2,seam-x0,'x',(x0,yy,zz)))
        front=front.cut(cyl(H['closure_clear_d_mm']/2,x1-seam,'x',(seam,yy,zz)))
        pocket=cq.Workplane('XY').polygon(6,H['closure_pocket_af_mm']/math.cos(math.pi/6)).extrude(H['closure_pocket_length_mm']).rotate((0,0,0),(0,1,0),90).translate((seam+H['closure_pocket_x_offset_mm'],yy,zz))
        # Load from the cavity before fitting the camera, leaving a 2.4mm
        # axial retaining lip at the split and 0.1mm clearance at each end.
        access=cq.Workplane('XY').box(*H['closure_access_xyz_mm']).translate((seam+H['closure_access_x_offset_mm'],yy-math.copysign(H['closure_access_y_offset_mm'],yy),zz))
        rear=rear.cut(pocket).cut(access)
        pillar=cq.Workplane('XY').polygon(6,H['closure_pillar_af_mm']/math.cos(math.pi/6)).extrude(H['closure_pillar_length_mm']).cut(cq.Workplane('XY').circle(H['m2_thread_bore_d_mm']/2).extrude(H['closure_pillar_length_mm']))
        pillar=pillar.rotate((0,0,0),(0,1,0),90).translate((seam+H['closure_pillar_x_offset_mm'],yy,zz))
        add('head-closure-pillar-'+str(k),'standoff',pillar,spec=f"M2 hex female-female {H['closure_pillar_length_mm']:g}mm, AF{H['closure_pillar_af_mm']:g}")
    for yy in H['tongue_y_mm']:
        tab=cq.Workplane('XY').box(*H['tongue_xyz_mm']).translate((seam+H['tongue_x_offset_mm'],yy,z0+H['tongue_z_offset_mm']))
        pocket=cq.Workplane('XY').box(*H['tongue_pocket_xyz_mm']).translate((seam+H['tongue_pocket_x_offset_mm'],yy,z0+H['tongue_z_offset_mm']))
        rear=rear.union(tab);front=front.cut(pocket)
    add('cover-head-f','petg',front,print_face='+X',wall_mm=t,closure_status=f"two M2x{H['closure_screw_length_mm']:g} screws into captive {H['closure_pillar_length_mm']:g}mm hex pillars; bottom locating tongues")
    add('cover-head-b','petg',rear,print_face='-X',wall_mm=t,closure_status=f"side-load hex pillars before camera installation; {H['closure_retaining_lip_mm']:g}mm axial retaining lips")
    a=SERVO['horn_hole_square_mm']/2
    # Clip the rear corners inside the case connector's swept clearance.
    # The former (-10, +/-9) corners struck its lip near +/-30 degrees.
    outline=[*H['arm_start_xz_mm'],*((mx+u,mz+v) for u,v in H['arm_mount_offsets_xz_mm']),*H['arm_end_xz_mm']]
    for tag,y in [('front',H['front_arm_y_mm']),('rear',H['rear_arm_y_mm'])]:
        arm=cq.Workplane('XY').polyline(outline).close().extrude(H['arm_t_mm'])
        for u,v in ((a,a),(a,-a),(-a,a),(-a,-a),(mx,mz)):
            arm=arm.cut(cq.Workplane('XY').center(u,v).circle(H['mount_hole_d_mm']/2).extrude(H['arm_t_mm']))
        arm=arm.cut(cq.Workplane('XY').circle(H['arm_center_d_mm'][tag]/2).extrude(H['arm_t_mm']))
        flat=arm
        arm=arm.rotate((0,0,0),(1,0,0),90).translate((0,y+H['arm_t_mm']/2,0))
        add('head-output-arm-'+tag,'al',arm,flat=flat,manufacturing=f"laser {H['al_material']} {H['arm_t_mm']:g}mm; deburr")
    def m2(length,at,positive):
        sh=cq.Workplane('XY').circle(H['m2_shank_d_mm']/2).extrude(length)
        cap=cq.Workplane('XY').circle(H['m2_head_d_mm']/2).extrude(-H['m2_head_h_mm'])
        socket=cq.Workplane('XY').polygon(6,H['m2_socket_af_mm']/math.cos(math.pi/6)).extrude(-H['m2_socket_depth_mm']).translate((0,0,-H['m2_socket_offset_mm']))
        wp=sh.union(cap.cut(socket)).rotate((0,0,0),(0,1,0),90 if positive else -90)
        return wp.translate(at)
    for k,yy in enumerate(H['closure_y_mm']):
        add('head-closure-screw-'+str(k),'fastener',m2(H['closure_screw_length_mm'],(x1,yy,H['closure_z_mm']),False),spec=f"M2x{H['closure_screw_length_mm']:g} ISO4762")
    for tag,start,positive,ny in [('front',y1,False,H['front_arm_y_mm']-H['arm_t_mm']/2-H['mount_nut_h_mm']),('rear',y0,True,H['rear_arm_y_mm']+H['arm_t_mm']/2)]:
        fast=screw(H['mount_screw_length_mm'],'x' if positive else '-x',(start,0,0)).rotate((0,0,0),(0,0,1),90).translate((mx,0,mz))
        nut=cq.Workplane('XY').polygon(6,H['mount_nut_af_mm']/math.cos(math.pi/6)).extrude(H['mount_nut_h_mm']).cut(cq.Workplane('XY').circle(H['mount_nut_bore_d_mm']/2).extrude(H['mount_nut_h_mm']))
        nut=nut.rotate((0,0,0),(1,0,0),-90).translate((mx,ny,mz))
        add('head-mount-screw-'+tag,'fastener',fast,spec=f"M3x{H['mount_screw_length_mm']:g} ISO4762")
        add('head-mount-nut-'+tag,'fastener',nut,spec='M3 ISO4032')
    a=SERVO['horn_hole_square_mm']/2
    for k,(u,v) in enumerate(((a,a),(a,-a),(-a,a),(-a,-a))):
        fast=screw(H['passive_screw_length_mm'],'x',(H['rear_arm_y_mm']-H['arm_t_mm']/2,0,0)).rotate((0,0,0),(0,0,1),90).translate((u,0,v))
        add('head-passive-screw-'+str(k),'fastener',fast,spec=f"M3x{H['passive_screw_length_mm']:g} ISO4762")
    # Four 5mm female M2 pillars: board/back cover are mounted as one module.
    a=E['camera']['hole_pitch_mm']/2
    for k,(u,v) in enumerate(((a,a),(a,-a),(-a,a),(-a,-a))):
        post=cyl(H['camera_pillar_od_mm']/2,H['camera_pillar_length_mm'],'x',(x0+t,cy+u,cz+v)).cut(cyl(H['m2_thread_bore_d_mm']/2,H['camera_pillar_length_mm'],'x',(x0+t,cy+u,cz+v)))
        add('camera-pillar-'+str(k),'standoff',post,spec=f"M2 female-female {H['camera_pillar_length_mm']:g} mm")
        add('camera-screw-'+str(k),'fastener',m2(H['camera_screw_length_mm'],(cx,cy+u,cz+v),False),spec=f"M2x{H['camera_screw_length_mm']:g} ISO4762")
        add('camera-pillar-screw-'+str(k),'fastener',m2(H['camera_rear_screw_length_mm'],(x0,cy+u,cz+v),True),spec=f"M2x{H['camera_rear_screw_length_mm']:g} ISO4762")
    return parts
