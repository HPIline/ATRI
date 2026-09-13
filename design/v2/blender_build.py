"""Render the exported, individually identified CAD assembly with Cycles HIP.

No vendor substitutions, missing-part skips or proxy-mesh fallbacks. The same
studio/shot functions can run through MCP in the owner's visible Blender scene.
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[1]
if str(DESIGN) not in sys.path: sys.path.insert(0, str(DESIGN))


def linear_rgba(rgb):
    values=[v/255 for v in rgb]
    return tuple(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values)+(1.,)


def configure_studio(samples=64):
    import bpy
    from mathutils import Vector
    scene=bpy.context.scene
    scene.render.engine='CYCLES';scene.cycles.samples=samples
    scene.render.use_sequencer=False;scene.render.use_compositing=False
    scene.cycles.use_denoising=True
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='HIP';prefs.get_devices()
    devices=[]
    for device in prefs.devices:
        device.use=device.type=='HIP'
        if device.use:devices.append(device.name)
    if not devices:raise RuntimeError('A HIP GPU is required; CPU fallback is disabled')
    scene.cycles.device='GPU'
    scene.render.resolution_x=1600;scene.render.resolution_y=1200
    scene.render.resolution_percentage=100;scene.render.film_transparent=False
    scene.render.image_settings.file_format='PNG'
    scene.view_settings.view_transform='AgX'
    world=scene.world or bpy.data.worlds.new('ATRI_studio')
    scene.world=world;world.use_nodes=True
    background=next(n for n in world.node_tree.nodes if n.type=='BACKGROUND')
    background.inputs['Color'].default_value=(.15,.18,.22,1)
    background.inputs['Strength'].default_value=.35
    # Remove studio lights only; structural parts are never touched here.
    for obj in list(scene.objects):
        if obj.type=='LIGHT':bpy.data.objects.remove(obj,do_unlink=True)
    target=Vector((0,0,.25))
    for name,position,energy,size in (
        ('ATRI_key',(.65,-.6,.9),8,.55),
        ('ATRI_fill',(.15,.7,.55),5,.7),
        ('ATRI_rim',(-.65,-.2,.8),7,.45)):
        data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.shape='DISK';data.size=size
        obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj)
        obj.location=position;obj.rotation_euler=(target-obj.location).to_track_quat('-Z','Y').to_euler()
    cam=scene.camera
    if cam is None:
        cam=bpy.data.objects.new('ATRI_product_camera',bpy.data.cameras.new('ATRI_product_camera'))
        scene.collection.objects.link(cam);scene.camera=cam
    cam.data.type='ORTHO';cam.data.clip_start=.001;cam.data.clip_end=20
    print('CYCLES HIP ONLY:',devices)
    return devices


def _bounds(objects):
    from mathutils import Vector
    points=[obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:raise ValueError('Shot contains no geometry')
    low=Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return low,high


def frame_shot(objects,direction=(1,-1,.4),margin=1.25):
    import bpy
    from mathutils import Vector
    bpy.context.view_layer.update()
    low,high=_bounds(objects);center=(low+high)/2
    cam=bpy.context.scene.camera;cam.location=center+Vector(direction).normalized()*max((high-low).length*3,.35)
    cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.update()
    inverse=cam.matrix_world.inverted()
    pts=[inverse @ (obj.matrix_world @ Vector(c)) for obj in objects for c in obj.bound_box]
    width=max(p.x for p in pts)-min(p.x for p in pts)
    height=max(p.y for p in pts)-min(p.y for p in pts)
    ratio=bpy.context.scene.render.resolution_x/bpy.context.scene.render.resolution_y
    cam.data.ortho_scale=max(width,height*ratio)*margin


def assembly_objects():
    import bpy
    from v2.assembly3d import kinematic_tree
    links={x['name'] for x in kinematic_tree()['links']}
    return [o for o in bpy.context.scene.objects if o.type=='MESH' and o.parent and o.parent.name in links]


def render_shots(out, samples=64):
    """Render actual assembled geometry, then an explicitly exploded service view."""
    import bpy
    from mathutils import Vector
    out=Path(out);folder=out/'blender/renders';folder.mkdir(parents=True,exist_ok=True)
    devices=configure_studio(samples);parts=assembly_objects()
    if not parts:raise ValueError('No named CAD assembly in the visible scene')
    original={o.name:(o.location.copy(),o.hide_render) for o in parts}
    rendered=[]
    shots=[('product_iso',(1,-1,.45),parts),('product_front',(1,0,.12),parts),
           ('product_rear',(-1,-.3,.25),parts),
           ('detail_horn',(1,.8,.4),[o for o in parts if 'left-shoulder' in o.name or o.name=='servo-left_shoulder_roll']),
           ('detail_pelvis',(1,-.6,.3),[o for o in parts if o.parent.name=='pelvis' or 'pelvis' in o.name]),
           ('detail_camera',(1,-.6,.25),[o for o in parts if o.parent.name=='head'])]
    try:
        for name,direction,focus in shots:
            frame_shot(focus,direction,1.3)
            bpy.context.scene.render.filepath=str(folder/(name+'.png'))
            bpy.ops.render.render(write_still=True);rendered.append(name+'.png')
        # Only removable covers are translated. This is a service illustration,
        # not a substitute for ordered fastening/assembly instructions.
        for obj in parts:
            if obj.name=='shell-torso-front':obj.location.x+=.10
            elif obj.name=='shell-torso-rear':obj.location.x-=.10
            elif obj.name=='cover-head-f':obj.location.x+=.07
            elif obj.name=='cover-head-b':obj.location.x-=.07
        frame_shot(parts,(1,-1,.45),1.25)
        bpy.context.scene.render.filepath=str(folder/'service_exploded.png')
        bpy.ops.render.render(write_still=True);rendered.append('service_exploded.png')
    finally:
        for obj in parts:obj.location, obj.hide_render=original[obj.name]
        bpy.context.view_layer.update();frame_shot(parts)
    report=dict(devices=devices,cpu_enabled=False,engine='CYCLES',samples=samples,
                part_count=len(parts),renders=rendered,
                scope='CAD review renders, not photographs or proof of assembly qualification')
    (folder/'render-report.json').write_text(json.dumps(report,indent=2))
    return report


def build(out,samples=64):
    import bpy
    from v2.assembly3d import kinematic_tree,KINDS
    from mathutils import Matrix
    out=Path(out).resolve();manifest=json.loads((out/'sim/parts.json').read_text())
    files=[out/'sim/parts'/i['file'] for i in manifest]
    if not manifest or any(not p.is_file() for p in files):raise ValueError('Complete actual CAD parts export is required')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    tree=kinematic_tree();empties={}
    for link in tree['links']:
        obj=bpy.data.objects.new(link['name'],None);bpy.context.scene.collection.objects.link(obj);empties[obj.name]=obj
    empties[tree['root']].location=tuple(v*.001 for v in tree['root_xyz'])
    for joint in tree['joints']:
        child=empties[joint['child']];child.parent=empties[joint['parent']]
        child.location=tuple(v*.001 for v in joint['xyz'])
        child['axis']=joint['axis'];child['joint']=joint['name'];child['limit_deg']=joint['limit_deg']
    mats={}
    for kind,spec in KINDS.items():
        mat=bpy.data.materials.new('ATRI_'+kind);mat.use_nodes=True
        node=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        color=linear_rgba(spec['color'])
        mat.diffuse_color=color;node.inputs['Base Color'].default_value=color
        node.inputs['Metallic'].default_value=spec['metal'];node.inputs['Roughness'].default_value=spec['rough']
        if 'Weight' in node.inputs:node.inputs['Weight'].default_value=1.
        mats[kind]=mat
    for item,path in zip(manifest,files):
        bpy.ops.wm.stl_import(filepath=str(path));obj=bpy.context.object
        obj.name=item['name'];obj.scale=(.001,)*3
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        obj.parent=empties[item['link']];obj.matrix_parent_inverse=Matrix.Identity(4);obj.location=(0,0,0)
        obj.data.materials.clear();obj.data.materials.append(mats[item['kind']])
    bpy.ops.mesh.primitive_plane_add(size=3)
    bpy.context.object.name='ground'
    report=render_shots(out,samples)
    dest=out/'blender/ATRI-v2-assembly-review.blend';dest.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(dest))
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=Path(__file__).parent/'out');parser.add_argument('--samples',type=int,default=64)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    print(build(args.out,args.samples))
