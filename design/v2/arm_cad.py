"""Candidate stock-angle arm links and independently fixed/moving fingers.

External case clamps need slip, preload and creep qualification on a sample.
All design parameters are collected below pending migration to profile.py.
"""
import math
import cadquery as cq
from .profile import K, SERVO, CASE_MOUNT as C, ARM
from .case_mount import build_case_clamp
from .pelvis_cad import cyl, screw




def parameters():
    return ARM


def _path(points,width,t):
    shape=None
    for x,z in points:
        disk=cq.Workplane('XY').center(x,z).circle(width/2).extrude(t)
        shape=disk if shape is None else shape.union(disk)
    for (x,z),(xx,zz) in zip(points,points[1:]):
        if math.hypot(xx-x,zz-z)<1e-9:continue
        bar=cq.Workplane('XY').box(math.hypot(xx-x,zz-z),width,t,centered=(True,True,False)).rotate((0,0,0),(0,0,1),math.degrees(math.atan2(zz-z,xx-x))).translate(((x+xx)/2,(z+zz)/2,0))
        shape=shape.union(bar)
    return shape


def _transform(wp,swapped):
    # Reference output +X and case +Y -> actual output +Y and case +X.
    return wp.rotate((0,0,0),(1,1,0),180) if swapped else wp


