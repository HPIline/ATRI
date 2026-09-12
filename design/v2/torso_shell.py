"""Removable two-piece chest shell, bolted to integral electronics-carrier ears.

Candidate dimensions are centralized in profile.py (TORSO_SHELL).
The function returns replacement carriers plus the shell and its hardware;
callers must replace the input list, not append its returned carriers again.
"""
import math
import cadquery as cq
from .pelvis_cad import cyl, screw
from .profile import TORSO_SHELL




def _box(bounds):
    x0,y0,z0,x1,y1,z1=bounds
    return cq.Workplane('XY').box(x1-x0,y1-y0,z1-z0,centered=(False,False,False)).translate((x0,y0,z0))


def _nut(af,height,bore):
    shape=cq.Workplane('YZ').polygon(6,af/math.cos(math.pi/6)).extrude(height)
    return shape.cut(cyl(bore/2,height,'x',(0,0,0))) if bore else shape


def add_torso_shell(items, parameters=None):
    """Return new item dictionaries, with ears fused into the three real carriers."""
    p=dict(TORSO_SHELL if parameters is None else parameters)
    result=[dict(item) for item in items]
    index={item['name']:item for item in result}
    required=('bus-bridge','sbc-carrier-0','sbc-carrier-1')
    if any(name not in index for name in required):
        raise ValueError('Torso shell requires bus-bridge and both sbc-carrier anchors')
    if any(name.startswith('shell-torso-') for name in index):
        raise ValueError('Torso shell already installed')
    x0,y0,z0,x1,y1,z1=p['bounds_mm'];t=p['wall_mm']
    body=_box((x0,y0,z0,x1,y1,z1)).cut(_box((x0+t,y0+t,z0-1,x1-t,y1-t,z1-t)))
    wx0,wz0,wx1,wz1=p['shoulder_window_xz_mm']
    for lo,hi in ((y0-1,y0+t+1),(y1-t-1,y1+1)):
        body=body.cut(_box((wx0,lo,wz0-1,wx1,hi,wz1)))
    ax0,ay0,ax1,ay1=p['yaw_window_xy_mm']
    body=body.cut(_box((ax0,ay0,z1-t-1,ax1,ay1,z1+1)))
    ry0,rz0,ry1,rz1=p['rear_window_yz_mm']
    body=body.cut(_box((x0-1,ry0,rz0-1,x0+t+1,ry1,rz1)))
    for z in p['front_vent_z_mm']:
        # Rounded ventilation slots are intentional openings, with solid ribs
        # between them and no overlap with the four shell attachment locations.
        vent=cq.Workplane('YZ').slot2D(p['front_vent_length_mm'],p['front_vent_height_mm']).extrude(t+2).translate((x1-t-1,0,z))
        body=body.cut(vent)
    seam=p['seam_x_mm'];gap=p['seam_gap_mm']
    shells={'front':body.intersect(_box((seam+gap/2,y0-1,z0-1,x1+1,y1+1,z1+1))),
            'rear':body.intersect(_box((x0-1,y0-1,z0-1,seam-gap/2,y1+1,z1+1)))}
    def add(name,kind,wp,**meta):
        result.append(dict(name=name,link='torso',kind=kind,wp=wp,**meta))
    def mount(tag,number,anchor_name,ear,y,z,seat,direction):
        # Captive hex pocket opens upward into the cavity. The axial lip takes
        # screw tension; the nut is installed before attaching the shell.
        contact=seat+direction*t
        near=contact+direction*p['retaining_lip_mm']
        far=near+direction*p['nut_pocket_axial_mm']
        lo,hi=sorted((near,far))
        pocket=_nut(p['nut_pocket_af_mm'],hi-lo,0).translate((lo,y,z))
        access=_box((lo,y-p['nut_pocket_af_mm']/2,z,hi,y+p['nut_pocket_af_mm']/2,z+15))
        bore=cyl(p['bolt_clear_mm']/2,50,'x',(min(seat,contact)-35,y,z))
        anchor=index[anchor_name]
        anchor['wp']=anchor['wp'].union(ear).cut(pocket).cut(access).cut(bore)
        anchor['shell_mount']='integral side-load M3 captive-nut ear; install nut before shell'
        if len(anchor['wp'].val().Solids())!=1 or not anchor['wp'].val().isValid():
            raise ValueError(f'Detached or invalid shell ear: {anchor_name}')
        shells[tag]=shells[tag].cut(cyl(p['bolt_clear_mm']/2,t+2,'x',(seat-1 if direction>0 else contact-1,y,z)))
        nutx=lo+(hi-lo-p['nut_h_mm'])/2
        add(f'shell-torso-{tag}-nut-{number}','fastener',_nut(p['nut_af_mm'],p['nut_h_mm'],2.5).translate((nutx,y,z)),spec='M3 ISO4032 nominal envelope; captive pocket fit requires sample')
        add(f'shell-torso-{tag}-screw-{number}','fastener',screw(p['bolt_length_mm'],'x' if direction>0 else '-x',(seat,y,z)),spec=f"M3x{p['bolt_length_mm']:g} ISO4762; insert from exterior along X")
    for n,y in enumerate(p['front_mount_y_mm']):
        z=p['front_mount_z_mm'];half=p['front_ear_width_mm']/2;hz=p['front_ear_height_mm']/2
        ear=_box((p['front_ear_start_x_mm'],y-half,z-hz,x1-t,y+half,z+hz))
        mount('front',n,'bus-bridge',ear,y,z,x1,-1)
    for n in range(2):
        anchor=index[f'sbc-carrier-{n}'];bb=anchor['wp'].val().BoundingBox();y=(bb.ymin+bb.ymax)/2
        z=p['rear_mount_z_mm'];half=p['rear_ear_width_mm']/2;hz=p['rear_ear_height_mm']/2
        ear=_box((x0+t,y-half,z-hz,p['rear_ear_inner_x_mm'],y+half,z+hz))
        web=_box((p['rear_ear_web_x_mm'],y-half,p['rear_web_bottom_z_mm'],p['rear_ear_inner_x_mm'],y+half,z+hz))
        mount('rear',n,f'sbc-carrier-{n}',ear.union(web),y,z,x0,1)
    for tag,shape in shells.items():
        if not shape.val().isValid() or len(shape.val().Solids())!=1:
            raise ValueError(f'Invalid or disconnected torso shell: {tag}')
        add('shell-torso-'+tag,'petg',shape,print_face='+X' if tag=='front' else '-X',wall_mm=t,
            material='opaque matte white PETG',assembly='independently remove two exterior M3 screws; captive nuts loaded from inside before closure',
            qualification='candidate shell: connector insertion, full ROM and print supports require integrated checks')
    return result
