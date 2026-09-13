"""Open pelvis and cut/drilled stock-angle adapters; dimensions in profile.py.

Fixed mounting uses external case clamps. The passive disc remains free.
Clamp slip and case deformation require the single-servo sample test.
"""
from __future__ import annotations
import math,json
from pathlib import Path
import cadquery as cq
from .profile import PELVIS as P,K,SERVO,CASE_MOUNT as C


def cyl(r,length,axis,at):
 w=cq.Workplane('XY').circle(r).extrude(length)
 if axis=='x':w=w.rotate((0,0,0),(0,1,0),90)
 if axis=='y':w=w.rotate((0,0,0),(1,0,0),-90)
 return w.translate(at)


def screw(length,axis,at):
 """ISO 4762 nominal M3 envelope; unmodelled helical thread is metadata."""
 body=cq.Workplane('XY').circle(1.5).extrude(length)
 head=cq.Workplane('XY').circle(2.75).extrude(-3.0)
 socket=cq.Workplane('XY').polygon(6,2.5/math.cos(math.pi/6)).extrude(-1.4).translate((0,0,-1.6))
 s=body.union(head.cut(socket))
 if axis=='x':s=s.rotate((0,0,0),(0,1,0),90)
 if axis=='-x':s=s.rotate((0,0,0),(0,1,0),-90)
 if axis=='y':s=s.rotate((0,0,0),(1,0,0),-90)
 return s.translate(at)