def _orthogonal(tag,link,target,clock,swapped=False,output_spacer=0.):
    p=parameters();t=p['angle_t_mm'];parts=[]
    def add(name,kind,wp,**meta):
        parts.append(dict(name=f'arm-{tag}-{name}',link=link,kind=kind,wp=_transform(wp,swapped),**meta))
    face=p['output_front_mm']+output_spacer
    # Target case jaw is replaced by the stock-angle side leg, bearing at +Y.
    def case_pose(wp):
        return wp.rotate((0,0,0),(0,1,0),clock).translate(target)
    holes=[]
    a=math.radians(clock)
    for z in C['bolt_z_mm']:
        holes.append((target[0]+C['bolt_x_mm']*math.cos(a)+z*math.sin(a),target[2]-C['bolt_x_mm']*math.sin(a)+z*math.cos(a)))
    midpoint=((holes[0][0]+holes[1][0])/2,(holes[0][1]+holes[1][1])/2)
    bridge_z=midpoint[1]-p['upper_bridge_drop_mm'] if tag.endswith('-upper') else midpoint[1]
    if tag.endswith('-fore'):bridge_z+=p['fore_bridge_drop_mm']
    waypoints=[(face,bridge_z),(midpoint[0],bridge_z),midpoint,*holes]
    sideflat=_path(waypoints,p['web_mm'],t)
    # Exact flat clamp contact patch, including both external bolt pads.
    jaw=cq.Workplane('XY').box(C['x_span_mm'][1]-C['x_span_mm'][0],C['height_mm'],t,centered=(True,True,False)).translate(((C['x_span_mm'][0]+C['x_span_mm'][1])/2,0,0)).rotate((0,0,0),(0,0,1),-clock).translate((target[0],target[2],0))
    sideflat=sideflat.union(jaw)
    if tag.endswith('-fore'):
        extra=(p['finger_case_bolt_y_mm'],target[2]-p['finger_case_bolt_z_mm'][1])
        sideflat=sideflat.union(_path([holes[0],holes[1],extra],p['web_mm'],t))
        holes.append(extra)
        sideflat=sideflat.intersect(cq.Workplane('XY').box(p['clip_extent_mm'],p['clip_extent_mm'],t,centered=(False,True,False)).translate((p['fore_jaw_long_end_mm']-p['clip_extent_mm'],0,0)))
    extent=p['clip_extent_mm'];side_limit=face+t-extent if midpoint[0]<face else face
    sideflat=sideflat.intersect(cq.Workplane('XY').box(extent,extent,t,centered=(False,True,False)).translate((side_limit,0,0)))
    for x,z in holes:sideflat=sideflat.cut(cyl(C['hole_mm']/2,t,'z',(x,z,0)))
    side=sideflat.rotate((0,0,0),(1,0,0),90).translate((0,C['front_face_mm']+t+target[1],0))
    y1=C['front_face_mm']+t+target[1]
    output_path=[(0,0),(y1-t,bridge_z)]
    if tag.endswith('-fore'):
        yy,zz=p['fore_output_waypoint_yz_mm']
        output_path=[(0,0),(yy,zz),(yy,bridge_z),(y1-t,bridge_z)]
    outputflat=cq.Workplane('XY').circle(p['output_radius_mm']).extrude(t).union(_path(output_path,p['web_mm'],t))
    if not tag.endswith('-fore'):
        outputflat=outputflat.intersect(cq.Workplane('XY').box(extent,extent,t,centered=(False,True,False)).translate((y1-extent,0,0)))
    output=outputflat.rotate((0,0,0),(1,1,1),120).translate((face,0,0))
    sq=SERVO['horn_hole_square_mm']/2
    for y,z in ((sq,sq),(sq,-sq),(-sq,sq),(-sq,-sq)):
        outputflat=outputflat.cut(cyl(SERVO['horn_clear_mm']/2,t,'z',(y,z,0)))
        output=output.cut(cyl(SERVO['horn_clear_mm']/2,2*t,'x',(face-t,y,z)))
        bolt_length=output_spacer+p['spaced_bolt_base_mm'] if output_spacer else p['horn_bolt_mm']
        bolt=screw(bolt_length,'-x',(face+t,y,z))
        if tag.endswith('-fore'):
            bolt_length=p['fore_csk_bolt_mm']
            cone=cq.Workplane('XY').newObject([cq.Solid.makeCone(p['csk_head_d_mm']/2,1.5,p['csk_depth_mm'])])
            bolt=cone.union(cyl(1.5,bolt_length,'z',(0,0,0)))
            bolt=bolt.cut(cq.Workplane('XY').polygon(6,p['button_socket_af_mm']/math.cos(math.pi/6)).extrude(p['button_socket_depth_mm']))
            bolt=bolt.rotate((0,0,0),(0,1,0),-90).translate((face+t,y,z))
            sink=cq.Workplane('XY').newObject([cq.Solid.makeCone(p['csk_head_d_mm']/2,C['hole_mm']/2,p['csk_depth_mm'])]).rotate((0,0,0),(0,1,0),-90).translate((face+t,y,z))
            output=output.cut(sink)
        add(f'output-bolt-{y}-{z}','fastener',bolt,spec=f"M3x{bolt_length:g} ISO4762; nominal thread")
        if tag.endswith('-fore'):parts[-1]['spec']=f'M3x{bolt_length:g} DIN7991 countersunk; length includes head'
        if output_spacer:
            stack=p['fore_spacer_stack_mm'] if tag.endswith('-fore') else (output_spacer,)
            start=p['output_front_mm']
            for k,span in enumerate(stack):
                ring=cyl(p['spacer_od_mm']/2,span,'x',(start,y,z)).cut(cyl(C['hole_mm']/2,span,'x',(start,y,z)))
                add(f'output-spacer-{y}-{z}-{k}','al' if span>1 else 'fastener',ring,spec=f"M3 OD{p['spacer_od_mm']:g} ID{C['hole_mm']:g} spacer/shim {span:g}mm")
                start+=span
    output=output.cut(cyl(p['center_d_mm']/2,2*t,'x',(face-t,0,0)))
    outputflat=outputflat.cut(cyl(p['center_d_mm']/2,t,'z',(0,0,0)))
    angle=output.union(side)
    inner_x=face if midpoint[0]<face else face+t
    inner_y=C['front_face_mm']+target[1]
    radius=p['inside_r_mm'];direction=-1 if midpoint[0]<face else 1
    # Preserve the real stock corner wherever both open trimming profiles
    # retain it. The two extruded profiles also define the actual saw cuts.
    fillet=cq.Workplane('XY').box(radius,radius,extent).translate((inner_x+direction*radius/2,inner_y-radius/2,0))
    fillet=fillet.cut(cyl(radius,extent,'z',(inner_x+direction*radius,inner_y-radius,-extent/2)))
    output_mask=outputflat.faces('>Z').wires().toPending().extrude(extent,combine=False).rotate((0,0,0),(1,1,1),120).translate((face-extent/2,0,0))
    side_mask=sideflat.faces('>Z').wires().toPending().extrude(extent,combine=False).rotate((0,0,0),(1,0,0),90).translate((0,inner_y+extent/2,0))
    fillet=fillet.intersect(output_mask).intersect(side_mask)
    angle=angle.union(fillet)
    for x,z in holes:
        angle=angle.cut(cyl(C['hole_mm']/2,t+radius,'y',(x,inner_y-radius,z)))
    # Saw-cut open profile, not a milled pocket; the side profile is retained
    # separately for a cutting/drilling template, not sold as a standalone plate.
    bounds=angle.val().BoundingBox()
    stock_leg=None if tag=='right-shoulder' else next(leg for leg in p['stock_equal_leg_mm'] if leg>=max(bounds.xlen,bounds.ylen)-1e-6)
    cut_length=math.ceil(bounds.zlen)
    if tag=='right-shoulder':
        sideflat,outputflat,joining=_split_shoulder(sideflat,outputflat,face,inner_y,bridge_z)
        add('case-cheek','al',sideflat.rotate((0,0,0),(1,0,0),90).translate((0,inner_y+t,0)),flat=sideflat,manufacturing=f"laser {p['material']} {t:g}mm; deburr",qualification=C['qualification'])
        add('output-cheek','al',outputflat.rotate((0,0,0),(1,1,1),120).translate((face,0,0)),flat=outputflat,manufacturing=f"laser {p['material']} {t:g}mm; deburr")
        for name,kind,wp,meta in joining:add(name,kind,wp,**meta)
    else:
        add('angle','al',angle,side_flat=sideflat,output_flat=outputflat,
            stock_angle_mm=(stock_leg,stock_leg,t),stock_cut_length_mm=cut_length,
            manufacturing=f"{p['material']} stock {stock_leg:g}x{stock_leg:g}x{t:g} angle, saw {cut_length:g}mm; trim both open flange profiles and drill; R{radius:g} inside corner; no CNC pockets"+('; four DIN7991 countersinks after drilling' if tag.endswith('-fore') else ''),
            qualification=C['qualification']+'; angle section, radius and trim quote must be confirmed by supplier')
    for part in build_case_clamp(tag,link,include_front=False):
        wp=part['wp']
        if tag.endswith('-fore') and part['name'].endswith('jaw-rear'):
            clip=cq.Workplane('XY').box(p['clip_extent_mm'],p['clip_extent_mm'],p['clip_extent_mm'],centered=(False,True,True)).translate((-p['fore_jaw_long_end_mm'],0,0))
            wp=wp.intersect(clip)
            part['flat']=part['flat'].intersect(cq.Workplane('XY').box(p['clip_extent_mm'],p['clip_extent_mm'],C['plate_t_mm'],centered=(False,True,False)).translate((-p['fore_jaw_long_end_mm'],0,0)))
        if '-bolt-' in part['name']:wp=wp.translate((0,t-C['plate_t_mm'],0))
        if tag=='right-upper':
            zz=C['bolt_z_mm'][int(part['name'].rsplit('-',1)[1])] if '-bolt-' in part['name'] or '-nut-' in part['name'] else None
            if '-bolt-' in part['name']:
                cap=cq.Workplane('XY').circle(p['button_head_d_mm']/2).extrude(-p['button_head_h_mm'])
                cap=cap.edges('<Z').fillet(p['button_edge_r_mm'])
                wp=cyl(1.5,C['bolt_length_mm'],'z',(0,0,0)).union(cap)
                socket=cq.Workplane('XY').polygon(6,p['button_socket_af_mm']/math.cos(math.pi/6)).extrude(p['button_socket_depth_mm']).translate((0,0,-p['button_head_h_mm']))
                wp=wp.cut(socket).rotate((0,0,0),(1,0,0),-90).translate((C['bolt_x_mm'],C['rear_face_mm']-C['plate_t_mm'],zz))
                part['spec']='M3x45 ISO7380 button socket screw, reverse installed; property class 10.9'
            elif '-nut-' in part['name']:
                wp=cq.Workplane('XY').polygon(6,p['nut_af_mm']/math.cos(math.pi/6)).extrude(p['nut_h_mm']).cut(cyl(p['nut_bore_mm']/2,p['nut_h_mm'],'z',(0,0,0)))
                wp=wp.rotate((0,0,0),(1,0,0),-90).translate((C['bolt_x_mm'],C['front_face_mm']+t,zz))
        part['wp']=_transform(case_pose(wp),swapped)
        parts.append(part)
    return parts


