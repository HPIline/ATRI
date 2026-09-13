"""CAD pad spacing and overlap screen; no claim of measured grip force."""
import json
from pathlib import Path
from .arm_cad import _gripper
from .profile import K,ARM
from .structural_theory import friction_grip


def report():
    parts={p['name']:p for p in _gripper('left')}
    fixed=parts['arm-left-gripper-fixed-pad']['wp'].translate((0,0,K['forearm'])).val()
    moving=parts['arm-left-gripper-moving-pad']['wp'].val();a=fixed.BoundingBox();poses=[]
    for angle in range(0,61,5):
        s=moving.rotate((0,0,0),(1,0,0),angle);b=s.BoundingBox()
        poses.append(dict(angle_deg=angle,pad_min_distance_mm=fixed.distance(s),
          axial_overlap_mm=max(0,min(a.xmax,b.xmax)-max(a.xmin,b.xmin)),
          height_overlap_mm=max(0,min(a.zmax,b.zmax)-max(a.zmin,b.zmin))))
    return dict(target={'object_mm':[15,35],'mass_kg':.1,'task':'T3','payload_in_robot_weighing':False},
      dimensions={'finger_length_mm':ARM['finger_length_mm'],'finger_width_mm':ARM['finger_width_mm'],'finger_t_mm':ARM['finger_t_mm'],
      'forearm_mm':K['forearm'],'pad_height_mm':ARM['pad_height_mm']},poses=poses,
      friction_sensitivity=[dict(mu=mu,**friction_grip(.1,mu,2,ARM['finger_length_mm'])) for mu in (.2,.3,.5)],
      minimum_gap_scope='distance between solid pads, not a certified grasp diameter; curved/rectangular object contact and wedging differ',
      release_ready=False,remaining=['actual object insertion and both contact normals','minimum grip-pad bond area; metal-backed fixed pad retains about 0.2 mm lip',
      'force/current limitation and servo heating','slip under shaking, object eccentricity and friction variability',
      '100 g payload at arm extension must be included in posture torque/balance tests'])

if __name__=='__main__':
    r=report();(Path(__file__).parent/'out/gripper-audit.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    print(r['poses'][-1])
