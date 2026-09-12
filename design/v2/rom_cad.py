"""Sample actual CAD motion. This is not continuous collision detection."""
from pathlib import Path
import json
import hashlib
from .cad_export import build_items
from .cad_audit import intersections
from .assembly3d import kinematic_tree


def report():
    items=build_items();tree=kinematic_tree();cases=[]
    def run(name,pose):
        angles=[pose.get(j['name'],0.) for j in tree['joints']]
        result=intersections(items,angles,include_same_link=False)
        cases.append(dict(name=name,pose_deg=pose,**result))
        print(name,'PASS' if result['ok'] else result['intersections'],flush=True)
    zero=intersections(items)
    for joint in tree['joints']:
        for angle in joint['limit_deg']:run(f"{joint['name']} {angle:g}",{joint['name']:angle})
    run('shallow crouch',{f'{s}_{j}_pitch':v for s in ('left','right') for j,v in [('hip',-20),('knee',40),('ankle',-20)]})
    run('hip abduction',{'left_hip_roll':25,'right_hip_roll':-25})
    run('arms raised',{'left_shoulder_pitch':90,'right_shoulder_pitch':-90})
    run('folded arms',{'left_shoulder_roll':90,'right_shoulder_roll':-90,'left_elbow_pitch':-120,'right_elbow_pitch':-120})
    run('look left up',{'head_yaw':90,'head_pitch':-45})
    run('look right down',{'head_yaw':-90,'head_pitch':45})
    digest=hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        digest.update(path.name.encode());digest.update(path.read_bytes())
    return dict(part_count=len(items),zero=zero,cases=cases,source_sha256=digest.hexdigest(),
      sampled_structural_clearance_ok=zero['ok'] and all(x['ok'] for x in cases),
      continuous_motion_verified=False,all_combinations_verified=False,
      wiring_verified=False,fastener_engagement_scope='Intentional thread engagement excluded; local mounting tests include fixed hardware where applicable',
      release_ready=False)


if __name__=='__main__':
    r=report();path=Path(__file__).parent/'out/rom-cad-audit.json';path.write_text(json.dumps(r,ensure_ascii=False,indent=2))
    print(path,r['sampled_structural_clearance_ok'])