def build_pelvis_items():
 from .case_mount import build_case_clamp
 from .cad_parts import orient_y_to_axis
 items=[]
 def add(name,link,kind,wp,**meta):
  items.append(dict(name=name,link=link,kind=kind,wp=wp,**meta))
 hw=K['hip_width']/2
 centers=[('left_hip_roll',hw,0),('right_hip_roll',-hw,0),('trunk_roll',0,P['trunk_roll_z_mm'])]
 t=P['frame_t_mm'];r=P['frame_pad_r_mm'];web=P['frame_web_mm']
 holes=[]
 for tag,y,z in centers:
  clock=P['housing_clock_deg'][tag]
  for part in build_case_clamp(tag,'pelvis'):
   wp=part['wp']
   if '-nut-' in part['name']:wp=wp.translate((0,-t-P['frame_washer_mm'],0))
   part['wp']=orient_y_to_axis(wp,(1,0,0)).rotate((0,0,0),(1,0,0),clock).translate((0,y,z))
   items.append(part)
  sign=1 if clock>0 else -1
  for zz in C['bolt_z_mm']:holes.append((y-sign*zz,z-sign*C['bolt_x_mm']))
 # One laser-cut bridge joins the six clamp bolts, away from all output discs.
 flat=None
 for y,z in holes:
  disk=cq.Workplane('XY').center(y,z).circle(r).extrude(t)
  flat=disk if flat is None else flat.union(disk)
 paths=[(holes[0],holes[1]),(holes[2],holes[3]),(holes[4],holes[5])]
 for upper,lower in ((holes[1],holes[5]),(holes[2],holes[4])):
  corner=(upper[0],lower[1]);paths.extend(((upper,corner),(corner,lower)))
 for a,b in paths:
  dy,dz=b[0]-a[0],b[1]-a[1]
  length=math.hypot(dy,dz)
  bar=cq.Workplane('XY').box(length,web,t,centered=(True,True,False)).rotate((0,0,0),(0,0,1),math.degrees(math.atan2(dz,dy))).translate(((a[0]+b[0])/2,(a[1]+b[1])/2,0))
  flat=flat.union(bar)
 for y,z in holes:
  flat=flat.cut(cq.Workplane('XY').center(y,z).circle(C['hole_mm']/2).extrude(t))
 # Rotation maps local (y,z,t) to world (t,y,z).
 face=C['rear_face_mm']-C['plate_t_mm']-P['frame_washer_mm']
 frame=flat.rotate((0,0,0),(1,1,1),120).translate((face-t,0,0))
 add('pelvis-open-frame','pelvis','al',frame,manufacturing=f'laser 6061-T6 {t:g} mm; deburr; clamp slip qualification required',flat=flat,mount_holes=holes)
 for k,(y,z) in enumerate(holes):
  washer=cyl(3.5,P['frame_washer_mm'],'x',(face,y,z)).cut(cyl(C['hole_mm']/2,P['frame_washer_mm'],'x',(face,y,z)))
  add(f'pelvis-frame-washer-{k}','pelvis','fastener',washer,spec='M3 washer 0.5 mm')
 # Independent output adapters: the rear frame stays fixed; each adapter turns.
 for tag,link,target_z in [('left','left_hip_roll_link',-K['hip_stack_z']),('right','right_hip_roll_link',-K['hip_stack_z']),('trunk','trunk_roll_link',P['trunk_pitch_offset_mm'])]:
  tt=P['adapter_t_mm'];inner=P['front_horn_inner_mm']+P['horn_t_mm']
  case_face=C['front_face_mm'];ymin=case_face+tt-P['adapter_angle_leg_mm']
  zmin=min(-10,target_z-C['height_mm']/2);zmax=max(10,target_z+C['height_mm']/2)
  leg=P['adapter_angle_leg_mm']
  out_h=P['adapter_output_half_height_mm'];out_y0=P['adapter_output_y_min_mm']
  front=cq.Workplane('XY').box(tt,case_face+tt-out_y0,2*out_h).translate((inner+tt/2,(out_y0+case_face+tt)/2,0))
  if tag != 'trunk':
   # Trim unused rectangular corners; retain the complete PCD14 mounting pad.
   front=cyl(P['hip_output_pad_radius_mm'],tt,'x',(inner,0,0))
   bridge=cq.Workplane('XY').box(tt,case_face+tt,2*P['hip_output_neck_half_width_mm']).translate((inner+tt/2,(case_face+tt)/2,0))
   front=front.union(bridge)
  # Saw away unused stock flanges; keep a continuous diagonal side web.
  depth=P['adapter_depth_leg_mm']
  web_width=P['trunk_adapter_web_mm'] if tag=='trunk' else P['adapter_web_mm']
  forward=tag=='trunk'
  start_x=inner+tt if forward else inner-tt
  end_x=-C['bolt_x_mm'] if forward else C['bolt_x_mm']
  path=[(start_x,0)]
  if not forward:path.append(P['hip_adapter_waypoint_xz_mm'])
  path.append((end_x,target_z));side_flat=None
  for a,b in zip(path,path[1:]):
   dx,dz=b[0]-a[0],b[1]-a[1];span=math.hypot(dx,dz)
   web=cq.Workplane('XY').box(span,web_width,tt,centered=(True,True,False)).rotate((0,0,0),(0,0,1),math.degrees(math.atan2(dz,dx))).translate(((a[0]+b[0])/2,(a[1]+b[1])/2,0))
   side_flat=web if side_flat is None else side_flat.union(web)
  side_flat=side_flat.union(cq.Workplane('XY').box(2*tt,2*out_h,tt,centered=(True,True,False)).translate((inner+tt if forward else inner,0,0)))
  xmin,xmax=(-C['x_span_mm'][1],-C['x_span_mm'][0]) if forward else (inner+tt-depth,C['x_span_mm'][1])
  end_pad=cq.Workplane('XY').box(xmax-xmin,C['height_mm'],tt,centered=(True,True,False))
  if not forward:end_pad=end_pad.edges('|Z').fillet(P['hip_profile_radius_mm'])
  side_flat=side_flat.union(end_pad.translate(((xmin+xmax)/2,target_z,0)))
  if forward:
   # Keep the side flange inside the stock heel: widening must not grow
   # behind the output face into the adjacent hip clamp sweep.
   side_flat=side_flat.intersect(cq.Workplane('XY').box(depth,2*(zmax-zmin)+40,tt,centered=(False,True,False)).translate((inner,target_z/2,0)))
  side=side_flat.rotate((0,0,0),(1,0,0),90).translate((0,case_face+tt,0))
  adapter=front.union(side)
  corner=inner+tt if forward else inner
  internal=[e for e in adapter.edges('|Z').vals() if abs(e.Center().x-corner)<.001 and abs(e.Center().y-case_face)<.001]
  if forward and internal:adapter=adapter.newObject(internal).fillet(P['adapter_inner_radius_mm'])
  if not forward:
   r=P['adapter_inner_radius_mm'];h=P['hip_output_neck_half_width_mm']
   root=cq.Workplane('XY').box(r,r,2*h,centered=(False,False,False)).translate((inner-r,case_face-r,-h))
   root=root.cut(cyl(r,2*h,'z',(inner-r,case_face-r,-h)))
   adapter=adapter.union(root)
  if forward:
   # Radius the remote through-profile corners after the stock inner radius.
   # Leave the folded root untouched so its actual extrusion radius is retained.
   profile_edges=[e for e in adapter.edges('|Y').vals() if e.Center().x >= xmin-1e-6]
   adapter=adapter.newObject(profile_edges).fillet(P['trunk_profile_radius_mm'])
   flat_edges=[e for e in side_flat.edges('|Z').vals() if e.Center().x >= xmin-1e-6]
   side_flat=side_flat.newObject(flat_edges).fillet(P['trunk_profile_radius_mm'])
  for u,v in ((4.95,4.95),(4.95,-4.95),(-4.95,4.95),(-4.95,-4.95)):
   adapter=adapter.cut(cyl(SERVO['horn_clear_mm']/2,tt+2,'x',(inner-1,u,v)))
   front=front.cut(cyl(SERVO['horn_clear_mm']/2,tt+2,'x',(inner-1,u,v)))
  for zz in C['bolt_z_mm']:
   adapter=adapter.cut(cyl(C['hole_mm']/2,tt+2,'y',(end_x,case_face-1,target_z+zz)))
   side_flat=side_flat.cut(cyl(C['hole_mm']/2,tt,'z',(end_x,target_z+zz,0)))
  adapter=adapter.cut(cyl(3.3,tt+2,'x',(inner-1,0,0)))
  front=front.cut(cyl(3.3,tt+2,'x',(inner-1,0,0)))
  output_flat=front.translate((-inner,0,0)).rotate((0,0,0),(1,1,1),-120)
  profile_note=f"remote profile R{P['trunk_profile_radius_mm']:g}; " if forward else f"round PCD pad R{P['hip_output_pad_radius_mm']:g}; bridge width {2*P['hip_output_neck_half_width_mm']:g}; side profile R{P['hip_profile_radius_mm']:g}; "
  add(f'pelvis-output-adapter-{tag}',link,'al',adapter,manufacturing=f'6061-T6 stock angle {depth:g}x{leg:g}x{tt:g}, saw length {zmax-zmin:g}; trim flange and open side profile; 6x3.2 and 1x6.6 drilled; inner R<=3; {profile_note}NO CNC pockets',stock_cut_length_mm=zmax-zmin,side_flat=side_flat,output_flat=output_flat)
  for part in build_case_clamp(tag+'-pitch',link,include_front=False):
   wp=part['wp']
   if '-bolt-' in part['name']:wp=wp.translate((0,tt-C['plate_t_mm'],0))
   if forward:wp=wp.rotate((0,0,0),(0,1,0),180)
   part['wp']=wp.translate((0,0,target_z));items.append(part)
  for i,(u,v) in enumerate(((4.95,4.95),(4.95,-4.95),(-4.95,4.95),(-4.95,-4.95))):
   add(f'adapter-output-screw-{tag}-{i}',link,'fastener',screw(6,'-x',(inner+tt,u,v)),spec='M3x6; 3 mm horn engagement')
 return items


