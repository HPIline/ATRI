"""Purchased electronic envelopes tied to source records, in link coordinates."""
import cadquery as cq
from functools import lru_cache
from pathlib import Path
import math
import json
from .profile import ELECTRONICS as E


@lru_cache(maxsize=1)
def bus_adapter_shape():
    source=Path(__file__).parents[1]/'cad/vendor/bus-servo-adapter-a/bus-servo-adapter-a.step'
    raw=cq.importers.importStep(str(source)).val().Solids()
    solids=[]
    for index,part in enumerate(raw):
        fixed=part
        if not part.isValid():
            before=part.Volume();fixed=part.fix()
            if not fixed.isValid() or abs(fixed.Volume()-before)>1e-6:
                raise ValueError(f'Bus adapter solid {index} could not be healed without volume change')
        solids.append(fixed)
    if len(solids)!=117:raise ValueError('Bus adapter vendor revision changed; recheck mechanics')
    return cq.Workplane('XY').newObject([cq.Compound.makeCompound(solids)])


def build_electronics():
    items=[]
    def add(name,link,kind,wp,**meta):items.append(dict(name=name,link=link,kind=kind,wp=wp,**meta))
    c=E['camera'];x,y,z=c['position_mm'];w,h,t=c['pcb_mm']
    pcb=cq.Workplane('YZ').rect(w,h).extrude(-t)
    a=c['hole_pitch_mm']/2
    for u,v in ((a,a),(a,-a),(-a,a),(-a,-a)):
        pcb=pcb.cut(cq.Workplane('YZ').center(u,v).circle(c['hole_d_mm']/2).extrude(-t))
    add('camera','head','pcb',pcb.translate((x,y,z)),sku=c['sku'],source=c['source'])
    # Only dimensions documented on the supplier outline are used as interfaces.
    barrel=cq.Workplane('YZ').circle(c['lens_d_mm']/2).extrude(c['lens_front_mm'])
    add('lens','head','optical',barrel.translate((x,y,z)),detail='lens barrel envelope; internal glass not manufactured')
    back=cq.Workplane('XY').box(c['total_depth_mm']-c['lens_front_mm']-t,w,h)
    back=back.translate((x-t-(c['total_depth_mm']-c['lens_front_mm']-t)/2,y,z))
    for u,v in ((a,a),(a,-a),(-a,a),(-a,-a)):
        back=back.cut(cq.Workplane('YZ').center(y+u,z+v).circle(c['hole_d_mm']/2).extrude(-c['total_depth_mm']).translate((x,0,0)))
    add('camera-rear-envelope','head','electronics_case',back,detail='supplier overall envelope, not an internal component layout')
    b=E['battery']
    add('battery','torso','elec',cq.Workplane('XY').box(*b['body_mm']).translate(b['position_mm']),sku=b['sku'],purchased_mass_g=b['mass_g'])
    b=E['sbc'];w,h,t=b['pcb_mm']
    # Keep the official drawing's lower-left PCB datum until holes are cut.
    board=cq.Workplane('XY').box(w,h,t,centered=(False,False,True))
    for hx,hy in b['hole_xy_mm']:
        board=board.cut(cq.Workplane('XY').center(hx,hy).circle(b['hole_d_mm']/2).extrude(t,both=True))
    board=board.translate((-w/2,-h/2,0)).rotate((0,0,0),(0,1,0),-90).rotate((0,0,0),(1,0,0),-90)
    add('sbc','torso','pcb',board.translate(b['position_mm']),sku=b['sku'],purchased_mass_g=b['mass_g'],source=b['mounting_status'],purchased_assembly='sbc')
    reference=Path(__file__).parents[1]/'cad/vendor/pi4b/component-envelopes.json'
    components=json.loads(reference.read_text())['components']
    for index,component in enumerate(components):
        bounds=component['bounds']
        if bounds==[[-42.5,42.5],[-.8,.8],[-28.,28.]]:continue
        lengths=[hi-lo for lo,hi in bounds];center=[(lo+hi)/2 for lo,hi in bounds]
        envelope=cq.Workplane('XY').box(*lengths).translate(center).rotate((0,0,0),(0,0,1),90).translate(b['position_mm'])
        add(f'sbc-component-{index:03d}','torso','electronics_case',envelope,purchased_assembly='sbc',source=str(reference),geometry_status='conservative component box from supplied grabette visual STL; not a manufacturing solid or exact connector mating surface')
    r=E['regulator']
    add('regulator','torso','electronics_case',cq.Workplane('XY').box(*r['envelope_mm']).translate(r['position_mm']),sku=r['sku'],source=r['source'],geometry_status='published overall envelope; no undocumented mounting holes invented',qualification=r['qualification'])
    b=E['bus_adapter'];w,h,t=b['pcb_mm']
    theta=math.radians(b['clock_deg']);x,y,z=b['position_mm']
    offset=(x-w/2*math.cos(theta)+h/2*math.sin(theta),y-w/2*math.sin(theta)-h/2*math.cos(theta),z)
    # A rigid TopLoc placement preserves the vendor tolerances. Rebuilding the
    # underlying surfaces with Shape.rotate made this vendor's solid 25 invalid.
    placed=bus_adapter_shape().val().located(cq.Location(cq.Vector(*offset),cq.Vector(0,0,1),b['clock_deg']))
    if not placed.isValid():raise ValueError('Placed bus adapter is invalid')
    for index,solid in enumerate(placed.Solids()):
        adapter=cq.Workplane('XY').newObject([solid])
        kind='pcb' if index==0 else ('connector_metal' if index==16 else ('connector_white' if index in (17,18) else 'electronics_case'))
        add(f'bus-adapter-{index:03d}','torso',kind,adapter,sku=b['sku'],source=b['source'],purchased_assembly='bus-adapter',vendor_solid_index=index,repair='vendor solid 25 healed, volume conserved; no components omitted')
    return items
