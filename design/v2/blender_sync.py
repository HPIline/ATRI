"""Run inside the visible Blender MCP session after exporting CAD parts."""
import json
import importlib
from pathlib import Path


def sync_parts(folder, focus_prefix=None, prune=False):
    import bpy
    from mathutils import Matrix, Vector
    folder=Path(folder)
    items=json.loads((folder/'parts.json').read_text())
    sources=[folder/(i.get('file',i['name']+'.stl')) for i in items]
    sources=[p if p.is_file() else folder/'parts'/p.name for p in sources]
    missing=[str(p) for p in sources if not p.is_file()]
    if missing:raise FileNotFoundError(missing)
    parents={i['link'] for i in items}
    if any(p not in bpy.data.objects for p in parents):
        raise ValueError('Open the existing ATRI review scene before synchronizing')
    from . import profile, assembly3d
    importlib.reload(profile)
    importlib.reload(assembly3d)
    tree=assembly3d.kinematic_tree()
    for kind,spec in assembly3d.KINDS.items():
        mat=bpy.data.materials.get('ATRI_'+kind) or bpy.data.materials.new('ATRI_'+kind)
        mat.use_nodes=True
        bsdf=next(node for node in mat.node_tree.nodes if node.type=='BSDF_PRINCIPLED')
        from .blender_build import linear_rgba
        rgba=linear_rgba(spec['color'])
        mat.diffuse_color=rgba;bsdf.inputs['Base Color'].default_value=rgba
        if 'Weight' in bsdf.inputs:bsdf.inputs['Weight'].default_value=1.
        bsdf.inputs['Metallic'].default_value=spec['metal'];bsdf.inputs['Roughness'].default_value=spec['rough']
    bpy.data.objects[tree['root']].location=tuple(v*.001 for v in tree['root_xyz'])
    for joint in tree['joints']:
        bpy.data.objects[joint['child']].location=tuple(v*.001 for v in joint['xyz'])
        bpy.data.objects[joint['child']]['axis']=joint['axis']
        bpy.data.objects[joint['child']]['limit_deg']=joint['limit_deg']
    window=bpy.context.window_manager.windows[0]
    area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
    region=next(r for r in area.regions if r.type=='WINDOW')
    names={i['name'] for i in items}
    if prune:
        links={row['name'] for row in tree['links']}
        for old in list(bpy.data.objects):
            if old.type=='MESH' and old.parent and old.parent.name in links and old.name not in names:
                bpy.data.objects.remove(old,do_unlink=True)
    with bpy.context.temp_override(window=window,area=area,region=region):
        if bpy.context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
        for old in list(bpy.data.objects):
            if old.name in names and old.type=='MESH':bpy.data.objects.remove(old,do_unlink=True)
        for item,source in zip(items,sources):
            bpy.ops.wm.stl_import(filepath=str(source))
            obj=bpy.context.object;obj.name=item['name'];obj.scale=(.001,)*3
            bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
            obj.parent=bpy.data.objects[item['link']]
            obj.matrix_parent_inverse=Matrix.Identity(4);obj.location=(0,0,0)
            mat=bpy.data.materials.get('ATRI_'+item['kind'])
            if mat:
                obj.data.materials.clear();obj.data.materials.append(mat)
            for k,v in item.items():
                if isinstance(v,(str,int,float)):obj[k]=v
        bpy.ops.object.select_all(action='DESELECT')
        chosen=[i['name'] for i in items if not focus_prefix or i['name'].startswith(focus_prefix)]
        if chosen:
            for name in chosen:bpy.data.objects[name].select_set(True)
            bpy.context.view_layer.objects.active=bpy.data.objects[chosen[0]]
            bpy.ops.view3d.view_selected(use_all_regions=False)
            area.spaces.active.region_3d.view_rotation=Vector((1,-1,.55)).to_track_quat('Z','Y')
        area.tag_redraw()
    print('CAD parts synchronized:',len(items))
