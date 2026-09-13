"""Second identical pack on an integral extension of the existing bolted tray."""
import cadquery as cq
from .profile import ELECTRONICS as E, BATTERY_EXPANSION as D


def add_second_battery(items):
    result=[dict(i) for i in items]; ix={i['name']:i for i in result}
    t=D['thickness_mm'];x0,x1=D['tray_x_mm'];y0,y1=D['tray_y_mm'];z=D['tray_z_mm']
    extension=cq.Workplane('XY').box(x1-x0,y1-y0,t,centered=(False,False,False)).translate((x0,y0,z))
    for yy in D['bridge_y_mm']:
        arm=cq.Workplane('XY').box(x0-D['bridge_start_x_mm'],D['bridge_width_mm'],t,centered=(False,True,False)).translate((D['bridge_start_x_mm'],yy,z))
        extension=extension.union(arm)
        clear=D['shell_clearance_mm']
        slot=cq.Workplane('XY').box(20,D['bridge_width_mm']+2*clear,t+2*clear).translate((60,yy,z+t/2))
        ix['shell-torso-front']['wp']=ix['shell-torso-front']['wp'].cut(slot)
    tray=ix['battery-tray'];tray['wp']=tray['wp'].union(extension)
    tray['flat']=tray['flat'].union(extension.translate((0,0,-z)))
    tray['manufacturing']='2 mm 6061-T6 single laser-cut extended tray; existing four bolted angle supports; countersink as original; extension stiffness requires load test'
    def add(name,kind,wp,**kw):result.append(dict(name=name,link='torso',kind=kind,wp=wp,**kw))
    b=E['battery'];cx,cy,cz=D['center_mm'];bw,bl,bh=b['body_mm']
    add('battery-secondary','elec',cq.Workplane('XY').box(bw,bl,bh).translate((cx,cy,cz)),sku=b['sku'],purchased_mass_g=b['mass_g'],qualification='second identical 3S pack; separate protected electrical path not yet built')
    # Closed strap paths wrap beneath the tray and over the pack, not floating strips.
    st=D['strap_t_mm'];sw=D['strap_width_mm'];top=cz+bh/2
    inner=[(x0,z),(x1,z),(x1,z+t),(cx+bw/2,top),(cx-bw/2,top),(x0,z+t)]
    outer=[(x0-st,z-st),(x1+st,z-st),(x1+st,z+t),(cx+bw/2+st,top+st),(cx-bw/2-st,top+st),(x0-st,z+t)]
    cross=cq.Workplane('XY').polyline(outer).close().extrude(sw).cut(cq.Workplane('XY').polyline(inner).close().extrude(sw))
    for n,yy in enumerate(D['strap_y_mm']):
        loop=cross.rotate((0,0,0),(1,0,0),90).translate((0,yy+sw/2,0))
        add(f'battery-secondary-strap-{n}','strap',loop,spec='10 mm hook-loop closed strap around pack and tray; qualify tension and friction')
    return result
