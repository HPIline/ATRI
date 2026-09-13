"""Ventilated captive converter tray; no assumed PCB mounting-hole pattern."""
import math
import cadquery as cq
from .profile import ELECTRONICS as E,TORSO as T
from .pelvis_cad import cyl


def add_regulator_mount(items):
    result=[dict(i) for i in items]
    bridge=next(i for i in result if i['name']=='bus-bridge')
    r=E['regulator'];x,y,z=r['position_mm'];w,d,h=r['envelope_mm']
    wall=T['regulator_cradle_wall_mm'];gap=T['regulator_cradle_clear_mm']
    floor=z-h/2;lid_bottom=z+h/2+T['regulator_lid_gap_mm']
    total_h=lid_bottom-floor+wall
    outer=cq.Workplane('XY').box(w+2*(gap+wall),d+2*(gap+wall),total_h,centered=(True,True,False)).translate((x,y,floor-wall))
    cavity=cq.Workplane('XY').box(w+2*gap,d+2*gap,total_h,centered=(True,True,False)).translate((x,y,floor))
    cradle=outer.cut(cavity)
    # End openings accept soldered input/output leads without guessed connectors.
    for sign in (-1,1):
        slot=cq.Workplane('XY').box(wall+2*gap,T['regulator_wire_slot_y_mm'],T['regulator_wire_slot_h_mm'],centered=(True,True,False)).translate((x+sign*(w/2+gap+wall/2),y,floor))
        cradle=cradle.cut(slot)
    lid=cq.Workplane('XY').box(w+2*(gap+wall),d+2*(gap+wall),wall,centered=(True,True,False)).translate((x,y,lid_bottom))
    for dx in T['regulator_vent_x_offsets_mm']:
        vent=cq.Workplane('XY').box(T['regulator_vent_width_mm'],T['regulator_vent_length_mm'],wall,centered=(True,True,False)).translate((x+dx,y,lid_bottom))
        lid=lid.cut(vent)
    bridge['wp']=bridge['wp'].union(cradle)
    for n,sign in enumerate((-1,1)):
        x=r['position_mm'][0]+T['regulator_lid_boss_x_offsets_mm'][n]
        yy=y+sign*T['regulator_lid_boss_y_offset_mm'];rad=T['regulator_lid_boss_r_mm']
        boss=cyl(rad,lid_bottom-T['bus_bridge_z_mm'],'z',(x,yy,T['bus_bridge_z_mm']))
        bridge['wp']=bridge['wp'].union(boss)
        lid=lid.union(cyl(rad,wall,'z',(x,yy,lid_bottom)))
        hole=cyl(1.1,lid_bottom+wall-T['bus_bridge_z_mm'],'z',(x,yy,T['bus_bridge_z_mm']))
        bridge['wp']=bridge['wp'].cut(hole);lid=lid.cut(hole)
        nz=T['regulator_nut_z_mm'];nh=T['regulator_nut_h_mm']
        pocket=cq.Workplane('XY').polygon(6,(T['regulator_nut_af_mm']+T['regulator_nut_clear_mm'])/math.cos(math.pi/6)).extrude(nz+nh-T['bus_bridge_z_mm']).translate((x,yy,T['bus_bridge_z_mm']))
        bridge['wp']=bridge['wp'].cut(pocket)
        nut=cq.Workplane('XY').polygon(6,T['regulator_nut_af_mm']/math.cos(math.pi/6)).extrude(nh).cut(cyl(.8,nh,'z',(0,0,0))).translate((x,yy,nz))
        seat=lid_bottom+wall;length=T['regulator_lid_screw_mm']
        bolt=cyl(1.,length,'z',(x,yy,seat-length)).union(cyl(1.9,2.,'z',(x,yy,seat)))
        socket=cq.Workplane('XY').polygon(6,1.5/math.cos(math.pi/6)).extrude(-1.2).translate((x,yy,seat+2.))
        result.extend([dict(name=f'regulator-lid-nut-{n}',link='torso',kind='fastener',wp=nut,spec='M2 ISO4032; load through underside before fitting bridge'),dict(name=f'regulator-lid-bolt-{n}',link='torso',kind='fastener',wp=bolt.cut(socket),spec='M2x8 ISO4762')])
    result.append(dict(name='regulator-lid',link='torso',kind='petg',wp=lid,print_face='+Z',wall_mm=wall,assembly='place bare converter in edge-constrained tray, solder leads through end windows, close captive lid',qualification='envelope fit and continuous-load thermal test required; nominal 0.2 mm side clearance'))
    bridge['assembly']+='; converter pocket is integral; fit its captive nuts from underside first'
    return result
