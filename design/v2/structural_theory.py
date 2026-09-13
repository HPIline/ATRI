"""Transparent preliminary beam screening, not whole-assembly certification.

N, mm, MPa. Euler-Bernoulli linear elastic cantilever with end force.
Actual folded sections, holes, joints, buckling and contact require additional
analysis; straight-strip screening is neither an FEA model nor a lower bound.
"""
import json
from pathlib import Path
from .profile import PELVIS, LEG, ARM, TORSO, K


def rectangular_beam(force_n,length_mm,width_mm,thickness_mm,e_mpa):
    if min(length_mm,width_mm,thickness_mm,e_mpa)<=0 or force_n<0:
        raise ValueError('Positive dimensions/modulus and nonnegative force required')
    inertia=width_mm*thickness_mm**3/12
    return {'stress_mpa':force_n*length_mm*thickness_mm/(2*inertia),
            'deflection_mm':force_n*length_mm**3/(3*e_mpa*inertia),
            'second_moment_mm4':inertia}


def friction_grip(mass_kg,mu,load_factor,lever_mm):
    if min(mass_kg,mu,load_factor,lever_mm)<=0:raise ValueError('Positive inputs required')
    normal=mass_kg*9.81*load_factor/(2*mu)
    return {'normal_per_jaw_n':normal,'torque_nm':normal*lever_mm/1000,
            'assumes':'two opposed contacts, Coulomb friction, force normal to jaw; no wedging or object eccentricity'}


def report():
    # Modulus and yield are explicit study assumptions, not certified stock data.
    e=69000.;yield_mpa=200.;sf=2.;rows=[]
    def add(name,length,width,t,force,scope):
        r=rectangular_beam(force,length,width,t,e)
        rows.append(dict(name=name,length_mm=length,width_mm=width,thickness_mm=t,
                         force_n=force,**r,nominal_yield_margin=yield_mpa/max(r['stress_mpa'],1e-12),
                         screening_below_allowable=r['stress_mpa']<=yield_mpa/sf,scope=scope))
    # Same 1.2 Nm bench load for comparison of single unbraced strips.
    add('pelvis output web, weak-axis strip',50,PELVIS['trunk_adapter_web_mm'],PELVIS['adapter_t_mm'],1200/50,
        '1.2 Nm root moment; angle fold and tapered root not represented; critical lower section still needs CAD section analysis')
    add('pelvis rear frame, isolated web',40,PELVIS['frame_web_mm'],PELVIS['frame_t_mm'],2.45*9.81*2,
        'full 2.45 kg at k=2 applied to one cantilever; actual multi-point load distribution unknown')
    add('leg one of two webs, weak-axis strip',K['thigh'],LEG['web_mm'],LEG['plate_t_mm'],2.45*9.81*2/2,
        'equal load sharing assumed; paired frame action, axial loading and spacers not represented')
    add('arm link web, weak-axis strip',K['upper_arm'],ARM['web_mm'],ARM['angle_t_mm'],1200/K['upper_arm'],
        '1.2 Nm screening moment; actual angle section and case grip unresolved')
    add('leg drive-side web, in-plane full torque',K['thigh'],LEG['plate_t_mm'],LEG['web_mm'],1200/K['thigh'],
        'full 1.2 Nm carried by drive plate; passive rear disc does not halve drive torque')
    add('foot toe-edge concentrated load',58,70-2*LEG['foot_lightening_width_mm'],LEG['foot_plate_t_mm'],2.45*9.81*2,
        '48.07 N at toe edge, 58 mm lever; net section through both windows; stress concentrations and actual ground-pressure distribution excluded')
    grip=friction_grip(.1,.3,2,ARM['finger_length_mm'])
    add('gripper finger, out-of-plane misuse load',ARM['finger_length_mm'],ARM['finger_width_mm'],ARM['finger_t_mm'],grip['normal_per_jaw_n'],
        'contact-force magnitude applied to weak axis; normal grip acts mainly in plane, lateral object loads may not')
    add('gripper finger, in-plane ideal strip',ARM['finger_length_mm'],ARM['finger_t_mm'],ARM['finger_width_mm'],grip['normal_per_jaw_n'],
        'straight moving finger approximation; fixed return-shaped finger needs separate analysis')
    return dict(release_ready=False,method='linear cantilever screening, NOT full structure verification',
      assumptions={'E_mpa':e,'yield_mpa':yield_mpa,'yield_safety_factor':sf,'material_certified':False},
      rows=rows,grip_100g_mu03_k2=grip,
      unverified=['hole bearing/net section and stress concentration','angle section torsion and local buckling',
      'plastic case crush, creep and clamp slip','servo shaft and horn capacity','gripper contact overlap and pad bond',
      'neck and foot detailed load paths','torso tube joints and threaded rod preload','complete mass and centre of gravity',
      'fatigue, impact and continuous pose envelope'],
      interpretation='A failed strip screen flags a load-path question; it does not prove the actual braced assembly fails. A passed strip screen does not certify the assembly.')


def write():
    r=report();out=Path(__file__).parent/'out'
    (out/'structural-theory.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    lines=['# 结构理论初筛（未放行）','','这是简化梁筛查，不是整体有限元验证。材料 E=69 GPa、屈服200 MPa、安全系数2均为研究假设，待采购材料证书核实。',
    '', '| 部位 | 名义应力 MPa | 梁模型挠度 mm | 低于100 MPa |','|---|---:|---:|---|']
    for a in r['rows']:lines.append(f"| {a['name']} | {a['stress_mpa']:.1f} | {a['deflection_mm']:.2f} | {a['screening_below_allowable']} |")
    lines+=['','梁截面与加载假设详见同名 JSON。孤立薄条会忽略折边和框架共同承载，不能把失败值直接当作整机真实应力；通过也不代表夹具或孔边通过。',
    '', f"100 g、摩擦系数0.3、载荷系数2、双侧理想接触：每指法向力3.27 N，{ARM['finger_length_mm']:g} mm力臂需{r['grip_100g_mu03_k2']['torque_nm']:.3f} N·m。真实接触形状、胶垫粘接和摩擦须另验。",
    '', '## 未完成验证','']+['- '+x for x in r['unverified']]
    (out/'结构理论初筛.md').write_text('\n'.join(lines)+'\n')
    return r

if __name__=='__main__': print(json.dumps(write(),ensure_ascii=False))
