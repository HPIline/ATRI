"""Actual modeled arm mass + T3 payload gravity envelope, with explicit limits."""
import json,math,itertools
from pathlib import Path
from .assembly3d import kinematic_tree,fk,m_apply
from .mass_ledger import DENSITY_G_MM3
from .profile import ARM,K,SERVO


def point_gravity_moment(origin_mm,axis,point_mm,mass_g):
    return (-(point_mm[1]-origin_mm[1])*axis[0]+(point_mm[0]-origin_mm[0])*axis[1])*mass_g*9.81/1e6


def report(side="left", items=None):
    from .cad_export import build_items
    tree=kinematic_tree();parents={x['name']:x['parent'] for x in tree['links']}
    def below(link,root):
        while link:
            if link==root:return True
            link=parents[link]
        return False
    rows=[];omitted=[]
    for it in (build_items() if items is None else items):
        if not below(it['link'],side+'_upper'):continue
        if it['name'].startswith('servo-'):m=55.
        elif it['kind'] in DENSITY_G_MM3:m=it['wp'].val().Volume()*DENSITY_G_MM3[it['kind']]
        else:omitted.append(it['name']);continue
        rows.append(dict(name=it['name'],link=it['link'],mass_g=m,center=it['wp'].val().Center().toTuple()))
    # Payload follows the fixed hand frame. Approximate object centre between
    # opposing pads; +/- uncertainty is retained separately, not hidden.
    rows.append(dict(name='T3-object',link=side+'_hand',mass_g=100.,
       center=(ARM['moving_finger_x_mm'],0.,-K['forearm']-ARM['finger_length_mm']+ARM['pad_height_mm']['fixed']/2)))
    names=[side+'_'+n for n in ('shoulder_pitch','shoulder_roll','elbow_pitch')]
    maxima={n:dict(static_nm=-1.) for n in names};count=0
    for pitch,roll,elbow in itertools.product(range(-90,91,15),range(0,91,15),range(-120,1,15)):
        pose=dict(zip(names,[pitch,roll if side=='left' else -roll,elbow]));w=fk(tree,[pose.get(j['name'],0.) for j in tree['joints']]);count+=1
        for j in tree['joints']:
            if j['name'] not in names:continue
            origin=m_apply(w[j['child']],(0,0,0));aa=m_apply(w[j['parent']],j['axis']);zz=m_apply(w[j['parent']],(0,0,0));axis=[aa[k]-zz[k] for k in range(3)]
            torque=0.
            for row in rows:
                if not below(row['link'],j['child']):continue
                c=m_apply(w[row['link']],row['center']);torque+=point_gravity_moment(origin,axis,c,row['mass_g'])
            if abs(torque)>maxima[j['name']]['static_nm']:maxima[j['name']]=dict(static_nm=abs(torque),pose_deg=pose)
    for r in maxima.values():
        r['k14_nm']=r['static_nm']*1.4;r['k2_nm']=r['static_nm']*2
        r['rated_utilization_static']=r['static_nm']/SERVO['rated_nm']
        r['k14_below_85pct_rated']=r['k14_nm']<=SERVO['rated_nm']*.85
        r['k2_below_rated']=r['k2_nm']<=SERVO['rated_nm']
        r['strip_inplane_mpa_at_k2']=r['k2_nm']*1000/(ARM['angle_t_mm']*ARM['web_mm']**2/6)
        r['strip_outofplane_mpa_at_k2']=r['k2_nm']*1000/(ARM['web_mm']*ARM['angle_t_mm']**2/6)
    return dict(release_ready=False,side=side,
      mass_model='geometric homogeneous materials plus nominal 55g servo; missing parts are explicitly omitted',
      known_arm_mass_without_payload_g=sum(x['mass_g'] for x in rows)-100,
      payload_g=100,payload_not_in_robot_weighing=True,omitted_modeled_items=omitted,
      additionally_unmodeled='arm wiring; purchased servo accessory mass scope unresolved',
      sampled_poses=count,gravity_maxima=maxima,
      limitations=['No inertial dynamics: k=1.4/2 are comparison multipliers only',
      'Maximum may be at an infeasible combined pose; this is a rectangular joint-range load envelope',
      'Payload centre approximation, not a solved object contact pose',
      'Strip stresses do not include actual angle-frame load sharing, torsion or root concentrations',
      'Horn thread pullout, spacer bending, housing clamp slip and fatigue remain unqualified'])

