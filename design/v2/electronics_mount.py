"""Pi 4 mounting on printed collars with accessible tube-wall nuts."""
import math
import cadquery as cq
from .profile import ELECTRONICS as E,TORSO as T,K,PELVIS
from .pelvis_cad import cyl,screw


def sbc_holes():
    x,y,z=E['sbc']['position_mm'];w,h,_=E['sbc']['pcb_mm']
    return [(y+hx-w/2,z-(hy-h/2)) for hx,hy in E['sbc']['hole_xy_mm']]


def m25_screw(length,seat,direction):
    # ISO 4762 nominal head envelope; external threads shown at major diameter.
    part=cyl(2.25,2.5,'x',(-2.5,0,0)).union(cyl(1.25,length,'x',(0,0,0)))
    socket=cq.Workplane('YZ').polygon(6,2/math.cos(math.pi/6)).extrude(1.5).translate((-2.5,0,0))
    part=part.cut(socket)
    if direction<0:part=part.rotate((0,0,0),(0,0,1),180)
    return part.translate(seat)


def build_sbc_mount():
    items=[]
    def add(name,kind,wp,**meta):items.append(dict(name=name,link='torso',kind=kind,wp=wp,**meta))
    holes=sbc_holes();ys=sorted({y for y,z in holes});zs=sorted({z for y,z in holes})
    sh=K['pelvis_to_shoulder_z']-PELVIS['trunk_roll_z_mm']-PELVIS['trunk_pitch_offset_mm']
    beam_z=[sh+z for z in T['beam_z_offsets_mm']]
    wall=T['sbc_carrier_wall_mm'];clear=T['sbc_carrier_clearance_mm']
    bx=T['beam_x_mm'];w=T['beam_width_mm'];h=T['beam_height_mm']
    rear=T['sbc_carrier_rear_x_mm'];width=T['sbc_rail_width_mm']
    zlo=zs[0]-T['sbc_rail_end_margin_mm'];zhi=zs[-1]+T['sbc_rail_end_margin_mm']
    for n,y in enumerate(ys):
        rail=cq.Workplane('XY').box(wall,width,zhi-zlo,centered=(False,True,False)).translate((rear,y,zlo))
        for z in beam_z:
            ring=cq.Workplane('XZ').rect(w+2*(clear+wall),h+2*(clear+wall)).rect(w+2*clear,h+2*clear).extrude(width).translate((bx,y+width/2,z))
            rail=rail.union(ring)
            rail=rail.cut(cyl(T['sbc_beam_clear_d_mm']/2,w,'x',(rear,y,z)))
            add(f'sbc-beam-bolt-{n}-{z:g}','fastener',screw(T['sbc_beam_screw_mm'],'x',(rear,y,z)),spec='M3x10 ISO4762; nut inserted from open tube end before frame assembly')
            nut=cq.Workplane('YZ').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'x',(0,0,0)))
            add(f'sbc-beam-nut-{n}-{z:g}','fastener',nut.translate((bx-w/2+T['beam_wall_mm'],y,z)),spec='M3 ISO4032 inside rectangular tube')
        for k,z in enumerate(zs):
            rail=rail.cut(cyl(T['sbc_mount_clear_d_mm']/2,wall,'x',(rear,y,z)))
            post=cyl(T['sbc_post_od_mm']/2,T['sbc_post_mm'],'x',(rear-T['sbc_post_mm'],y,z)).cut(cyl(1.05,T['sbc_post_mm'],'x',(rear-T['sbc_post_mm'],y,z)))
            add(f'sbc-post-{n}-{k}','standoff',post,spec='M2.5 female/female round OD5 x 8 mm; brass')
            seat=E['sbc']['position_mm'][0]-E['sbc']['pcb_mm'][2]/2
            add(f'sbc-board-bolt-{n}-{k}','fastener',m25_screw(T['sbc_board_screw_mm'],(seat,y,z),1),spec='M2.5x5 ISO4762')
            add(f'sbc-carrier-bolt-{n}-{k}','fastener',m25_screw(T['sbc_carrier_screw_mm'],(rear+wall,y,z),-1),spec='M2.5x6 ISO4762')
        add(f'sbc-carrier-{n}','petg',rail,print_face='-Y',material='opaque matte white PETG',assembly='slide over both bare tube segments; install four internal nuts before end plates',qualification='printed hole fit and collar creep require sample')
    return items