def _split_shoulder(sideflat,outputflat,face,inner_y,zcenter):
    """Two laser cheeks joined by a short, drilled commodity angle."""
    p=parameters();t=p['angle_t_mm'];leg=p['shoulder_join_leg_mm'];length=p['shoulder_join_length_mm'];inset=p['shoulder_join_hole_inset_mm'];result=[]
    angle=cq.Workplane('XY').box(t,leg,length).translate((face-t/2,inner_y-leg/2,zcenter))
    angle=angle.union(cq.Workplane('XY').box(leg,t,length).translate((face-leg/2,inner_y-t/2,zcenter)))
    corner=(face-t,inner_y-t,zcenter)
    angle=angle.edges(cq.selectors.NearestToPointSelector(corner)).fillet(p['inside_r_mm'])
    for dz in p['shoulder_join_hole_z_mm']:
        z=zcenter+dz;sx=face-inset;oy=inner_y-inset
        sideflat=sideflat.union(cq.Workplane('XY').center(sx,z).circle(p['shoulder_join_pad_r_mm']).extrude(t))
        outputflat=outputflat.union(_path([(inner_y,zcenter),(oy,z)],2*p['shoulder_join_pad_r_mm'],t))
        sideflat=sideflat.cut(cyl(C['hole_mm']/2,t,'z',(sx,z,0)))
        outputflat=outputflat.cut(cyl(C['hole_mm']/2,t,'z',(oy,z,0)))
        angle=angle.cut(cyl(C['hole_mm']/2,t,'x',(face-t,oy,z))).cut(cyl(C['hole_mm']/2,t,'y',(sx,inner_y-t,z)))
        for label,at in [('output',(face+t,oy,z)),('side',(sx,inner_y+t,z))]:
            fast=screw(p['shoulder_join_screw_mm'],'-x',(0,0,0))
            if label=='side':fast=fast.rotate((0,0,0),(0,0,1),90)
            result.append((f'join-{label}-bolt-{dz}','fastener',fast.translate(at),dict(spec=f"M3x{p['shoulder_join_screw_mm']:g} ISO4762")))
            nut=cq.Workplane('XY').polygon(6,p['nut_af_mm']/math.cos(math.pi/6)).extrude(p['nut_h_mm']).cut(cyl(p['nut_bore_mm']/2,p['nut_h_mm'],'z',(0,0,0)))
            if label=='output':nut=nut.rotate((0,0,0),(0,1,0),90).translate((face-t-p['nut_h_mm'],oy,z))
            else:nut=nut.rotate((0,0,0),(1,0,0),-90).translate((sx,inner_y-t-p['nut_h_mm'],z))
            result.append((f'join-{label}-nut-{dz}','fastener',nut,dict(spec='M3 ISO4032')))
    result.append(('join-angle','al',angle,dict(stock_angle_mm=(leg,leg,t),stock_cut_length_mm=length,manufacturing=f"stock {p['material']} {leg:g}x{leg:g}x{t:g} angle; saw {length:g}mm; drill four {C['hole_mm']:g}mm holes; R{p['inside_r_mm']:g} inside")))
    # The flat cheeks butt at the corner; they must not occupy the same
    # 3mm corner volume that was continuous in the previous stock angle.
    sideflat=sideflat.intersect(cq.Workplane('XY').box(p['clip_extent_mm'],p['clip_extent_mm'],t,centered=(False,True,False)).translate((face-p['clip_extent_mm'],0,0)))
    return sideflat,outputflat,result


