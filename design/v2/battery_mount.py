"""Flat-cut battery supports, stock angles and a removable strap-held tray."""
import math
import cadquery as cq
from .profile import TORSO as T,ELECTRONICS as E,K,PELVIS
from .pelvis_cad import cyl,screw


def build_battery_mount():
    items=[]
    def add(name,kind,wp,**meta):items.append(dict(name=name,link='torso',kind=kind,wp=wp,**meta))
    t=T['plate_t_mm'];y=T['battery_side_y_mm'];bx=T['beam_x_mm']
    sh=K['pelvis_to_shoulder_z']-PELVIS['trunk_roll_z_mm']-PELVIS['trunk_pitch_offset_mm']
    bz=[sh+v for v in T['beam_z_offsets_mm']]
    xmin,xmax=T['battery_bracket_x_mm'];bottom=T['battery_bracket_bottom_mm'];web=T['battery_bracket_web_mm']
    flat=cq.Workplane('XY').polyline([(xmin,bottom),(xmax,bottom),(xmax,bottom+web),(bx+web/2,bottom+web),(bx+web/2,bz[-1]+web/2),(xmin,bz[-1]+web/2)]).close().extrude(t)
    for x,z in [(bx,z) for z in bz]+[(x,T['battery_angle_hole_z_mm']) for x in T['battery_angle_holes_x_mm']]:flat=flat.cut(cyl(1.6,t,'z',(x,z,0)))
    x0,y0,z0,x1,y1,z1=T['battery_tray_bounds_mm'];tt=z1-z0
    trayflat=cq.Workplane('XY').box(x1-x0,y1-y0,tt,centered=(False,False,False)).translate((x0,y0,0))
    for x in T['bus_bridge_leg_x_mm']:
        for yy in (-T['bus_bridge_foot_hole_y_mm'],T['bus_bridge_foot_hole_y_mm']):trayflat=trayflat.cut(cyl(1.6,tt,'z',(x,yy,0)))
    leg=T['battery_angle_leg_mm'];at=T['battery_angle_t_mm'];al=T['battery_angle_length_mm'];ac=(x0+x1)/2
    inner=y-t/2
    # Left angle: vertical face meets the support plate; horizontal face supports tray.
    angle=cq.Workplane('XY').box(al,at,leg,centered=(True,False,False)).translate((ac,inner-at,z0-leg))
    angle=angle.union(cq.Workplane('XY').box(al,leg,at,centered=(True,False,False)).translate((ac,inner-leg,z0-at)))
    corner_y=inner-at;corner_z=z0-at
    edge=[e for e in angle.val().Edges() if e.geomType()=='LINE' and abs(e.Length()-al)<1e-5 and abs(e.Center().y-corner_y)<1e-5 and abs(e.Center().z-corner_z)<1e-5]
    if len(edge)!=1:raise ValueError('Battery stock-angle inner edge missing')
    angle=angle.newObject(edge).fillet(T['battery_angle_inner_r_mm'])
    horizontal_y=inner-leg/2
    for x in T['battery_angle_holes_x_mm']:
        angle=angle.cut(cyl(1.6,at,'y',(x,inner-at,T['battery_angle_hole_z_mm'])))
        angle=angle.cut(cyl(1.6,at,'z',(x,horizontal_y,z0-at)))
        for yy in (-horizontal_y,horizontal_y):trayflat=trayflat.cut(cyl(1.6,tt,'z',(x,yy,0)))
    tray=trayflat.translate((0,0,z0))
    nut=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'z',(0,0,0)))
    for sign,side in ((1,'left'),(-1,'right')):
        plate=flat.rotate((0,0,0),(1,0,0),90).translate((0,y+t/2,0))
        sideangle=angle
        if sign<0:
            plate=plate.mirror('XZ');sideangle=sideangle.mirror('XZ')
        add('battery-support-'+side,'al',plate,flat=flat,manufacturing='laser 6061-T6 1.5 mm; captured between tube segments by shared M3 rods')
        add('battery-angle-'+side,'al',sideangle,stock_cut_length_mm=al,manufacturing=f'stock angle {leg:g}x{leg:g}x{at:g}, cut {al:g} mm; four 3.2 mm drilled holes; inner R1.5')
        for k,x in enumerate(T['battery_angle_holes_x_mm']):
            yy=sign*horizontal_y
            head=cq.Workplane('XY').newObject([cq.Solid.makeCone(1.3,3.,1.7)]).translate((x,yy,z1-1.7))
            tray=tray.cut(head)
            bolt=cyl(1.5,6.5,'z',(x,yy,z1-8)).union(head)
            socket=cq.Workplane('XY').polygon(6,2/math.cos(math.pi/6)).extrude(-1.2).translate((x,yy,z1))
            add(f'battery-tray-bolt-{side}-{k}','fastener',bolt.cut(socket),spec='M3x8 ISO10642; flush countersink; verify purchased head before machining')
            add(f'battery-tray-nut-{side}-{k}','fastener',nut.translate((x,yy,z0-at-2.4)),spec='M3 ISO4032')
            bolt=screw(8,'-x',(y+t/2,0,0)).rotate((0,0,0),(0,0,1),90).translate((x,0,T['battery_angle_hole_z_mm']))
            snut=nut.rotate((0,0,0),(1,0,0),-90).translate((x,inner-at-2.4,T['battery_angle_hole_z_mm']))
            if sign<0:bolt=bolt.mirror('XZ');snut=snut.mirror('XZ')
            add(f'battery-angle-bolt-{side}-{k}','fastener',bolt,spec='M3x8 ISO4762')
            add(f'battery-angle-nut-{side}-{k}','fastener',snut,spec='M3 ISO4032')
    add('battery-tray','al',tray,flat=trayflat,manufacturing='laser 6061-T6 2 mm; four 90 degree countersinks OD6; deburr battery-facing edges')
    b=E['battery'];cx,cy,cz=b['position_mm'];bw,bl,bh=b['body_mm']
    thick=T['battery_strap_thickness_mm'];sw=T['battery_strap_width_mm'];top=cz+bh/2
    path=[(x0,z0),(x1,z0),(x1,z1),(cx+bw/2,top),(cx-bw/2,top),(x0,z1)]
    outer=[(x0-thick,z0-thick),(x1+thick,z0-thick),(x1+thick,z1),(cx+bw/2+thick,top+thick),(cx-bw/2-thick,top+thick),(x0-thick,z1)]
    perimeter=sum(math.dist(a,bb) for a,bb in zip(outer,outer[1:]+outer[:1]))
    if perimeter+T['battery_strap_overlap_mm']>T['battery_strap_length_mm']:raise ValueError('Battery strap is too short')
    ribbon=cq.Workplane('XZ').polyline(outer).close().extrude(sw).cut(cq.Workplane('XZ').polyline(path).close().extrude(sw))
    for n,yy in enumerate(T['battery_strap_y_mm']):
        loop=ribbon.translate((0,yy+sw/2,0))
        overlap=cq.Workplane('XY').box(T['battery_strap_overlap_mm'],sw,thick,centered=(True,True,False)).translate((cx,yy,top+thick))
        add(f'battery-strap-{n}','strap',loop.union(overlap),spec=f'hook-loop battery strap {sw:g}x{T["battery_strap_length_mm"]:g} mm, overlap >=20 mm',qualification='nominal closed routing; source thickness and corner fit require sample')
    return items
