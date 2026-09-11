"""A.T.R.I. 答辩 PPT · 约 24 页。数字只从 facts.py 读。

用法： python3 ppt/build_deck.py
文案： docs/research/项目文档/答辩PPT-逐页文案-v4.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx.enum.text import PP_ALIGN

from design import *  # noqa: F401,F403
from design import bullets, page_frame, page_title, status_bar, num_card, table, joint_chain_h
from animate import add_transition
from diagrams import joint_topology
import facts as F

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
TOTAL = 24

CH = {
    0: ("00", "项目概要"),
    1: ("01", "构型与架构"),
    2: ("02", "软件契约"),
    3: ("03", "五项任务"),
    4: ("04", "仿真与机械"),
    5: ("05", "口径与推进"),
}


def frame(s, ch, n, dark=False):
    page_frame(s, CH[ch][0], CH[ch][1], n, total=TOTAL, dark=dark)


def p01(prs):
    s = add_slide(prs, PAPER)
    X = CONTENT_X
    text(s, X, 0.82, 6.4, 0.26,
         [P([R("中国国际大学生创新大赛（2026）", 10.5, BLUE, heavy=True),
             R("　陕西赛区特色专项 · 小人形组", 10.5, GRAY)])])
    text(s, X, 1.72, 6.4, 1.00, [P([R("A.T.R.I.", 54, INK, heavy=True, spc=1.5)])])
    text(s, X, 2.68, 6.4, 0.50, [P([R("桌面自主人形智能", 28, INK, heavy=True)])])
    rect(s, X, 3.40, 0.72, 0.05, fill=ORANGE)
    text(s, X, 3.62, 6.5, 0.36,
         [P([R("22 自由度 · 全离线 · 五项赛题同一套任务卡", 14, GRAPHITE)])])
    text(s, X, 4.20, 6.6, 0.32,
         [P([R(f"{F.DOF} DOF", 16, ORANGE, heavy=True),
             R("　·　", 11, BLUE_300),
             R("41.8 cm", 16, ORANGE, heavy=True),
             R("　·　", 11, BLUE_300),
             R(f"{F.TESTS_MAIN}+{F.TESTS_WEBOTS} 测试", 16, ORANGE, heavy=True)])])
    joint_chain_h(s, X, 5.00, 5.8, n=22, first_color=ORANGE)
    text(s, X, 5.22, 6.4, 0.24,
         [P([R(F.DOF_BREAKDOWN, 10, GRAY)])])
    text(s, X, 5.70, 6.4, 0.24, [P([R("无硬件闭环演示", 9, GRAY)])])
    text(s, X, 5.92, 6.4, 0.28, [P([R(f"{F.DEMO_TASKS} 任务通过　Python {F.PYTHON}", 13, GRAPHITE)])])
    vline(s, 7.42, 0.72, SLIDE_H - 1.44, color=LINE, width=0.75)
    joint_topology(s, cx=10.45, top=1.22, h=5.22, labels=True)


def p02(prs):
    s = add_slide(prs)
    frame(s, 0, 2)
    page_title(s, "五项赛题，一套状态机，端到端离线",
               lead="先是一台桌面双足，再是五项任务共用任务卡，最后才是教学平台。")
    items = [
        (str(F.DOF), "DOF", "主动关节全机归一 STS3215"),
        (str(F.TESTS_MAIN), "项测试", "主包 unittest，标准库"),
        (F.DEMO_TASKS, "闭环", "face / qr / carry / kick / dance"),
        (F.BOM_NEW_CNY, "元", "新增采购档（参考）"),
    ]
    w = (CONTENT_W - 0.45) / 4
    for i, (n, u, c) in enumerate(items):
        num_card(s, CONTENT_X + i * (w + 0.15), Y_BODY, w, 1.55, n, u, c, color=INK)
    bullets(s, CONTENT_X, 4.05, CONTENT_W, [
        ("已完成", "软件栈、设计模型、Webots 离线联调判据"),
        ("进行中", "CAD 质量尚未回灌 URDF；板上 Python 3.14 需自装"),
        ("规划中", "真机总线、STM32 下沉、12V 舵机实测"),
    ], gap=0.48)
    status_bar(s, ["done", "doing", "plan"])


def p03(prs):
    s = add_slide(prs)
    frame(s, 0, 3)
    page_title(s, "设备贵、算法散、断网就瘫",
               lead="小人形组要的是能离线完成五项任务的桌面双足，不是云端演示。")
    cards = [
        ("01 设备贵", "教育型小型双足套件多在万元级，一个班买不起一批。"),
        ("02 算法散", "人脸、循迹、抓取、步态散在互不相通的工程里。"),
        ("03 断网瘫", "依赖云推理的方案，赛场一断网就失效。"),
    ]
    w = (CONTENT_W - 0.4) / 3
    for i, (t, d) in enumerate(cards):
        x = CONTENT_X + i * (w + 0.2)
        card(s, x, Y_BODY, w, 2.4)
        text(s, x + 0.2, Y_BODY + 0.2, w - 0.4, 0.4, [P([R(t, 16, INK, heavy=True)])])
        text(s, x + 0.2, Y_BODY + 0.8, w - 0.4, 1.3, [P([R(d, 13, GRAPHITE)], line_spacing=1.25)])
    status_bar(s, ["design"])


def p04(prs):
    s = add_slide(prs)
    frame(s, 0, 4)
    page_title(s, "全离线、桌面尺寸、预算可讲清",
               lead="树莓派 4B 只是 BOM 参考板，软件按通用 Linux aarch64 写。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("包络", f"现行 {F.ENVELOPE_MM[0]}×{F.ENVELOPE_MM[1]}×{F.ENVELOPE_MM[2]} mm，赛题上限 {F.ENVELOPE_RULE_MM[0]}×{F.ENVELOPE_RULE_MM[1]}×{F.ENVELOPE_RULE_MM[2]} mm"),
        ("离线", "人脸检测、二维码、TTS、任务卡全部本地；禁止云 API 当赛场依赖"),
        ("成本", f"新增采购 {F.BOM_NEW_CNY} 元；全口径 {F.BOM_FULL_CNY} 元"),
        ("板", F.BOARD_REF),
    ], gap=0.55)
    status_bar(s, ["design"])


def p05(prs):
    s = add_slide(prs)
    frame(s, 1, 5)
    page_title(s, "22 自由度：上肢加躯干正好 10",
               lead="检录口径不能砍躯干或夹爪。关节名与限位以 software/atri 与 robot_model.json 为准。")
    table(s, CONTENT_X, Y_BODY, CONTENT_W,
          ["分区", "数量", "说明"],
          [
              ["双腿", "10", "每腿 5：髋滚/髋俯仰/膝/踝俯仰/踝滚"],
              ["双臂", "8", "每臂 4，含末端夹爪"],
              ["躯干", "2", "计入上肢+躯干=10 的检录项"],
              ["头部", "2", "yaw + pitch"],
          ])
    status_bar(s, ["done"])


def p06(prs):
    s = add_slide(prs)
    frame(s, 1, 6)
    page_title(s, "大脑在 Linux 板上，小脑今天是 Python",
               lead="文档可以规划 STM32 下沉；当前仓库里没有 C 固件。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("大脑", "任务卡、FSM、技能、感知、语音。Python 3.14，主包零 pip"),
        ("小脑", "步态、动作库、限位钳制。板上跑的就是这套 Python"),
        ("总线", "22 路 STS3215 规划；真串口留接口，本轮不假装已实现"),
        ("仿真", "Webots 在 x86；ARM 板不跑 3D 仿真"),
    ], gap=0.52)
    status_bar(s, ["done", "plan"])


def p07(prs):
    s = add_slide(prs)
    frame(s, 2, 7)
    page_title(s, "技能必须报真成败，超时只举旗",
               lead="评委问「失败了会不会还往下踢」——不会。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("失败即停", "感知失败不下发实体动作，后续技能不跑"),
        ("found", "只接受 bool。字符串 \"False\" 在 Python 里为真，会判非法"),
        ("超时", "定时器线程只置 abort_event；home() 只在主线程、execute 返回后一次"),
        ("测试", f"主包 {F.TESTS_MAIN} 项覆盖这些契约"),
    ], gap=0.52)
    status_bar(s, ["done"])


def p08(prs):
    s = add_slide(prs)
    frame(s, 2, 8)
    page_title(s, "改 JSON 就能改动作，NaN 进不了舵机",
               lead="限位在 set_angle 统一钳制，子类只能写 _write_angle。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("动作库", "关键帧 JSON，校验器拒绝非有限值"),
        ("步态", "generate_gait 出双足正弦关键帧"),
        ("安全", "NaN / Inf 直接 ValueError，不会被钳成限位尽头"),
    ], gap=0.55)
    status_bar(s, ["done"])


def p09(prs):
    s = add_slide(prs)
    frame(s, 2, 9)
    page_title(s, "人脸能检出框，比对还没做",
               lead="Q&A 已承认身份模块未实现。PPT 不许吹成「认出是谁」。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("已有", "Haar 人脸框、二维码 JSON、球的 found/偏移（Mock 或 OpenCV）"),
        ("未做", "人脸特征比对、face_db.json 从未被代码加载"),
        ("依赖", "OpenCV 可选，板上用 opencv-python-headless"),
    ], gap=0.55)
    status_bar(s, ["done", "plan"])


def p10(prs):
    s = add_slide(prs)
    frame(s, 2, 10)
    page_title(s, "Linux 上语音可升级，没有引擎就 Mock",
               lead="探测 piper → espeak-ng → espeak → spd-say；ATRI_TTS 可强制。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("板上", "apt 装 espeak-ng 即可发声；piper 更好听，模型不进 git"),
        ("CI", f"无引擎时 Mock，{F.TESTS_MAIN} 项测试不依赖喇叭"),
        ("macOS", "仍用系统 say"),
    ], gap=0.55)
    status_bar(s, ["done"])


def p11(prs):
    s = add_slide(prs)
    frame(s, 3, 11)
    page_title(s, "任务 face：对准，不声称认出姓名",
               lead="头部 2 DOF 跟检测框；播报走 TTS，身份库未接。")
    status_bar(s, ["done", "plan"])


def p12(prs):
    s = add_slide(prs)
    frame(s, 3, 12)
    page_title(s, "任务 qr：二维码里是一段可执行 JSON",
               lead="非法动作、越界步数、坏编码都变成技能失败，不炸 traceback。")
    status_bar(s, ["done"])


def p13(prs):
    s = add_slide(prs)
    frame(s, 3, 13)
    page_title(s, "任务 carry：轻物、双臂、失败就停",
               lead="设计目标 ≤100 g。观测缺距离则失败，不硬编距离。")
    status_bar(s, ["done"])


def p14(prs):
    s = add_slide(prs)
    frame(s, 3, 14)
    page_title(s, "任务 kick：先看见球，再踢",
               lead="缺测距看任务卡参数；再没有就失败。不再写死 12 cm。")
    status_bar(s, ["done"])


def p15(prs):
    s = add_slide(prs)
    frame(s, 3, 15)
    page_title(s, "任务 dance：动作库回放，超时在帧边界停",
               lead="不能从半路掐断一次阻塞调用，这是诚实限制。")
    status_bar(s, ["done"])


def p16(prs):
    s = add_slide(prs)
    frame(s, 4, 16)
    page_title(s, "Webots：三层绑定，零重力不是走路",
               lead=f"离线 {F.TESTS_WEBOTS} 项测试。映射截断或 --velocity 0 必须失败。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("覆盖", "映射键必须恰好是 22 个合法关节名"),
        ("绑定", "非空条目全部绑上；Nao 留空 4 个自由度仍算过"),
        ("行程", "至少一个关节 >1°，不是每个关节都动"),
        ("重力", "当前世界零重力，只证明运动学联调，不证明能走 1 m"),
    ], gap=0.48)
    status_bar(s, ["done"])


def p17(prs):
    s = add_slide(prs)
    frame(s, 4, 17)
    page_title(s, "髋肩错轴 30–35 mm，不要拿 8–12 回改",
               lead="19.6 mm 轴距塞不下两只 35 mm 机体。关节轴不动，机体沿自身轴抽出。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("权威表", "fit_stagger.py：hip_roll / shoulder_pitch +35，hip_pitch +30"),
        ("新件", "cluster_horn_arm + cluster_outrigger"),
        ("电子件", "按 kind 落座，显示名对不上就失败"),
    ], gap=0.55)
    status_bar(s, ["done"])


def p18(prs):
    s = add_slide(prs)
    frame(s, 5, 18)
    page_title(s, "两套质量都是真的，不要混引",
               lead="CAD 更轻，但还没写回 URDF。仿真仍按提交口径。")
    table(s, CONTENT_X, Y_BODY, CONTENT_W,
          ["层", "结构", "整机", "用途"],
          [
              ["提交 / URDF", f"{F.MASS_URDF_STRUCTURE_G} g", f"{F.MASS_URDF_TOTAL_G} g", "测试与交接包钉死"],
              ["CAD 现行", f"{F.MASS_CAD_STRUCTURE_G} g", f"{F.MASS_CAD_TOTAL_G} g", "未回灌"],
              ["错轴后结构", f"约 {F.MASS_CAD_AFTER_STAGGER_G} g", "—", "新件 +86 g"],
          ])
    status_bar(s, ["doing"])


def p19(prs):
    s = add_slide(prs)
    frame(s, 5, 19)
    page_title(s, "扭矩主判据是 0.98，不是 1.47",
               lead="0.98 来自 12V 兄弟型号，尚未用本仓库那份 7.4V 规格书实测。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("踝", f"{F.ANKLE_NM} N·m ≈ 连续额定的 {F.ANKLE_PCT_CONTINUOUS}%"),
        ("腰", f"{F.WAIST_NM} N·m ≈ {F.WAIST_PCT_CONTINUOUS}%"),
        ("峰值", f"{F.TORQUE_PEAK_NM} N·m 只作短时参考；CAD「102%」用的是峰值"),
    ], gap=0.55)
    status_bar(s, ["design"])


def p20(prs):
    s = add_slide(prs)
    frame(s, 5, 20)
    page_title(s, "2000 mAh 大约 13 分钟，30 分钟要 4.53 Ah",
               lead="现选电池不满足赛题续航。补电池会加重，扭矩只会更差。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("现选", f"{F.BATTERY_SELECTED_MAH} mAh · {F.VOLTAGE} · 约 {F.BATTERY_RUNTIME_MIN} min"),
        ("需求", f"标称 ≥ {F.BATTERY_REQUIRED_AH} Ah"),
    ], gap=0.55)
    status_bar(s, ["plan"])


def p21(prs):
    s = add_slide(prs)
    frame(s, 5, 21)
    page_title(s, "BOM：全口径与新增采购分开写",
               lead="树莓派按 2026 内存涨价计入。软件不绑这块板。")
    table(s, CONTENT_X, Y_BODY, CONTENT_W,
          ["口径", "金额", "含什么"],
          [
              ["全口径", F.BOM_FULL_CNY + " 元", "含备用舵机与平衡充"],
              ["新增采购", F.BOM_NEW_CNY + " 元", "扣实验室已有边缘板+STM32"],
          ])
    status_bar(s, ["design"])


def p22(prs):
    s = add_slide(prs)
    frame(s, 5, 22)
    page_title(s, "当场可以跑的四条命令",
               lead="本机无显示 Ubuntu、Python 3.14.7 已跑通。CadQuery 与真 Webots 窗口未在本机跑。")
    lines = [
        "cd software/atri && python3 -m unittest discover -s tests",
        "python3 run_demo.py --fast",
        "cd webots/tests && python3 -m unittest test_atri_controller",
        "python3 webots/tools/generate_atri_world.py",
    ]
    y = Y_BODY
    for i, cmd in enumerate(lines, 1):
        text(s, CONTENT_X, y, CONTENT_W, 0.28, [P([R(f"{i}.  {cmd}", 13, GRAPHITE)])])
        y += 0.48
    text(s, CONTENT_X, y + 0.2, CONTENT_W, 0.5,
         [P([R(f"结果：{F.TESTS_MAIN} + {F.TESTS_WEBOTS} + {F.DEMO_TASKS} + 世界文件幂等", 14, INK, heavy=True)])])
    status_bar(s, ["done"])


def p23(prs):
    s = add_slide(prs)
    frame(s, 5, 23)
    page_title(s, "还没做的，写在这里",
               lead="减重、换电池、装 3.14、真机串口。不把规划写成已完成。")
    bullets(s, CONTENT_X, Y_BODY, CONTENT_W, [
        ("质量回灌", "CadQuery 重测后写入 robot_model.json / URDF"),
        ("扭矩实测", "买一只 12V STS3215"),
        ("真机", "SerialServoBus、可选 STM32 下沉"),
        ("续航", "换 ≥4.53 Ah 或缩短任务时间"),
    ], gap=0.48)
    status_bar(s, ["plan"])


def p24(prs):
    s = add_slide(prs, INK)
    text(s, CONTENT_X, 2.2, CONTENT_W, 0.7,
         [P([R("A.T.R.I.", 40, WHITE, heavy=True)])])
    text(s, CONTENT_X, 3.0, CONTENT_W, 0.4,
         [P([R(f"{F.DOF} DOF · Python {F.PYTHON} · 全离线 · {F.DEMO_TASKS}", 16, ORANGE, heavy=True)])])
    text(s, CONTENT_X, 4.2, CONTENT_W, 0.4,
         [P([R("地基在软件契约和结构拓扑。真机还没装上。", 16, WHITE)])])
    text(s, CONTENT_X, 5.4, CONTENT_W, 0.3,
         [P([R("恳请各位评委批评指正", 14, BLUE_300)])])


PAGES = [p01, p02, p03, p04, p05, p06, p07, p08, p09, p10,
         p11, p12, p13, p14, p15, p16, p17, p18, p19, p20,
         p21, p22, p23, p24]


def main():
    stem = sys.argv[1] if len(sys.argv) > 1 else "ATRI-答辩PPT-v4"
    prs = new_deck()
    for fn in PAGES:
        fn(prs)
    for slide in prs.slides:
        add_transition(slide, "fade", 700)
    path = OUT / f"{stem}.pptx"
    prs.save(str(path))
    print(f"saved: {path}  ({len(PAGES)} pages)")


if __name__ == "__main__":
    main()
