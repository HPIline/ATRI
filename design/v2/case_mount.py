"""External case clamp; never fix a link to the passive output disc.

Clamp preload and plastic-case creep require physical qualification.
"""
import math
import cadquery as cq
from .profile import CASE_MOUNT as C
from .pelvis_cad import screw


def jaw_flat(thickness=None):
    t=C['plate_t_mm'] if thickness is None else thickness
    x0,x1=C['x_span_mm'];h=C['height_mm']
    p=cq.Workplane('XY').rect(x1-x0,h).extrude(t).translate(((x0+x1)/2,0,0))
    for z in C['bolt_z_mm']:
        p=p.cut(cq.Workplane('XY').center(C['bolt_x_mm'],z).circle(C['hole_mm']/2).extrude(t))
    return p


def canonical_jaw(front=True):
    # +90 X maps extrusion +Z to -Y: rear jaw is [-19.2,-17.7],
    # front jaw [17,18.5]. Rear contact is the case lip at X=-29..-25.
    t=C['plate_t_mm']
    outer=C['front_face_mm']+t if front else C['rear_face_mm']
    return jaw_flat().rotate((0,0,0),(1,0,0),90).translate((0,outer,0))


def build_case_clamp(tag,link,include_front=True,include_rear=True):
    parts=[]
    def add(name,kind,wp,**meta):parts.append(dict(name=f'case-{tag}-{name}',link=link,kind=kind,wp=wp,**meta))
    for front,enabled in ((True,include_front),(False,include_rear)):
        if enabled:
            add('jaw-front' if front else 'jaw-rear','al',canonical_jaw(front),flat=jaw_flat(),
                manufacturing='laser 6061-T6 1.5 mm; deburr',
                qualification='case clamp preload, slip and creep test required')
    for k,z in enumerate(C['bolt_z_mm']):
        start=C['front_face_mm']+C['plate_t_mm']
        bolt=screw(C['bolt_length_mm'],'-x',(start,0,0)).rotate((0,0,0),(0,0,1),90).translate((C['bolt_x_mm'],0,z))
        add('bolt-'+str(k),'fastener',bolt,spec='M3x45 ISO4762',connection='external clamp; sample qualification required')
        rear=C['rear_face_mm']-C['plate_t_mm']
        nut=cq.Workplane('XY').polygon(6,5.5/math.cos(math.pi/6)).extrude(2.4).cut(cq.Workplane('XY').circle(1.25).extrude(2.4))
        nut=nut.rotate((0,0,0),(1,0,0),-90).translate((C['bolt_x_mm'],rear-2.4,z))
        add('nut-'+str(k),'fastener',nut,spec='M3 ISO4032; retention method to qualify')
    return parts