def markdown(results):
    lines=['# 手臂与 T3 载荷理论核验（未放行）','',
      '每侧携带100 g，物体不计入整机称重；按当前已建模质量扫描每侧819个关节组合。',
      '', '| 关节 | 静态峰值 N·m | ×1.4 | ×2 | ×2 / 额定 |', '|---|---:|---:|---:|---:|']
    for side in results.values():
        for name,r in side['gravity_maxima'].items():
            lines.append(f"| {name} | {r['static_nm']:.3f} | {r['k14_nm']:.3f} | {r['k2_nm']:.3f} | {r['k2_nm']/SERVO['rated_nm']:.1%} |")
    worst=max(r['k2_nm'] for side in results.values() for r in side['gravity_maxima'].values())
    weak_z=ARM['web_mm']*ARM['angle_t_mm']**2/6
    lines+=['',f'按孤立3×9 mm腹板弱轴比较，最大×2弯矩的名义应力约{worst*1000/weak_z:.1f} MPa。实际折边、变截面根部与连接没有被这一梁模型求解，不能据此认定整臂强度通过。',
      '', '## 隔柱螺钉初筛','',
      '| 连接 | 参考弯矩/扭矩 N·m | 隔柱mm | 单钉纯扭剪力N | 根部悬臂应力MPa |','|---|---:|---:|---:|---:|']
    root_d=3-1.22687*.5;section=math.pi*root_d**3/32
    shoulder=max(v['k2_nm'] for side in results.values() for name,v in side['gravity_maxima'].items() if 'shoulder' in name)
    elbow=max(v['k2_nm'] for side in results.values() for name,v in side['gravity_maxima'].items() if 'elbow' in name)
    from .structural_theory import friction_grip
    grip=friction_grip(.1,.3,2,ARM['finger_length_mm'])['torque_nm']
    for name,tq,span in [('肩输出',shoulder,ARM['output_spacer_mm']['shoulder']),('肘至前臂输出',elbow,ARM['output_spacer_mm']['fore']),('夹爪T3',grip,sum(ARM['finger_spacer_stack_mm']))]:
        shear=tq*1000/(4*7);stress=shear*span/section
        lines.append(f'| {name} | {tq:.3f} | {span:g} | {shear:.1f} | {stress:.1f} |')
    lines+=['', '四颗M3按PCD14均匀分配纯扭矩，螺纹根径按公制基本几何近似；悬臂跨度取隔柱长度。没有求解预紧摩擦、附加横向力、轴向拉力或实际螺钉等级，不能直接给安全系数。',
      '', '## 结论与未决项','',
      '已计质量＋100 g研究对象下，当前舵机重力包络有余量；整臂强度尚未放行。以下限制不能忽略：','']
    lines+=['- '+x for x in next(iter(results.values()))['limitations']]
    lines+=['- 材料/螺钉等级与舵盘螺纹啮合必须采购核实，塑料壳夹持和胶垫粘接须样件验证。',
      '- 未计齐线束和舵机附件质量；载荷系数不是动力学仿真。']
    return '\n'.join(lines)+'\n'


if __name__=='__main__':
    from .cad_export import build_items
    items=build_items();r={side:report(side,items) for side in ('left','right')}
    (Path(__file__).parent/'out/arm-load-audit.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    (Path(__file__).parent/'out/手臂载荷核验.md').write_text(markdown(r))
    print(json.dumps({side:{'mass_g':v['known_arm_mass_without_payload_g'],'maxima':v['gravity_maxima']} for side,v in r.items()},ensure_ascii=False))