def build_bus_mount():
    items=[]
    def add(name,kind,wp,**meta):items.append(dict(name=name,link='torso',kind=kind,wp=wp,**meta))
    x0,x1=T['bus_bridge_x_mm'];y0,y1=T['bus_bridge_y_mm'];z=T['bus_bridge_z_mm'];t=T['bus_bridge_t_mm']
    bottom=T['battery_tray_bounds_mm'][5]
    bridge=cq.Workplane('XY').box(x1-x0,y1-y0,t,centered=(False,False,False)).translate((x0,y0,z))
    window=cq.Workplane('XY').box(*T['bus_bridge_window_mm'],t,centered=(True,True,False)).translate(((x0+x1)/2,0,z))
    bridge=bridge.cut(window)
    for n,x in enumerate(T['bus_bridge_leg_x_mm']):
        for sign in (-1,1):
            yy=y1-t/2 if sign>0 else y0+t/2
            web=cq.Workplane('XY').box(T['bus_bridge_leg_width_mm'],t,z-bottom,centered=(True,True,False)).translate((x,yy,bottom))
            fy=y1-T['bus_bridge_foot_depth_mm']/2 if sign>0 else y0+T['bus_bridge_foot_depth_mm']/2
            foot=cq.Workplane('XY').box(T['bus_bridge_leg_width_mm'],T['bus_bridge_foot_depth_mm'],t,centered=(True,True,False)).translate((x,fy,bottom))
            bridge=bridge.union(web).union(foot)
            hy=sign*T['bus_bridge_foot_hole_y_mm']
            bridge=bridge.cut(cyl(1.6,t,'z',(x,hy,bottom)))
            bolt=screw(T['bus_bridge_mount_screw_mm'],'-x',(bottom+t,0,0)).rotate((0,0,0),(0,1,0),-90).translate((x,hy,0))
            add(f'bus-bridge-bolt-{n}-{sign}','fastener',bolt,spec='M3x8 ISO4762')
            nut=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cyl(1.25,2.4,'z',(0,0,0)))
            add(f'bus-bridge-nut-{n}-{sign}','fastener',nut.translate((x,hy,T['battery_tray_bounds_mm'][2]-2.4)),spec='M3 ISO4032; fit below tray before battery')
    b=E['bus_adapter'];cx,cy,cz=b['position_mm'];px,py=b['hole_pitch_mm']
    def busbolt(length,positive):
        body=cyl(T['bus_mount_d_mm']/2,length,'z',(0,0,0))
        cap=cyl(T['bus_mount_head_d_mm']/2,T['bus_mount_head_h_mm'],'z',(0,0,-T['bus_mount_head_h_mm']))
        socket=cq.Workplane('XY').polygon(6,T['bus_mount_socket_mm']/math.cos(math.pi/6)).extrude(1.2).translate((0,0,-T['bus_mount_head_h_mm']))
        bolt=body.union(cap.cut(socket))
        return bolt if positive else bolt.rotate((0,0,0),(1,0,0),180)
    for n,(x,y) in enumerate((cx+dx,cy+dy) for dx in (-py/2,py/2) for dy in (-px/2,px/2)):
        bridge=bridge.cut(cyl(T['bus_mount_clear_mm']/2,t,'z',(x,y,z)))
        post=cyl(T['bus_post_od_mm']/2,T['bus_post_mm'],'z',(x,y,z+t)).cut(cyl(T['bus_post_bore_mm']/2,T['bus_post_mm'],'z',(x,y,z+t)))
        add(f'bus-post-{n}','standoff',post,spec='M2 female/female OD4 x 8 mm brass')
        lower=busbolt(6,True).translate((x,y,z))
        upper=busbolt(5,False).translate((x,y,cz))
        add(f'bus-post-bottom-bolt-{n}','fastener',lower,spec='M2x6 ISO4762')
        add(f'bus-board-bolt-{n}','fastener',upper,spec='M2x5 ISO4762 in vendor 2.5 mm clearance holes')
    add('bus-bridge','petg',bridge,print_face='+Z',wall_mm=t,manufacturing='opaque matte white PETG; bridge roof on print bed',assembly='bolt posts to bridge, then bridge to tray, fit board last; battery removable after bridge removal')
    return items