def build_arm_items():
    items=[];p=parameters()
    for side,sgn in [('left',1),('right',-1)]:
        shoulder=_orthogonal('left-shoulder','left_upper',(p['shoulder_offset_mm'],0,0),-90,swapped=True,output_spacer=p['output_spacer_mm']['shoulder'])
        if side=='right':
            for part in shoulder:
                part['name']=part['name'].replace('left','right')
                part['link']='right_upper';part['wp']=part['wp'].mirror('XZ')
                part['assembly']='mirrored external shoulder output; right shoulder pitch axis -Y'
        items.extend(shoulder)
        items.extend(_orthogonal(side+'-upper',side+'_fore',(0,0,-K['upper_arm']),0,output_spacer=p['output_spacer_mm']['upper']))
        fore=_orthogonal(side+'-fore',side+'_hand',(0,0,K['forearm']),180,swapped=True,output_spacer=p['output_spacer_mm']['fore'])
        items.extend(part for part in fore if part['name']!='case-'+side+'-fore-bolt-0')
        items.extend(_gripper(side))
    return items


def _gripper(side):
    p=parameters();t=p['finger_t_mm'];parts=[];length=p['finger_length_mm']
    def add(name,link,kind,wp,**meta):
        if link.endswith('_hand'):wp=wp.translate((0,0,-K['forearm']))
        parts.append(dict(name=f'arm-{side}-gripper-{name}',link=link,kind=kind,wp=wp,**meta))
    def yz(flat,x):return flat.rotate((0,0,0),(1,1,1),120).translate((x,0,0))
    # The lower case-clamp bolt and an added drilled ear carry the fixed
    # finger; the upper bolt stays flush enough for the fully folded arm.
    by=p['finger_case_bolt_y_mm'];zlo,zhi=p['finger_case_bolt_z_mm'];bz=p['finger_bridge_z_mm'];fy=p['fixed_finger_y_mm']
    fixed=_path([(by,zhi),(by,bz),(fy,bz),(fy,-length)],p['finger_width_mm'],t)
    fixed=fixed.union(_path([(by,zlo),(by,zhi)],p['finger_mount_web_mm'],t))
    for z in p['finger_case_bolt_z_mm']:fixed=fixed.cut(cyl(C['hole_mm']/2,t,'z',(by,z,0)))
    add('fixed-finger',side+'_hand','al',yz(fixed,p['finger_mount_x_mm']),flat=fixed,manufacturing=f"laser {p['material']} {t:g}mm; deburr",qualification='finger stiffness and pinch-force sample test required')
    moving=cq.Workplane('XY').circle(p['output_radius_mm']).extrude(t).union(_path([(0,0),(p['moving_finger_tip_y_mm'],-length)],p['finger_width_mm'],t))
    a=SERVO['horn_hole_square_mm']/2
    for u,v in ((a,a),(a,-a),(-a,a),(-a,-a)):
        moving=moving.cut(cyl(C['hole_mm']/2,t,'z',(u,v,0)))
        add(f'moving-bolt-{u}-{v}',side+'_grip','fastener',screw(p['finger_bolt_mm'],'-x',(p['moving_finger_x_mm']+t,u,v)),spec=f"M3x{p['finger_bolt_mm']:g} ISO4762; nominal thread")
        at=p['output_front_mm']
        for index,ll in enumerate(p['finger_spacer_stack_mm']):
            ring=cyl(p['spacer_od_mm']/2,ll,'x',(at,u,v)).cut(cyl(C['hole_mm']/2,ll,'x',(at,u,v)))
            add(f'moving-spacer-{u}-{v}-{index}',side+'_grip','al' if ll>1 else 'fastener',ring,spec=f"M3 plain spacer/shim OD{p['spacer_od_mm']:g} ID{C['hole_mm']:g} length{ll:g}mm")
            at+=ll
    moving=moving.cut(cyl(p['finger_center_d_mm']/2,t,'z',(0,0,0)))
    add('moving-finger',side+'_grip','al',yz(moving,p['moving_finger_x_mm']),flat=moving,manufacturing=f"laser {p['material']} {t:g}mm; deburr")
    # The extra ear is part of the forearm angle and has its own through nut.
    for z in p['finger_case_bolt_z_mm']:
        start=p['fixed_spacer_face_mm'];span=p['finger_mount_x_mm']-start
        ring=cyl(p['fixed_spacer_od_mm']/2,span,'x',(start,by,z)).cut(cyl(C['hole_mm']/2,span,'x',(start,by,z)))
        add('fixed-spacer-'+str(z),side+'_hand','al',ring,spec=f"M3 OD{p['fixed_spacer_od_mm']:g} ID{C['hole_mm']:g} spacer {span:g}mm")
        length_bolt=p['fixed_bolt_mm'] if z==p['finger_case_bolt_z_mm'][0] else p['finger_aux_bolt_mm']
        add('fixed-bolt-'+str(z),side+'_hand','fastener',screw(length_bolt,'-x',(p['finger_mount_x_mm']+t,by,z)),spec=f"M3x{length_bolt:g} ISO4762 through finger, spacer and angle")
        if z==p['finger_case_bolt_z_mm'][1]:
            nut=cq.Workplane('XY').polygon(6,p['nut_af_mm']/math.cos(math.pi/6)).extrude(p['nut_h_mm']).cut(cyl(p['nut_bore_mm']/2,p['nut_h_mm'],'z',(0,0,0)))
            nut=nut.rotate((0,0,0),(0,1,0),90).translate((C['front_face_mm']-p['nut_h_mm'],by,z))
            add('fixed-aux-nut',side+'_hand','fastener',nut,spec='M3 ISO4032')
    for name,link in [('fixed',side+'_hand'),('moving',side+'_grip')]:
        yy=p['pad_y_mm'][name]
        left=p['moving_finger_x_mm']
        right=p['finger_mount_x_mm']+t if name=='fixed' else left+t
        pad_h=p['pad_height_mm'][name]
        pad=cq.Workplane('XY').box(right-left,p['pad_t_mm'],pad_h).translate(((left+right)/2,yy,-length+pad_h/2))
        if name=='moving':pad=pad.rotate((0,0,0),(1,0,0),math.degrees(math.atan2(p['moving_finger_tip_y_mm'],length)))
        add(name+'-pad',link,'tpu',pad,print_face='+X',manufacturing='TPU95A adhesive grip strip; bond qualification required')
    return parts