def mesh_payload(items):
 out=[]
 for it in items:
  vertices,faces=it['wp'].val().tessellate(.08,.15)
  verts=[]
  for inds in faces:
   a,b,c=[vertices[j] for j in inds]
   n=(b-a).cross(c-a)
   if n.Length: n=n.normalized()
   for p in (a,b,c):verts.extend([p.x,p.y,p.z,n.x,n.y,n.z])
  out.append(dict(name=it['name'],link=it['link'],kind=it['kind'],alpha=1.,verts=verts))
 return out


def export_pelvis(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 items=build_pelvis_items()
 for i in items:
  cq.exporters.export(i['wp'],str(out/(i['name']+'.stl')))
  if i['kind']=='al':cq.exporters.export(i['wp'],str(out/(i['name']+'.step')))
 frame=next(i for i in items if i['name']=='pelvis-open-frame')
 cq.exporters.export(frame['flat'].faces('<Z'),str(out/'pelvis-open-frame.dxf'))
 (out/'parts.json').write_text(json.dumps([{k:v for k,v in i.items() if k not in ('wp','flat','side_flat','output_flat')} for i in items],ensure_ascii=False,indent=2))
 (out/'meshes.json').write_text(json.dumps(mesh_payload(items),separators=(',',':')))
 from .geometry_cache import pelvis_source_hash
 (out/'geometry-source.json').write_text(json.dumps({'sha256':pelvis_source_hash(),'units':'mm','source':'pelvis_cad.py','release':'HOLD'}))
 mass=sum(i['wp'].val().Volume()*2.7/1000 for i in items if i['kind']=='al')
 print(json.dumps({'parts':len(items),'aluminum_g':mass,'release':'HOLD: sample interface and full assembly verification pending'}))
 return items

if __name__=='__main__':
 import sys
 export_pelvis(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent/'out'/'pelvis-revision')
