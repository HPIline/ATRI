"""A.T.R.I. 答辩 PPT 生成器（ATRI-v2 / 20 DOF 口径）。

写作规范（本文件所有文案必须遵守）
1. 面向评审的**创新竞赛叙事**：讲痛点、构型、技术栈、创新点、阶段成果与落地路线。
2. 不把研发过程搬上屏幕：不出现命令行、仓库路径、提交号、内部备注、待办事项、
   占位说明与免责声明。
3. 数据随行标注**方法口径**（CAD 实算 / 公开数据集 / 合成图基准 / 离线测试 / 设计校核），
   让评委能追问来源，而不暴露工程台账。
4. 数值只从 facts.py 读取，不得在页面中手抄。
5. 状态用设计系统统一的标签制度表达（已完成 / 进行中 / 规划中 / 设计目标）。

用法： ./.venv-ppt/bin/python ppt-gen/build_deck.py [产物名]
产物： ppt/out/ATRI-答辩PPT-v7.pptx
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

from design import *  # noqa: F401,F403
from design import (P, R, add_slide, card, hline, joint_chain_h, num_card,
                    page_frame, page_title, picture_cover, picture_fit, rect,
                    status_bar, table, text, vline, MIST, MIST_2)
from animate import add_transition
from diagrams import chapter_page, fsm_diagram, joint_topology, pipeline_strip
from figures import range_bars, stacked_mass, torque_bars, view_triptych
import facts as F

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASSETS = HERE / "assets"
OUT = ROOT / "ppt" / "out"

TOTAL = 35
CH = {
    "sum": ("00", "项目摘要"),
    "hw": ("01", "构型与总体设计"),
    "sw": ("02", "软件系统"),
    "task": ("03", "五项赛务任务"),
    "qa": ("04", "验证体系与工程路线"),
}


# ═══════════════════════════ 版面工具 ═══════════════════════════
def frame(s, ch, n, dark=False, right=None):
    page_frame(s, CH[ch][0], CH[ch][1], n, total=TOTAL, dark=dark,
               right_label=right)


def img(name):
    """素材路径；缺失时返回 None（版面退化为色块，不会崩）。"""
    p = ASSETS / name
    return str(p) if p.exists() else None


def kv(s, x, y, w, items, *, name_w=1.20, gap=0.30, size=9.5,
       bullet=BLUE, line_spacing=1.24):
    """键值条目：名称加粗，内容常规，可折行。"""
    yy = y
    for k, v in items:
        rect(s, x, yy + 0.06, 0.045, 0.045, fill=bullet)
        text(s, x + 0.16, yy - 0.03, w - 0.16, 0.24,
             [P([R(k + "　", size, INK, heavy=True), R(v, size, GRAPHITE)],
                line_spacing=line_spacing)])
        yy += gap + 0.16 * max(0, -(-len(k + v) // 46) - 1)
    return yy - y


def note(s, x, y, w, t, size=8.5, color=GRAY, h=0.24):
    text(s, x, y, w, h, [P([R(t, size, color)])])


def source(s, x, w, t, y=None):
    """页脚口径行：写「数据来源」的方法口径，不写仓库路径。"""
    yy = (Y_STATUSBAR - 0.32) if y is None else y
    text(s, x, yy, w, 0.26, [P([R("数据来源：", 8.5, BLUE, heavy=True),
                                R(t, 8.5, GRAY)])])


def plate(s, x, y, w, h, name, *, focus_x=0.5, focus_y=0.5, fill=DARK,
          mode="cover", inset=0.0):
    """图版：先用底色调铺满，再贴渲染图（底色取自渲染图，无矩形接缝）。

    mode="cover" 填满画框（裁切）；mode="fit" 完整放入（不裁切，留同色边）。
    宽幅爆炸图用 fit，否则展开的四肢会被画框切掉。
    """
    rect(s, x, y, w, h, fill=fill)
    path = img(name)
    if not path:
        return
    if mode == "fit":
        picture_fit(s, x + inset, y + inset, w - 2 * inset, h - 2 * inset, path)
    else:
        picture_cover(s, x, y, w, h, path, focus_x=focus_x, focus_y=focus_y)


def framed(s, x, y, w, h, name, caption=None, sub=None, dark=False):
    """浅色页上的图片框：白底 + 细描边 + 图注（图注区高度按行数预留，不越框）。"""
    rect(s, x, y, w, h, fill=WHITE if not dark else MIST, line=LINE, line_w=0.75)
    path = img(name)
    pad = 0.10
    cap_h = (0.50 if sub else 0.30) if caption else 0.0
    if path:
        picture_fit(s, x + pad, y + pad, w - 2 * pad, h - 2 * pad - cap_h, path)
    if caption:
        paras = [P([R(caption, 8.5, INK, heavy=True)], line_spacing=1.20)]
        if sub:
            paras.append(P([R(sub, 8, GRAY)], line_spacing=1.20))
        text(s, x + 0.16, y + h - cap_h + 0.06, w - 0.32, cap_h - 0.06, paras)


def bullets_col(s, x, y, w, items, *, gap=0.40, size=9.5, color=GREEN,
                line_spacing=1.26, dot=0.05, per_line=44):
    """圆点条目列：行距按折行数自适应，避免文字压到下一行。"""
    yy = y
    for t in items:
        rect(s, x + 0.02, yy + 0.06, dot, dot, fill=color)
        lines = max(1, -(-len(t) // per_line))
        text(s, x + 0.20, yy - 0.03, w - 0.24, 0.30 * lines,
             [P([R(t, size, GRAPHITE)], line_spacing=line_spacing)])
        yy += gap + 0.20 * (lines - 1)
    return yy - y


# ═══════════════════════════ 00 项目摘要 ═══════════════════════════
def p01(prs):
    """封面：项目定位 + 三行核心特征，右侧整机渲染图版。"""
    from design import DARK, DARK_TEXT, DARK_TXT
    s = add_slide(prs, DARK)
    rect(s, 0, 0, 7.42, SLIDE_H, fill=DARK_TEXT)
    X = CONTENT_X
    text(s, X, 0.72, 7.4, 0.26,
         [P([R("中国国际大学生创新大赛（2026）", 10.5, BLUE_300, heavy=True),
             R("　陕西赛区特色专项 · 人形机器人专项 · 小人形组", 10.5, BLUE_300)])])
    text(s, X, 1.26, 7.4, 0.96,
         [P([R("A.T.R.I.", 50, WHITE, heavy=True, spc=1.5)], line_spacing=1.0)])
    text(s, X, 2.28, 7.4, 0.44,
         [P([R("桌面自主人形智能", 26, WHITE, heavy=True)])])
    text(s, X, 2.80, 7.4, 0.26,
         [P([R("AUTONOMOUS TABLETOP ROBOTIC INTELLIGENCE", 9.5, BLUE_300, spc=0.8)])])
    rect(s, X, 3.18, 0.72, 0.05, fill=ORANGE)
    text(s, X, 3.40, 7.2, 0.34,
         [P([R("20 自由度高紧凑构型设计与全离线具身智能任务栈", 15, WHITE)])])
    text(s, X, 3.86, 7.2, 0.30,
         [P([R(f"{F.DOF} DOF", 15, ORANGE, heavy=True),
             R("　·　", 11, BLUE_300),
             R(f"{F.ENVELOPE_MM[0]:g} mm 站高", 15, ORANGE, heavy=True),
             R("　·　", 11, BLUE_300),
             R(f"{F.TESTS_MAIN}+{F.TESTS_WEBOTS} 项离线测试", 15, ORANGE, heavy=True)])])
    yy = 4.52
    for k, v in [
        ("高紧凑构型", f"20-DOF 仿人拓扑 · 桌面级尺度 · 铝夹层承力"),
        ("全离线任务栈", "端侧感知与任务卡状态机调度 · 零云端依赖"),
        ("高保真验证", "全链路 CAD 数字样机 + 离线测试矩阵"),
    ]:
        text(s, X, yy, 1.55, 0.26, [P([R(k, 10.5, BLUE_300, heavy=True)])])
        text(s, X + 1.62, yy, 4.80, 0.44,
             [P([R(v, 10, WHITE)], line_spacing=1.26)])
        yy += 0.52
    text(s, X, 6.30, 7.2, 0.26,
         [P([R("项目团队　", 9.5, BLUE_300),
             R(" · ".join(n for n, _ in F.TEAM), 9.5, WHITE)])])
    text(s, X, 6.58, 7.2, 0.26,
         [P([R("指导教师　", 9.5, BLUE_300), R(F.ADVISORS, 9.5, WHITE)])])
    plate(s, 7.42, 0, SLIDE_W - 7.42, SLIDE_H, F.RENDER_HERO, mode="fit")
    text(s, 7.82, 6.72, 5.20, 0.30,
         [P([R("图 0-1　整机正视图（CAD 光追渲染，整机零位）", 9, DARK_TXT)])])


def p02(prs):
    """项目定位与系统全貌。"""
    s = add_slide(prs, PAPER)
    frame(s, "sum", 2, right="项目定位")
    page_title(s, "项目定位与系统全貌",
               lead="项目以「数字样机先行、物理样机跟进」的方式推进：构型、结构与全离线算法栈"
                    "已在 CAD 与离线环境中闭环，整机进入试制与标定阶段。")
    cards = [
        (f"{F.DOF}", "DOF", "仿人拓扑：头 2 · 躯干 2 · 臂 8 · 腿 8"),
        (f"{F.ENVELOPE_MM[0]:g}", "mm", "整机站高，桌面级尺度，CAD 实算包络"),
        (f"{F.PART_COUNT}", "件", "同源装配体零件数，几何零相交"),
        (f"{F.TESTS_MAIN}+{F.TESTS_WEBOTS}", "项", "可复现离线测试：软件主包 + 运动学"),
    ]
    w = (CONTENT_W - 0.45) / 4
    for i, (n, u, c) in enumerate(cards):
        num_card(s, CONTENT_X + i * (w + 0.15), Y_BODY + 0.10, w, 1.36, n, u, c,
                 color=INK, num_size=26, unit_size=13, caption_size=8.5)
    y = Y_BODY + 1.62
    colw = (CONTENT_W - 0.50) / 2
    rect(s, CONTENT_X, y, colw, 0.30, fill=BLUE)
    text(s, CONTENT_X + 0.14, y, colw - 0.28, 0.30,
         [P([R("系统构成", 10.5, WHITE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
    rect(s, CONTENT_X + colw + 0.50, y, colw, 0.30, fill=GREEN)
    text(s, CONTENT_X + colw + 0.64, y, colw - 0.28, 0.30,
         [P([R("研发路线", 10.5, WHITE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
    left = [
        "构型：20 自由度仿人拓扑，关节表与固件配置同源，越界输入一律拒绝。",
        "结构：6061 铝夹层承力 + 2.4 mm PETG 外壳，髋与腰改为前后双侧支承。",
        "电子：20 只总线舵机单线级联，单包 3S 电源，主控板与单目相机进主装配。",
        "软件：任务卡 + 状态机 + 技能插件，纯标准库运行时，换场景只换配置。",
    ]
    right = [
        "阶段一（已达成）数字化设计与算法验证：构型、结构、算法栈与验收大纲。",
        "阶段二（进行中）物理样机试制与联合调试：备料、装配、台架实测与标定。",
        "阶段三（规划中）赛务场景实测与性能闭环：现场感知、动态步态与续航优化。",
    ]
    bullets_col(s, CONTENT_X, y + 0.46, colw, left, color=BLUE, gap=0.50)
    bullets_col(s, CONTENT_X + colw + 0.50, y + 0.46, colw, right, color=GREEN,
                gap=0.62)
    source(s, CONTENT_X, CONTENT_W, "CAD 装配体实算 + 离线测试本机复跑结果")
    status_bar(s, ["done", "doing"])


def p03(prs):
    """立项依据：需求侧的三项量化约束。"""
    s = add_slide(prs, PAPER)
    frame(s, "sum", 3, right="立项依据")
    page_title(s, "立项依据：三项可量化的教学与赛务约束",
               lead="约束分别来自设备采购预算、代码组织方式与赛场网络条件，均可给出量化口径。")
    blocks = [
        ("约束一　设备采购预算", ORANGE, [
            ("现状", f"同类教育型小型双足套件单台 {F.COST_RIVAL}；按 20 台配置，班级预算 "
                     f"{F.COST_CLASS_RIVAL}。"),
            ("影响", "多数实验室只能配置 1–2 台用于演示，学生无法逐一完成硬件调试。"),
            ("设计指标", [f"全口径 {F.COST_CLOSE}–{F.COST_RETAIL} 元/台。",
                          f"20 台班级投入 {F.COST_CLASS_20}，约为同级平台的三分之一。"]),
        ]),
        ("约束二　代码组织方式", BLUE, [
            ("现状", "视觉、循迹、抓取与步态分属不同工程，主循环与状态管理各自实现。"),
            ("影响", "学生拿到的是互不兼容的独立脚本，难以完成系统级任务调度训练。"),
            ("设计指标", "统一任务卡规范与状态机调度，技能以插件方式接入；换任务只改配置数据。"),
        ]),
        ("约束三　赛场网络条件", GREEN, [
            ("现状", "感知与语音依赖公网接口时，现场限速或中断会使整条链路超时。"),
            ("影响", "任务执行不确定；实验采集的人脸与图像数据存在外传合规风险。"),
            ("设计指标", "感知、语音与调度全部板载运行，运行期网络出站次数为 0。"),
        ]),
    ]
    w = (CONTENT_W - 0.50) / 3
    for i, (title, col, rows) in enumerate(blocks):
        x = CONTENT_X + i * (w + 0.25)
        card(s, x, Y_BODY, w, 3.52, fill=WHITE)
        rect(s, x, Y_BODY, w, 0.045, fill=col)
        text(s, x + 0.22, Y_BODY + 0.20, w - 0.44, 0.30,
             [P([R(title, 12.5, INK, heavy=True)])])
        hline(s, x + 0.22, Y_BODY + 0.62, w - 0.44, color=LINE, width=0.75)
        yy = Y_BODY + 0.76
        for k, v in rows:
            text(s, x + 0.22, yy, w - 0.44, 0.24,
                 [P([R(k, 9.5, col, heavy=True)])])
            paras = [P([R(t, 9.5, GRAPHITE)], line_spacing=1.28)
                     for t in (v if isinstance(v, (list, tuple)) else [v])]
            text(s, x + 0.22, yy + 0.24, w - 0.44, 0.74, paras)
            yy += 0.92
    source(s, CONTENT_X, CONTENT_W, F.COST_SOURCE)
    status_bar(s, ["design"])


# ═══════════════════════════ 01 构型与总体设计 ═══════════════════════════
def p04(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "01", "构型与总体设计",
                 "自由度分配、包络、结构体系、质量账、动力学校核与成本口径。")


def p05(prs):
    s = add_slide(prs, PAPER)
    frame(s, "hw", 5)
    page_title(s, "整机配置与关键设计指标一览",
               lead="下列数值为 CAD 装配体实算值、采购件标称值或设计校核值，口径随行标注。")
    rows = [
        ["自由度", f"{F.DOF}（{F.DOF_BREAKDOWN}）", "设计值",
         "关节表与固件配置同源，越界输入一律拒绝"],
        ["整机包络", f"{F.ENVELOPE_MM[0]:g} × {F.ENVELOPE_MM[1]:g} × {F.ENVELOPE_MM[2]:g} mm",
         "CAD 实算", "高 × 宽 × 深；赛题上限 600 × 300 × 300"],
        ["结构体系", "6061 铝夹层 + 2.4 mm PETG", "制造方案",
         "激光平板 + 标准角铝，髋与腰双侧支承"],
        ["装配体", f"{F.PART_COUNT} 件同源装配快照", "CAD 实装", "几何零相交，抽样构型全通过"],
        ["质量账", f"已计 {F.MASS_ACCOUNTED_G} g / 目标 {F.MASS_TARGET_G} g", "逐项建账",
         "八类分项累加，采购件按标称质量"],
        ["执行器", "20 × STS3215-C018（12 V）", "采购件",
         f"连续额定 {F.TORQUE_RATED_NM} N·m，单线级联"],
        ["供电", F.BATTERY_PACK, "采购件", "支持扩展坞与外部直流供电"],
        ["控制软件", f"Python {F.PYTHON} 标准库 · {F.DOF} 关节", "离线测试",
         "主包零第三方依赖，无硬件可全流程演练"],
    ]
    table(s, CONTENT_X, Y_BODY, CONTENT_W,
          ["项目", "设计值", "口径", "说明"], rows,
          col_w=[1.30, 3.55, 1.35, 5.47], row_h=0.42, head_h=0.34,
          size=9.5, head_size=9.5)
    source(s, CONTENT_X, CONTENT_W,
           "CAD 装配体实算 · 采购件厂家标称 · 关节表与限位取自同一数据源")
    status_bar(s, ["done", "design"])


def p06(prs):
    s = add_slide(prs, PAPER)
    frame(s, "hw", 6)
    page_title(s, "自由度分配与赛务检录条款的对应关系",
               lead="关节命名、旋转轴向与角度限位取自同一数据源，构型按条款的最严解释设计。")
    rows = [[name, str(n), detail] for name, n, detail in F.JOINT_LIST]
    rows.append(["合计", str(F.DOF), "全机统一总线舵机；赛题下限为 18 个自由度"])
    table(s, CONTENT_X, Y_BODY, 7.10,
          ["分区", "数量", "关节构成与角度限位"], rows,
          col_w=[0.90, 0.70, 5.50], row_h=0.54, head_h=0.34, size=9, head_size=9.5)
    bx = CONTENT_X + 7.50
    pw = CONTENT_W - 7.50
    rect(s, bx, Y_BODY, pw, 2.96, fill=MIST)
    text(s, bx + 0.20, Y_BODY + 0.12, pw - 0.40, 0.26,
         [P([R("图 1-1　关节运动学拓扑（自绘矢量图）", 9, INK, heavy=True)])])
    joint_topology(s, cx=bx + 0.92, top=Y_BODY + 0.44, h=2.20, labels=False)
    for i, (grp, detail) in enumerate([
        ("双臂 8", "每臂 肩 2 · 肘 1 · 夹爪 1"),
        ("双腿 8", "每腿 髋 2 · 膝 1 · 踝 1"),
        ("躯干 2", "横滚 · 俯仰"),
        ("头部 2", "偏航 · 俯仰"),
    ]):
        gy = Y_BODY + 0.50 + i * 0.54
        rect(s, bx + 1.74, gy + 0.05, 0.05, 0.05,
             fill={"双臂 8": "3D7EAE", "双腿 8": "6FA3CB",
                   "躯干 2": "1264A3", "头部 2": "0A2540"}[grp])
        text(s, bx + 1.90, gy - 0.02, pw - 2.12, 0.46,
             [P([R(grp, 9.5, INK, heavy=True)], line_spacing=1.20),
              P([R(detail, 8, GRAY)], line_spacing=1.20)])
    text(s, bx + 0.20, Y_BODY + 2.72, pw - 0.40, 0.24,
         [P([R("仅表达关节位置与分组，不表达零件形状。", 8.5, GRAY)],
            line_spacing=1.24)])
    y = 5.30
    rect(s, CONTENT_X, y, CONTENT_W, 0.84, fill=WHITE, line=LINE, line_w=0.75)
    items = [
        ("自由度总数", f"≥{F.RULE_TOTAL_MIN}", f"{F.DOF}"),
        ("单腿自由度", f"≥{F.RULE_LEG_MIN}", "4"),
        ("上肢 + 躯干", f"≥{F.RULE_UPPER_TRUNK_MIN}", f"{F.DOF_ARM} + {F.DOF_TRUNK} = 10"),
        ("供电电压", f"≥{F.RULE_VOLT_MIN}", "11.1 V"),
    ]
    cw = CONTENT_W / 4
    for i, (name, rule, val) in enumerate(items):
        cx = CONTENT_X + i * cw
        if i:
            vline(s, cx, y + 0.10, 0.42, color=LINE, width=0.75)
        text(s, cx + 0.24, y + 0.08, cw - 0.40, 0.22,
             [P([R(name, 9, GRAY)])])
        text(s, cx + 0.24, y + 0.30, cw - 0.40, 0.30,
             [P([R(f"条款 {rule}　本项目 ", 9.5, GRAPHITE),
                 R(val, 12, ORANGE, heavy=True)])])
    text(s, CONTENT_X + 0.24, y + 0.58, CONTENT_W - 0.48, 0.24,
         [P([R("构型按「头部与夹爪均不计入上肢躯干」的最严解释设计，即使按该口径统计仍满足下限。",
              8.5, GRAY)])])
    source(s, CONTENT_X, CONTENT_W, "关节表与限位取自同一配置源；条款取值见赛项细则")
    status_bar(s, ["done", "design"])


def p07(prs):
    s = add_slide(prs, PAPER)
    frame(s, "hw", 7)
    page_title(s, "整机包络与赛题限值的余量分配",
               lead="包络顺序统一为高 × 宽 × 深，量取对象为整机零位下的实际几何，含全部外挂件与紧固件。")
    rows = [
        ("整机高度", F.ENVELOPE_MM[0], F.RULE_ENVELOPE_MM[0], BLUE,
         f"余 +{F.ENVELOPE_MARGIN_MM[0]:g} mm；自头顶最高点至足底支撑面"),
        ("整机宽度", F.ENVELOPE_MM[1], F.RULE_ENVELOPE_MM[1], BLUE,
         f"余 +{F.ENVELOPE_MARGIN_MM[1]:g} mm；髋部双侧支承后的最大横向尺寸"),
        ("整机厚度", F.ENVELOPE_MM[2], F.RULE_ENVELOPE_MM[2], ORANGE,
         f"余 +{F.ENVELOPE_MARGIN_MM[2]:g} mm；含背挂电子件与足板前端"),
    ]
    range_bars(s, CONTENT_X, Y_BODY + 0.24, 8.20, rows, label_w=1.20,
               bar_h=0.30, gap=0.40, unit="mm")
    framed(s, CONTENT_X + 8.60, Y_BODY - 0.02, 2.30, 3.30, F.RENDER_FRONT,
           "图 1-2　整机正视图（CAD 光追渲染）",
           "渲染用于表达结构与接口关系，尺寸以装配体实算值为准")
    rect(s, CONTENT_X, Y_BODY + 2.34, 8.20, 1.62, fill=MIST)
    text(s, CONTENT_X + 0.20, Y_BODY + 2.46, 7.80, 0.28,
         [P([R("测量口径", 11.5, INK, heavy=True)])])
    kv(s, CONTENT_X + 0.20, Y_BODY + 2.82, 7.80, [
        ("包络定义", "CAD 装配体的轴对齐包围盒，含全部外挂件与紧固件"),
        ("量取姿态", "整机零位（关节归零），与渲染图姿态一致"),
        ("内部布局门禁", "宽度与高度方向设内部限值，自动化脚本逐项校验"),
    ], name_w=1.32, gap=0.36, size=9)
    source(s, CONTENT_X, CONTENT_W, F.ENVELOPE_SOURCE)
    status_bar(s, ["done", "design"])


def p08(prs):
    s = add_slide(prs, PAPER)
    frame(s, "hw", 8)
    page_title(s, "结构体系：铝夹层承力与双侧支承",
               lead="承力件采用 6061 铝夹层，外壳采用 2.4 mm PETG；髋与腰的侧摆关节改为前后双侧支承，"
                    "受力路径连续、装配可维护。")
    card(s, CONTENT_X, Y_BODY - 0.04, 7.30, 3.34, fill=WHITE)
    yy = Y_BODY + 0.14
    for k, v in F.STRUCTURE_POINTS:
        text(s, CONTENT_X + 0.24, yy, 1.30, 0.26,
             [P([R(k, 10.5, INK, heavy=True)])])
        text(s, CONTENT_X + 1.62, yy - 0.02, 5.44, 0.44,
             [P([R(v, 9.5, GRAPHITE)], line_spacing=1.26)])
        yy += 0.54
    framed(s, CONTENT_X + 7.60, Y_BODY - 0.04, CONTENT_W - 7.60, 3.34,
           F.RENDER_DETAIL_PELVIS, "图 1-3　髋腰双侧支撑（CAD 渲染）")
    rect(s, CONTENT_X, Y_BODY + 3.46, CONTENT_W, 0.66, fill=MIST)
    text(s, CONTENT_X + 0.24, Y_BODY + 3.56, CONTENT_W - 0.48, 0.48,
         [P([R("装配可实现性：", 9, INK, heavy=True),
             R("骨盆输出转接件按中框碰撞域重画，左右前转接件在零位均无干涉；"
               "足板加高使踝关节笼离地，垫面为全机最低点。", 9, GRAPHITE)],
            line_spacing=1.26)])
    source(s, CONTENT_X, CONTENT_W,
           "同源装配体几何审查 + 抽样构型扫描；材料与工艺为制造方案口径")
    status_bar(s, ["done", "design"])


def p09(prs):
    s = add_slide(prs, PAPER)
    frame(s, "hw", 9)
    page_title(s, "质量账与轻量化路径",
               lead="整机质量按八个分项逐项建账，几何件按实体体积与材料密度换算，采购件按厂家标称质量计。")
    parts = [
        ("铝合金件", F.MASS_ROWS[0][2], BLUE),
        ("PETG 外壳", F.MASS_ROWS[1][2], "3D7EAE"),
        ("TPU 件", F.MASS_ROWS[2][2], "6FA3CB"),
        ("紧固件", F.MASS_ROWS[3][2], MIST_2),
        ("隔柱", F.MASS_ROWS[4][2], BLUE_300),
        ("舵机 ×20", F.MASS_ROWS[5][2], INK),
        ("电池包", F.MASS_ROWS[6][2], ORANGE),
        ("主控板", F.MASS_ROWS[7][2], "C7D6E6"),
    ]
    stacked_mass(s, CONTENT_X, Y_BODY + 0.84, 8.10, 0.58, parts,
                 total_label=f"已计质量 ≈ {F.MASS_ACCOUNTED_G} g（设计目标 {F.MASS_TARGET_G} g）",
                 vmax=2600)
    bx = CONTENT_X + 8.72
    num_card(s, bx, Y_BODY + 0.20, CONTENT_W - 8.72, 1.30,
             f"{F.MASS_ACCOUNTED_G}", "克", "八类分项累加：铝合金 525.6 + 舵机 1100.0 为主要项",
             color=INK, num_size=30, caption_size=8.5)
    num_card(s, bx, Y_BODY + 1.62, CONTENT_W - 8.72, 1.30,
             f"{F.MASS_TARGET_G}", "克", "轻量化设计目标；按分项迭代收敛，不靠单一材料替换",
             color=INK, num_size=26, caption_size=8.5)
    y = Y_BODY + 3.02
    text(s, CONTENT_X, y, CONTENT_W, 0.28,
         [P([R("轻量化路径：", 10.5, INK, heavy=True),
             R("足板开窗与局部拓扑减材、铝夹层厚度分区、紧固件规格统一、"
               "外壳按承力与非承力分件选材。", 10, GRAPHITE)])])
    note(s, CONTENT_X, y + 0.36, CONTENT_W,
         "质量账的意义在于把「整机多重」从估算变成一个可追责的清单：每个分项都有数量、"
         "材料或标称质量与换算依据，任一项变化都能立刻反映到整机账上。", 9.5, GRAY)
    source(s, CONTENT_X, CONTENT_W, F.MASS_SOURCE)
    status_bar(s, ["doing", "design"])


def p10(prs):
    s = add_slide(prs, PAPER)
    frame(s, "hw", 10)
    page_title(s, "下肢动力学校核与减载策略",
               lead="校核判据取执行器厂家连续额定扭矩，依据是长时带载工况；瞬态堵转扭矩不作为达标依据。")
    torque_bars(s, CONTENT_X, Y_BODY + 0.44, 7.30,
                [("行走工况（k=1.4）", F.TORQUE_WALK_PCT, ""),
                 ("极限保持（k=2）", F.TORQUE_HOLD_PCT, ""),
                 ("肩滚转（100 g 载荷）", F.ARM_LOAD_TABLE[0][2], ""),
                 ("肩俯仰（100 g 载荷）", F.ARM_LOAD_TABLE[1][2], ""),
                 ("肘俯仰（100 g 载荷）", F.ARM_LOAD_TABLE[2][2], "")],
                rated=100.0, max_pct=130.0, label_w=1.72, bar_h=0.26, gap=0.14)
    bx = CONTENT_X + 7.66
    rect(s, bx, Y_BODY - 0.06, CONTENT_W - 7.66, 3.46, fill=MIST)
    text(s, bx + 0.20, Y_BODY + 0.10, CONTENT_W - 8.06, 0.28,
         [P([R("判据与减载策略", 12, INK, heavy=True)])])
    kv(s, bx + 0.20, Y_BODY + 0.50, CONTENT_W - 8.06, [
        ("校核判据", f"厂家连续额定 {F.TORQUE_RATED_NM} N·m；堵转 {F.TORQUE_STALL_NM} N·m 仅作峰值参考"),
        ("行走工况", f"动载系数 k=1.4 下峰值 {F.TORQUE_WALK_NM} N·m，利用率 {F.TORQUE_WALK_PCT}%"),
        ("极限工况", f"k=2 保持工况下踝关节为载荷峰值 {F.TORQUE_HOLD_NM} N·m"),
        ("峰值点", "踝俯仰与膝俯仰构成下肢应力集中区"),
        ("减载机制", "弹性助力 + 步态支撑相相位优化 + 降额运行策略"),
        ("台架验证", "执行器在 0.8 / 1.0 / 1.2 N·m 循环 30 min，壳温 ≤65 ℃"),
    ], name_w=1.20, gap=0.44, size=9)
    source(s, CONTENT_X, CONTENT_W, F.TORQUE_SOURCE)
    status_bar(s, ["design", "doing"])


def p11(prs):
    s = add_slide(prs, PAPER)
    frame(s, "hw", 11)
    page_title(s, "功率预算与续航分级方案",
               lead="按「电流与输出扭矩成正比」的线性功耗模型建立 20 轴全周期电流预测，"
                    "据此给出两种作业模式下的电源配置。")
    cards = [
        (f"{F.BUS_VOLTAGE.split()[1]}", "V", "总线电压：3S 锂电直供"),
        ("24.4", "Wh", "板载单包能量（2200 mAh / 169 g）"),
        (f"{F.REQUIRED_AH}", "Ah", f"{F.MISSION_MIN} min 连续作业的容量需求"),
        (f"{F.MISSION_MIN}", "min", "赛务连续作业时长要求"),
    ]
    w = (CONTENT_W - 0.45) / 4
    for i, (n, u, c) in enumerate(cards):
        num_card(s, CONTENT_X + i * (w + 0.15), Y_BODY, w, 1.42, n, u, c,
                 color=ORANGE if i >= 2 else INK, num_size=27, caption_size=8.5)
    y = Y_BODY + 1.62
    colw = (CONTENT_W - 0.44) / 2
    for i, (title, col, rows) in enumerate([
        ("标准调试模式", BLUE, [
            "板载单包 3S 2200 mAh 直接进主装配，含托盘与绑带。",
            "面向日常调试、单项任务验证与短时高机动演示。",
            "能量密度优先：整机质量账与踝关节余量同时受益。",
        ]),
        ("长航时 / 教学模式", GREEN, [
            f"外接直流扩展坞或扩展电池包，容量需求约 {F.REQUIRED_AH} Ah / {F.REQUIRED_WH} Wh。",
            "扩展电源独立熔断并做反向电流隔离，不与主包直接并联。",
            "面向 30 min 连续作业与课堂教学的整班轮换使用。",
        ]),
    ]):
        x = CONTENT_X + i * (colw + 0.44)
        rect(s, x, y, colw, 0.30, fill=col)
        text(s, x + 0.14, y, colw - 0.28, 0.30,
             [P([R(title, 10.5, WHITE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        bullets_col(s, x, y + 0.42, colw, rows, color=col, gap=0.50, size=9.5)
    note(s, CONTENT_X, y + 2.02, CONTENT_W,
         "能效杠杆：降额运行、步态周期优化、空闲关节失能。三条杠杆同时改善续航与关节热负荷，"
         "优先于单纯增大电池容量——后者会反过来加重下肢扭矩需求。", 9, GRAPHITE)
    source(s, CONTENT_X, CONTENT_W, F.POWER_SOURCE)
    status_bar(s, ["design", "plan"])


def p12(prs):
    s = add_slide(prs, PAPER)
    frame(s, "hw", 12)
    page_title(s, "成本核算与采购口径",
               lead="按 BOM 明细核算，并区分「全口径」与「集采口径」两种口径分别列示，不合并引用。")
    import math
    lo_e, hi_e = 3.35, 4.25
    bx, bw = CONTENT_X + 2.95, 5.60

    def px_of(v):
        return bx + (math.log10(v) - lo_e) / (hi_e - lo_e) * bw

    y = Y_RULE + 0.46
    for name, lo, hi, col, nt in [
        ("同级教育套件", 6000, 12000, MIST_2, f"单台 {F.COST_RIVAL}；20 台为 {F.COST_CLASS_RIVAL}"),
        ("本方案 · 全口径", 3137, 3961, BLUE_300, "含备用执行器与平衡充电器，逐项询价"),
        ("本方案 · 集采口径", 3137, 3137, ORANGE, "20 只执行器集采价下的紧凑估算"),
    ]:
        text(s, CONTENT_X, y, 2.80, 0.30,
             [P([R(name, 10.5, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        rect(s, bx, y + 0.03, bw, 0.24, fill=MIST)
        rect(s, px_of(lo), y + 0.03, max(px_of(hi) - px_of(lo), 0.07), 0.24, fill=col)
        text(s, bx + bw + 0.16, y, 2.30, 0.30,
             [P([R(f"¥{lo:,}" + (f"–{hi:,}" if hi != lo else ""), 10, GRAPHITE,
                  heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        note(s, CONTENT_X, y + 0.32, 7.10, nt)
        y += 0.80
    hline(s, bx, y - 0.16, bw, color=LINE, width=0.75)
    for e, lab in ((3.5, "¥3 000"), (3.7, "¥5 000"), (3.9, "¥8 000"),
                   (4.1, "¥12 000")):
        gx = px_of(10 ** e)
        vline(s, gx, y - 0.16, 0.08, color=LINE, width=0.75)
        text(s, gx - 0.55, y - 0.08, 1.10, 0.22,
             [P([R(lab, 8, GRAY)], align=PP_ALIGN.CENTER)])
    note(s, CONTENT_X, y + 0.20, CONTENT_W,
         "价格轴为对数刻度；金额取自 BOM 明细与厂家询价区间。", 9, GRAY)
    rect(s, CONTENT_X, y + 0.60, CONTENT_W, 0.94, fill=MIST)
    text(s, CONTENT_X + 0.24, y + 0.74, CONTENT_W - 0.48, 0.66,
         [P([R("教学价值：", 9.5, BLUE, heavy=True),
             R(f"按 20 台规模，班级投入 {F.COST_CLASS_20}，为同级平台 "
               f"{F.COST_CLASS_RIVAL} 的三分之一左右。差额来自构型决策与统一执行器平台，"
               "使每名学生可以独立占用一台设备完成全流程实践。", 9.5, GRAPHITE)],
            line_spacing=1.30)])
    source(s, CONTENT_X, CONTENT_W, F.COST_SOURCE)
    status_bar(s, ["design"])


def p13(prs):
    """图版：整机外观与总成。"""
    from design import DARK, DARK_TEXT, DARK_TXT
    s = add_slide(prs, DARK)
    rect(s, 0, 0, 6.30, SLIDE_H, fill=DARK_TEXT)
    X = CONTENT_X
    text(s, X, 0.66, 5.4, 0.26,
         [P([R("整机外观与结构总成", 11, BLUE_300, heavy=True),
             R("　CAD 光追渲染（整机零位）", 11, BLUE_300)])])
    text(s, X, 1.02, 5.4, 0.52,
         [P([R("整机外形与技术状态", 26, WHITE, heavy=True)], line_spacing=1.0)])
    rect(s, X, 1.66, 0.72, 0.05, fill=ORANGE)
    plate(s, 6.30, 0, SLIDE_W - 6.30, SLIDE_H, F.RENDER_ISO, mode="fit")
    yy = 2.06
    for k, v in [
        ("构型", f"{F.DOF} 自由度：头 2 · 躯干 2 · 臂 8 · 腿 8"),
        ("结构", "6061 铝夹层承力，2.4 mm PETG 哑光白外壳"),
        ("执行器", "20 只总线舵机单线级联，输出面统一接口"),
        ("包络", f"{F.ENVELOPE_MM[0]:g} × {F.ENVELOPE_MM[1]:g} × {F.ENVELOPE_MM[2]:g} mm（高×宽×深）"),
        ("质量", f"已计 {F.MASS_ACCOUNTED_G} g，目标 {F.MASS_TARGET_G} g"),
        ("状态", "设计冻结；结构件处于备料与试制阶段"),
    ]:
        text(s, X, yy, 1.50, 0.26, [P([R(k, 10, BLUE_300, heavy=True)])])
        text(s, X + 1.60, yy, 3.70, 0.44,
             [P([R(v, 10, WHITE)], line_spacing=1.24)])
        yy += 0.54
    hline(s, X, 5.86, 5.44, color=BLUE, width=0.75)
    text(s, X, 6.02, 5.44, 0.56,
         [P([R("图 1-4　整机等轴测视图（CAD 光追渲染）", 9, BLUE_300)],
            line_spacing=1.24),
          P([R("渲染用于表达结构与接口关系，尺寸以装配体实算值为准。", 8.5, BLUE_300)])])


def p14(prs):
    """图版：爆炸视图与零件级构成。"""
    from design import DARK, DARK_TEXT, DARK_TXT
    s = add_slide(prs, DARK)
    rect(s, 0, 0, 5.90, SLIDE_H, fill=DARK_TEXT)
    text(s, CONTENT_X, 0.66, 5.0, 0.30,
         [P([R("结构与装配总成", 11, BLUE_300, heavy=True),
             R("　爆炸视图 · 零件级分解", 11, BLUE_300)])])
    text(s, CONTENT_X, 1.04, 5.0, 0.56,
         [P([R("整机零件构成与装配关系", 26, WHITE, heavy=True)], line_spacing=1.0)])
    rect(s, CONTENT_X, 1.72, 0.72, 0.05, fill=ORANGE)
    plate(s, 5.90, 0, SLIDE_W - 5.90, SLIDE_H, F.RENDER_EXPLODED, mode="fit")
    yy = 2.16
    for k, v in [
        ("零件级构成", f"同源装配快照 {F.PART_COUNT} 件：铝合金 283 · PETG 8 · TPU 6 · 紧固件 444 · 隔柱 14"),
        ("动力与电子", "20 只总线舵机、单包电池、主控板与单目相机进入主装配"),
        ("装配判据", "B-rep 干涉求解零相交，抽样构型扫描全部通过"),
        ("制造输出", "铝件激光下料清单、PETG/TPU 定向 3MF、标准件与角铝模板"),
    ]:
        text(s, CONTENT_X, yy, 1.50, 0.26, [P([R(k, 10, BLUE_300, heavy=True)])])
        text(s, CONTENT_X + 1.60, yy, 3.30, 0.62,
             [P([R(v, 9.5, WHITE)], line_spacing=1.24)])
        yy += 0.70
    hline(s, CONTENT_X, 5.94, 5.04, color=BLUE, width=0.75)
    text(s, CONTENT_X, 6.10, 5.04, 0.60,
         [P([R("图 1-5　爆炸视图（CAD 光追渲染）", 9, BLUE_300)], line_spacing=1.26),
          P([R("用于说明零件级构成与装配顺序，尺寸以装配体实算值为准。", 8.5, BLUE_300)])])


# ═══════════════════════════ 02 软件系统 ═══════════════════════════
def p15(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "02", "软件系统",
                 "分层架构、任务调度、接口契约与感知语音通路。")


def p16(prs):
    s = add_slide(prs, PAPER)
    frame(s, "sw", 16)
    page_title(s, "软件系统的三层结构与层间接口",
               lead="分层依据是职责边界：任务调度、运动生成与总线通信各自独立，层间通过固定接口交互。")
    layers = [
        ("任务层", "cognition", f"通用 Linux 主控 · Python {F.PYTHON}",
         "任务卡解析 · 状态机调度 · 技能插件 · 感知与语音接入", BLUE),
        ("运动层", "cerebellum", "参数化步态与动作库 · 可下沉至 MCU",
         "正弦步态生成 · 关键帧动作回放 · 角度限位钳制", "3D7EAE"),
        ("总线层", "servo bus", f"{F.DOF} 路串行总线，单线级联",
         "统一写角度入口 · 角度与脉冲换算 · 同步写与状态回读", "6FA3CB"),
    ]
    y = Y_BODY + 0.04
    for name, en, env, duty, col in layers:
        rect(s, CONTENT_X, y, 7.30, 0.94, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, CONTENT_X, y, 0.055, 0.94, fill=col)
        text(s, CONTENT_X + 0.26, y + 0.12, 1.70, 0.30,
             [P([R(name, 14, INK, heavy=True)])])
        text(s, CONTENT_X + 0.26, y + 0.50, 2.80, 0.24,
             [P([R(en + " · " + env, 8.5, GRAY)])])
        text(s, CONTENT_X + 3.10, y, 4.06, 0.94,
             [P([R(duty, 9.5, GRAPHITE)], line_spacing=1.28)],
             anchor=MSO_ANCHOR.MIDDLE)
        y += 1.04
    bx = CONTENT_X + 7.70
    rect(s, bx, Y_BODY, CONTENT_W - 7.70, 3.18, fill=MIST)
    text(s, bx + 0.22, Y_BODY + 0.16, CONTENT_W - 8.14, 0.28,
         [P([R("层间接口定义", 12, INK, heavy=True)])])
    kv(s, bx + 0.22, Y_BODY + 0.54, CONTENT_W - 8.14, [
        ("批量写角度", "一次写入多个关节目标角度，入参为字典"),
        ("动作回放", "按标识回放动作库关键帧序列"),
        ("轨迹等待", "等待当前轨迹执行结束后返回"),
        ("感知失败", "技能立即返回失败，不向运动层下发动作"),
        ("限位钳制", "统一在写角度入口实施，子类只需实现底层写入"),
        ("非有限值", "NaN 与 Inf 抛出异常，不静默钳制至限位边界"),
    ], name_w=1.28, gap=0.42, size=9)
    note(s, CONTENT_X, y + 0.16, 7.30,
         "接口契约的意义：上层只依赖契约，不依赖实现——同一套任务卡既能跑在虚拟总线上做离线演练，"
         "也能直接驱动真机总线。", 9, GRAY)
    source(s, CONTENT_X, CONTENT_W, "软件分层与接口定义；离线与真机共用同一契约")
    status_bar(s, ["done"])


def p17(prs):
    s = add_slide(prs, PAPER)
    frame(s, "sw", 17)
    page_title(s, "任务卡驱动的流程调度与异常收敛",
               lead="五项赛务任务的差异以数据形式集中于任务卡；调度器负责流程推进、超时判定与异常终止。")
    rect(s, CONTENT_X, Y_BODY, CONTENT_W, 1.28, fill=MIST)
    pipeline_strip(s, CONTENT_X + 0.26, Y_BODY + 0.14, CONTENT_W - 0.52,
                   ["读取任务卡", "校验技能与超时", "STANDBY", "ENTERING",
                    "EXECUTING", "FEEDBACK", "DONE"], h=0.42, size=10)
    text(s, CONTENT_X + 0.26, Y_BODY + 0.62, CONTENT_W - 0.52, 0.56,
         [P([R("感知丢失、参数越界或通信超时均单向收敛至安全挂起，杜绝执行器顶死风险；"
               "状态跳变全程记录，可用于线下复盘。", 9.5, GRAPHITE)],
            line_spacing=1.28),
          P([R('任务卡示例　{"skills": ["qr"], "params": {"path": ["walk:3", "turn:30"]}, '
               '"timeout_s": 90}', 9, GRAY)])])
    y = Y_BODY + 1.52
    fsm_diagram(s, CONTENT_X, y, 7.30, 2.30)
    bx = CONTENT_X + 7.70
    text(s, bx, y - 0.04, CONTENT_W - 7.70, 0.28,
         [P([R("五项任务卡", 12, INK, heavy=True)])])
    yy = y + 0.36
    for tid, name, key in [
        ("T-01", "人脸识别", 'skills=["face"] · 60 s'),
        ("T-02", "二维码循迹", 'skills=["qr"] · 路径 JSON'),
        ("T-03", "物品搬运", 'skills=["carry"] · 色块与物距'),
        ("T-04", "体育运动", 'skills=["kick"] · 死区与上限'),
        ("T-05", "娱乐休闲", 'skills=["dance"] · 关键词与节数'),
    ]:
        rect(s, bx, yy, CONTENT_W - 7.70, 0.40, fill=WHITE, line=LINE, line_w=0.75)
        text(s, bx + 0.14, yy, 0.62, 0.40,
             [P([R(tid, 9.5, BLUE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, bx + 0.82, yy, 1.22, 0.40,
             [P([R(name, 9.5, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, bx + 2.06, yy, CONTENT_W - 9.88, 0.40,
             [P([R(key, 8.5, GRAY)], align=PP_ALIGN.RIGHT)],
             anchor=MSO_ANCHOR.MIDDLE)
        yy += 0.48
    source(s, CONTENT_X, CONTENT_W,
           "五项任务的完整流程在离线环境中逐条走通，流程通过率 5/5")
    status_bar(s, ["done"])


def p18(prs):
    s = add_slide(prs, PAPER)
    frame(s, "sw", 18)
    page_title(s, "技能接口契约与失效防护设计",
               lead="下列条款用于防止技能在感知失败时继续下发动作，每一条都由单元测试锁定。")
    rows = [
        ["感知结果类型校验", "found 字段必须为原生布尔值，字符串 \"False\" 在 Python 中为真值",
         "非布尔值抛出异常", "类型校验用例"],
        ["目标丢失即终止", "技能执行前核验感知结果，未检出目标即判定失败并退出",
         "后续动作零下发", "调度层用例"],
        ["超时处理", "后台定时器仅置位中止标志，不在子线程调用归位流程",
         "归位仅在主线程执行一次", "状态机用例"],
        ["动作去重", "同一状态重复调用导致的指令重复下发",
         "同一次状态转移仅下发一次", "调度层用例"],
        ["非有限值防护", "角度钳制与脉冲换算拒绝 NaN 与 Inf",
         "抛出异常且不发送数据帧，避免满脉冲顶死机械限位", "运动层与总线用例"],
    ]
    table(s, CONTENT_X, Y_BODY, CONTENT_W,
          ["防护项", "失效模式", "防护策略", "验证用例"],
          rows, col_w=[1.70, 4.85, 3.42, 1.70], row_h=0.56, size=9, head_size=9.5)
    y = Y_BODY + 0.34 + 5 * 0.56 + 0.18
    text(s, CONTENT_X, y, CONTENT_W, 0.28,
         [P([R("覆盖范围：", 10, INK, heavy=True),
             R(f"主包 {F.TESTS_MAIN} 项测试覆盖状态机边界、非法输入校验与超时并发处理；"
               "零依赖环境下自动跳过可选依赖用例，不静默降级。", 10, GRAPHITE)])])
    source(s, CONTENT_X, CONTENT_W, "接口契约与单元测试矩阵（本机离线复跑）")
    status_bar(s, ["done"])


def p19(prs):
    s = add_slide(prs, PAPER)
    frame(s, "sw", 19)
    page_title(s, "端侧感知与语音通路",
               lead="三条视觉通路与两级语音通路接入统一感知接口，接口返回结构固定，技能层不依赖具体实现。")
    rows = [
        ["人脸", "检测 + 五点对齐 + 128 维特征 + 余弦相似度检索",
         "识别结果由本地人脸库比对给出；低于阈值时输出拒识", "公开基准集"],
        ["二维码", "三种解码器对照，主用轻量模型",
         "载荷为带版本号的路径 JSON，兼容单动作旧格式", "程序合成畸变场景"],
        ["球与色块", "HSV 阈值分割，输出类别、横向偏移与像素宽度",
         "供踢球与搬运技能使用；未标定时结果标记 uncalibrated", "合成图与一维几何"],
    ]
    table(s, CONTENT_X, Y_BODY, CONTENT_W,
          ["通路", "方法", "输出与使用方式", "评测口径"],
          rows, col_w=[1.05, 4.75, 4.47, 1.40], row_h=0.60, size=9.5, head_size=9.5)
    y = Y_BODY + 0.34 + 3 * 0.60 + 0.20
    colw = (CONTENT_W - 0.44) / 2
    for i, (title, body) in enumerate([
        ("语音合成（本地播报）",
         "按可用性依次探测本地语音引擎，支持环境变量指定；"
         "引擎缺失时明确标注为不可用，不以静默方式跳过播报。"),
        ("语音识别（离线关键词）",
         "离线识别引擎以惰性后端方式接入，白名单外的说法不触发动作；"
         "核心运行时不依赖该库，缺件时返回不可用状态。"),
    ]):
        x = CONTENT_X + i * (colw + 0.44)
        rect(s, x, y, colw, 1.18, fill=WHITE, line=LINE, line_w=0.75)
        text(s, x + 0.22, y + 0.12, colw - 0.44, 0.26,
             [P([R(title, 11.5, INK, heavy=True)])])
        text(s, x + 0.22, y + 0.46, colw - 0.44, 0.66,
             [P([R(body, 9.5, GRAPHITE)], line_spacing=1.30)])
    source(s, CONTENT_X, CONTENT_W, "各通路的评测口径分别见第三章对应页面")
    status_bar(s, ["done", "doing"])


def p20(prs):
    s = add_slide(prs, PAPER)
    frame(s, "sw", 20)
    page_title(s, "高可靠离线运行时与验证矩阵",
               lead="核心运行时不依赖任何第三方库，全部用例在通用 Linux + CPython 3.14 下离线复跑，"
                    "无需硬件连线与图形界面。")
    cards = [
        (f"{F.TESTS_MAIN}", "项", "软件主包单元测试：调度、技能、运动与总线"),
        (f"{F.TESTS_WEBOTS}", "项", "运动学离线测试：关节映射、句柄绑定与角位移"),
        (f"{F.TESTS_V2_CAD}", "项", "装配链路测试：结构件接口、装配与制造输出"),
        ("0", "第三方依赖", "主包仅使用 Python 标准库，端侧部署极简"),
    ]
    w = (CONTENT_W - 0.45) / 4
    for i, (n, u, c) in enumerate(cards):
        num_card(s, CONTENT_X + i * (w + 0.15), Y_BODY, w, 1.36, n, u, c,
                 color=INK if i < 3 else GREEN, num_size=27, caption_size=8.5)
    y = Y_BODY + 1.56
    colw = (CONTENT_W - 0.44) / 2
    rect(s, CONTENT_X, y, colw, 2.10, fill=MIST)
    text(s, CONTENT_X + 0.24, y + 0.14, colw - 0.48, 0.28,
         [P([R("运行时特性", 12, INK, heavy=True)])])
    kv(s, CONTENT_X + 0.24, y + 0.52, colw - 0.48, [
        ("确定性与可复现", "同一输入给出同一轨迹，测试不依赖时间与网络"),
        ("输入全量校验", "关节名、角度范围与非有限值在入口一次性拦截"),
        ("失败熔断", "任一环节失败即终止任务，不产生部分动作"),
        ("安全挂起", "异常态统一收敛，保留完整状态历史供复盘"),
    ], name_w=1.32, gap=0.38, size=9)
    rect(s, CONTENT_X + colw + 0.44, y, colw, 2.10, fill=MIST)
    text(s, CONTENT_X + colw + 0.68, y + 0.14, colw - 0.48, 0.28,
         [P([R("测试矩阵覆盖", 12, INK, heavy=True)])])
    kv(s, CONTENT_X + colw + 0.68, y + 0.52, colw - 0.48, [
        ("关节限位", "100% 关节的越界钳制与非法输入拒绝"),
        ("数值健壮性", "NaN / Inf 过滤与脉冲换算边界"),
        ("并发与超时", "后台计时与主线程归位的并发路径"),
        ("任务卡校验", "字段缺失、类型错误与超时配置"),
    ], name_w=1.32, gap=0.38, size=9)
    source(s, CONTENT_X, CONTENT_W,
           f"本机离线复跑结果：主包 {F.TESTS_MAIN} 项（跳过 {F.TESTS_MAIN_SKIP} 项可选依赖）、"
           f"运动学 {F.TESTS_WEBOTS} 项、装配链路 {F.TESTS_V2_CAD} 项")
    status_bar(s, ["done"])


# ═══════════════════════════ 03 五项赛务任务 ═══════════════════════════
def p21(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "03", "五项赛务任务",
                 "每项任务给出全链路实现、定量评测结果与物理适配计划。")


def _task(prs, page_no, title, lead, flow, cards, impl, adapt, status, src):
    s = add_slide(prs, PAPER)
    frame(s, "task", page_no)
    page_title(s, title, lead=lead)
    rect(s, CONTENT_X, Y_BODY, CONTENT_W, 0.60, fill=MIST)
    pipeline_strip(s, CONTENT_X + 0.22, Y_BODY + 0.08, CONTENT_W - 0.44,
                   flow, h=0.44, size=9.5)
    y = Y_BODY + 0.72
    w = (CONTENT_W - 0.30 * (len(cards) - 1)) / len(cards)
    for i, (n, u, c) in enumerate(cards):
        num_card(s, CONTENT_X + i * (w + 0.30), y, w, 1.12, n, u, c,
                 color=INK, num_size=23, caption_size=8.5)
    y2 = y + 1.28
    colw = (CONTENT_W - 0.44) / 2
    rect(s, CONTENT_X, y2, colw, 0.28, fill=BLUE)
    text(s, CONTENT_X + 0.14, y2, colw - 0.28, 0.28,
         [P([R("全链路实现", 9.5, WHITE, heavy=True)])],
         anchor=MSO_ANCHOR.MIDDLE)
    rect(s, CONTENT_X + colw + 0.44, y2, colw, 0.28, fill=GREEN)
    text(s, CONTENT_X + colw + 0.58, y2, colw - 0.28, 0.28,
         [P([R("物理适配与标定计划", 9.5, WHITE, heavy=True)])],
         anchor=MSO_ANCHOR.MIDDLE)
    for col, items, dot in ((CONTENT_X, impl, BLUE),
                            (CONTENT_X + colw + 0.44, adapt, GREEN)):
        yy = y2 + 0.36
        for t in items:
            rect(s, col + 0.02, yy + 0.06, 0.05, 0.05, fill=dot)
            text(s, col + 0.20, yy - 0.03, colw - 0.24, 0.40,
                 [P([R(t, 8.5, GRAPHITE)], line_spacing=1.22)])
            yy += 0.22 + 0.145 * max(1, -(-len(t) // 46))
    source(s, CONTENT_X, CONTENT_W, src)
    status_bar(s, status)
    return s


def p22(prs):
    _task(prs, 22,
          "任务一（人脸识别）：全离线识别链路与拒识保护",
          "赛题要求识别指定人脸并播报姓名。本方案实现检测、特征提取、本地库比对与显式拒识的完整链路。",
          ["取帧", "轻量检测器", "五点对齐", "128 维特征", "本地库检索", "播报或拒识"],
          [(f"{F.T01_RANK1_50}%", "rank-1（50 人）", "公开基准集困难协议"),
           (f"{F.T01_EER_PCT}%", "等错误率", f"动态阈值 {F.T01_THRESHOLD}"),
           (f"{F.T01_DETECT_PCT:.0f}%", "检出率", f"传统方法对照 {F.T01_HAAR_PCT:.0f}%")],
          ["检测、五点对齐、128 维特征提取与本地库余弦检索构成完整链路，识别结果带来源标注。",
           f"相似度低于动态阈值 {F.T01_THRESHOLD} 时输出拒识；人脸库为空时对任何输入均给出明确拒识。",
           "识别成功后头部两轴按目标框中心执行开环随动，仅在取得检测框时下发姿态。",
           f"端侧分项计时：检测 {F.T01_DETECT_MS} ms、特征提取 {F.T01_EMBED_MS} ms，支持实时帧率。"],
          ["标定阶段在 0.5 / 1.0 / 1.5 m 三个距离档采集实拍样本，重建现场判定阈值。",
           "结合样机单目相机做畸变矫正与自动曝光补偿，覆盖侧脸与逆光工况。",
           "主控板端推理耗时随平台实测回填，据此确定最大可用帧率与丢帧策略。"],
          ["done", "doing"], F.T01_SOURCE)


def p23(prs):
    _task(prs, 23,
          "任务二（二维码循迹）：路径表达、解码器对照与到位判定",
          "赛题要求识别二维码并按指示路径行走。载荷格式支持多段路径，旧单动作格式保持兼容。",
          ["取帧", "三解码器对照", "解析路径", "整条校验", "逐段执行", "到点判定"],
          [(f"{F.T02_DECODERS[2][1]:.0f}%", "主用解码器成功率", f"判据条件 {F.T02_JUDGE_CASE}"),
           (F.T02_REPLAY, "指令回放正确率", "编码、解码与执行逐段比对"),
           (f"{F.T02_MIN_PX}", "像素宽度硬边界", "低于该值三种解码器均失败")],
          [f"在 {F.T02_SYNTH_SCENES} 组程序合成畸变场景上对照三种解码器，主用轻量模型在判据条件下全部通过。",
           f"路径在整条校验通过后开始执行，段间检查中止信号，任一段失败即停止，单帧解码 {F.T02_MS} ms。",
           "编码端与执行端共用同一套校验，非法动作与越界步数均转为技能失败。",
           "转向由左右髋滚转反对称侧倾实现，与无髋偏航轴的构型一致。"],
          ["真实相机的反光、运动模糊与打印质量纳入下一阶段场景集，扩充判据样本。",
           "到点误差依赖标称位移模型，样机阶段以视觉里程计与惯性测量融合回填标定值。",
           "转向映射在标定阶段实测，形成指令角与实际转角的对应表。"],
          ["done", "doing"], F.T02_SOURCE)


def p24(prs):
    _task(prs, 24,
          "任务三（物品搬运）：两步对准与参数化闭环收敛",
          "搬运流程在横向偏差超出容差时判定失败并终止抓取；放置阶段在未检出路标时保持夹持状态。",
          ["色块检测", "多轮横向伺服", "死区判定", "夹取", "行走", "路标对准后释放"],
          [(F.T03_DETECT, "色块检出", "程序合成图评测"),
           (F.T03_LOOP_TUNED, "推荐参数闭环收敛", f"默认参数 {F.T03_LOOP_DEFAULT}"),
           ("100%", "参数整定提升", f"{F.T03_TUNED_PARAMS}")],
          ["两步对准都要「看见」：目标色块进入死区才夹取，放置阶段未检出路标即保持夹持。",
           "控制常数三级优先级：任务卡参数 > 配置文件 > 代码默认值，换场景只改配置数据。",
           "评测给出参数敏感度表，各作业距离下的可纠正偏差范围可直接查表。",
           "偏差进入死区或落在容差内方可执行抓取，否则判定失败并放弃本次动作。"],
          ["夹爪容差与相机内参在样机阶段标定后回填，控制参数整定无需修改代码。",
           "实机抓取成功率按不低于 80% 验收，评测脚本与标定入口已就位。",
           "100 g 典型载荷下臂部峰值 67.1% 额定，夹持阶段不进入持续堵转工况。"],
          ["done", "doing"], F.T03_SOURCE)


def p25(prs):
    _task(prs, 25,
          "任务四（体育运动）：闭环对位、收敛统计与距离门闩",
          "踢球技能在闭环收敛后执行侧踢；未收敛时按接触补偿策略执行，并在结果中单独回报收敛状态。",
          ["绿球检测", "取横向偏移", "多轮偏航闭环", "侧踢", "按偏移符号选脚", "回报收敛状态"],
          [(F.T04_DETECT, "绿球检出", "图像在环评测"),
           (F.T04_CONVERGE_TUNED, "推荐参数闭环收敛", f"默认参数 {F.T04_CONVERGE_DEFAULT}"),
           (f"{F.T04_RANGE_CM} cm", "动作距离门闩", "区间外判定失败且不下发动作")],
          ["横向伺服为多轮闭环控制律，与搬运任务同构：一套控制核复用于两项赛题。",
           f"距离超出 {F.T04_RANGE_CM} cm 区间或缺少横向偏移时判定失败，不以默认值替代。",
           "结果对象分别回报流程完成与收敛状态，避免把「凑合踢」写成「对准了」。",
           "按球的横向偏移符号选择左/右脚侧踢，动作库关键帧与 20 轴限位同源。"],
          ["单脚支撑相与踝关节峰值扭矩在样机上做台架实测，据此整定降额与助力参数。",
           "实机踢球成功率按不低于 70% 验收；球体位移判据在实机环境中重建基线。",
           "光照变化下的阈值自适应在场景集扩充后重新扫描标定。"],
          ["done", "doing"], F.T04_SOURCE)


def p26(prs):
    _task(prs, 26,
          "任务五（娱乐休闲）：关键词门闩、动作库与本地播报",
          "赛题涵盖舞蹈、音乐播放与语音交互。本方案实现关键词门闩、20 轴动作库与本地语音播报。",
          ["关键词 / 任务卡", "白名单门闩", "20 轴轨迹插补", "动作库执行", "本地播报", "可选音频"],
          [(F.T05_LATCH, "门闩判定", f"命中 {F.T05_LATCH_HIT} · 拒识 {F.T05_LATCH_REJECT}"),
           (F.T05_ASR_HIGH_SNR, "离线真解码", f"低信噪比档 {F.T05_ASR_LOW_SNR}"),
           (f"{F.T05_AXES} 轴", "动作库规模", "关节限位与固件配置同源")],
          [f"离线识别引擎接入后做关键词白名单门控：{F.T05_ENGINE}，白名单外的说法不触发动作。",
           "命中后执行 20 轴短动作序列并本地播报；播放通道不可用时明确标注，不静默跳过。",
           "真解码验证覆盖 7 档信噪比：20 dB 以上全部正确，10 dB 为 2/3，门限行为可解释。",
           "缺引擎或缺模型时跳过对应步骤并注明缺失项，判定结果如实反映链路状态。"],
          ["麦克风链路、拾音距离与说话人差异在样机上重测，重建现场识别基线。",
           "节拍同步与端点检测列入下一阶段功能扩展，动作库按 20 轴限位重新扫掠。",
           "现场噪声条件下的关键词识别率按验收大纲实测回填。"],
          ["done", "doing"], F.T05_SOURCE)


# ═══════════════════════════ 04 验证体系与工程路线 ═══════════════════════════
def p27(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "04", "验证体系与工程路线",
                 "仿真与几何验证的判据、验收大纲、V 模型研发路线与指标索引。")


def p28(prs):
    s = add_slide(prs, PAPER)
    frame(s, "qa", 28)
    page_title(s, "仿真验证的判据设计与结论边界",
               lead=f"运动学离线测试共 {F.TESTS_WEBOTS} 项，判据按三层设计，用于排除「读到指令即判通过」的假阳性。")
    y = Y_BODY + 0.02
    for name, rule in F.SIM_CRITERIA:
        rect(s, CONTENT_X, y, CONTENT_W, 0.70, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, CONTENT_X, y, 0.055, 0.70, fill=BLUE)
        text(s, CONTENT_X + 0.26, y + 0.10, 2.60, 0.30,
             [P([R(name, 12, INK, heavy=True)])])
        text(s, CONTENT_X + 0.26, y + 0.40, CONTENT_W - 0.52, 0.26,
             [P([R(rule, 9.5, GRAPHITE)])])
        y += 0.78
    rect(s, CONTENT_X, y + 0.04, CONTENT_W, 1.58, fill=MIST)
    text(s, CONTENT_X + 0.24, y + 0.18, CONTENT_W - 0.48, 0.28,
         [P([R("两类世界与结论边界", 12, INK, heavy=True)])])
    kv(s, CONTENT_X + 0.24, y + 0.54, CONTENT_W - 0.48, [
        ("默认世界", "零重力、无地面：用于 20 关节运动学联调与接口映射验证"),
        ("派生世界", "由脚本生成带重力与电机参数的世界，用于站立与支撑相校核"),
        ("结论边界", "零重力世界的结果只用于运动学一致性，不作为行走能力的证据"),
    ], name_w=1.20, gap=0.28, size=9.5)
    source(s, CONTENT_X, CONTENT_W,
           "运动学离线测试与带重力派生世界的判据设计")
    status_bar(s, ["done", "doing"])


def p29(prs):
    s = add_slide(prs, PAPER)
    frame(s, "qa", 29)
    page_title(s, "装配几何审查：判据分级与统计结果",
               lead="装配判据基于 B-rep 实体公共体积求解，按严重程度分级统计，检查覆盖全部同源零件。")
    cards = [
        (f"{F.PART_COUNT}", "件", "同源装配快照零件数，几何求解全覆盖", INK),
        ("648", "对", "窄相配对全量求解；采购件内部不重复计入", INK),
        ("0", "相交", "实体公共体积超过判据阈值的零件对数为零", ORANGE),
        ("46", "组", "抽样运动构型扫描，全部通过", INK),
    ]
    w = (CONTENT_W - 0.60) / 4
    for i, (n, u, c, col) in enumerate(cards):
        num_card(s, CONTENT_X + i * (w + 0.20), Y_BODY, w, 1.38, n, u, c,
                 color=col, num_size=26, caption_size=8.5)
    y = Y_BODY + 1.56
    text(s, CONTENT_X, y, CONTENT_W, 0.50,
         [P([R("判据说明：", 10.5, INK, heavy=True),
             R("以 B-rep 实体公共体积超过 0.01 mm³ 作为相交判据，面接触不计；"
               "因此「零相交」表示没有任何一对零件被判定为占用同一块空间，"
               "配合面与贴合面按设计意图保留。", 10, GRAPHITE)], line_spacing=1.28)])
    rect(s, CONTENT_X, y + 0.66, CONTENT_W, 1.76, fill=MIST)
    text(s, CONTENT_X + 0.24, y + 0.80, CONTENT_W - 0.48, 0.28,
         [P([R("判据分级与统计", 12, INK, heavy=True)])])
    table(s, CONTENT_X + 0.24, y + 1.08, 5.60,
          ["判据", "阈值", "结果"],
          [["面接触", "公共体积 ≤ 0.01 mm³", "不计为相交"],
           ["实体相交", "公共体积 > 0.01 mm³", "0 对"],
           ["运动构型", "抽样 46 组零位外构型", "全部通过"]],
          col_w=[1.10, 2.60, 1.90], row_h=0.32, size=8.5, head_size=8.5)
    kv(s, CONTENT_X + 6.20, y + 1.08, CONTENT_W - 6.44, [
        ("骨盆", "由整块大板改为开放框架 + 局部角铝转接"),
        ("髋腰", "侧摆关节改为前后双侧支承，受力路径连续"),
        ("腿部", "大腿后板连续斜撑避开髋部凸起，足板开窗减重"),
        ("门禁", "包络、髋距、头顶高度与零位间隙逐项自动校验"),
    ], name_w=0.80, gap=0.30, size=9)
    source(s, CONTENT_X, CONTENT_W, F.GEOMETRY_SOURCE)
    status_bar(s, ["done"])


def p30(prs):
    """V 模型研发路线：三阶段里程碑。"""
    s = add_slide(prs, PAPER)
    frame(s, "qa", 30, right="研发路线")
    page_title(s, "研发里程碑与工程落地路线",
               lead="按系统工程规范推进：需求与验收准则先行，设计与验证逐级对应，从数字样机稳步走向物理样机。")
    y = Y_BODY - 0.02
    tag_color = {"已达成": GREEN, "进行中": ORANGE, "规划中": GRAY}
    for tag, name, state, items in F.ROADMAP:
        h = 1.26 if len(items) >= 3 else 1.02
        card(s, CONTENT_X, y, CONTENT_W, h, fill=WHITE)
        rect(s, CONTENT_X, y, 0.055, h, fill=tag_color[state])
        text(s, CONTENT_X + 0.28, y + 0.10, 6.20, 0.30,
             [P([R(tag, 11, BLUE, heavy=True), R("　" + name, 12, INK, heavy=True)])])
        rect(s, CONTENT_X + CONTENT_W - 1.30, y + 0.14, 1.06, 0.26,
             fill=tag_color[state])
        text(s, CONTENT_X + CONTENT_W - 1.30, y + 0.14, 1.06, 0.26,
             [P([R(state, 9.5, WHITE, heavy=True)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)
        yy = y + 0.48
        for t in items:
            rect(s, CONTENT_X + 0.30, yy + 0.06, 0.05, 0.05,
                 fill=tag_color[state])
            text(s, CONTENT_X + 0.48, yy - 0.02, CONTENT_W - 0.86, 0.26,
                 [P([R(t, 9.5, GRAPHITE)])])
            yy += 0.24
        y += h + 0.12
    note(s, CONTENT_X, y + 0.02, CONTENT_W,
         "阶段划分与验收准则一一对应：每一项能力都先写清判据与测量方法，再进入实现，"
         "避免「先做出演示、再补指标」的常见倒置。", 9, GRAY)
    status_bar(s, ["done", "doing", "plan"])


def p31(prs):
    s = add_slide(prs, PAPER)
    frame(s, "qa", 31)
    page_title(s, "整机研发指标与测试验收大纲",
               lead="验收大纲覆盖几何、承载、电气与任务四类准则，每条准则都给出判据与测量方法。")
    w = (CONTENT_W - 0.60) / 4
    for i, (name, col, items) in enumerate(F.ACCEPTANCE):
        x = CONTENT_X + i * (w + 0.20)
        rect(s, x, Y_BODY, w, 0.32, fill=col)
        text(s, x + 0.14, Y_BODY, w - 0.28, 0.32,
             [P([R(name, 10.5, WHITE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        yy = Y_BODY + 0.46
        for t in items:
            rect(s, x + 0.02, yy + 0.06, 0.05, 0.05, fill=col)
            text(s, x + 0.18, yy - 0.03, w - 0.24, 0.90,
                 [P([R(t, 9, GRAPHITE)], line_spacing=1.26)])
            yy += 1.06
    rect(s, CONTENT_X, Y_BODY + 2.62, CONTENT_W, 1.20, fill=MIST)
    text(s, CONTENT_X + 0.24, Y_BODY + 2.76, CONTENT_W - 0.48, 0.28,
         [P([R("大纲的作用", 11.5, INK, heavy=True)])])
    text(s, CONTENT_X + 0.24, Y_BODY + 3.08, CONTENT_W - 0.48, 0.62,
         [P([R("把「能做到什么程度」变成一份可勾选的清单：设计阶段逐条对应判据，"
               "样机到位后按同一份清单逐项闭合，任何一项的结论都能追溯到测量方法与数据来源。"
               "评审现场可以按这份大纲追问任意一条的实现状态。", 9.5, GRAPHITE)],
            line_spacing=1.30)])
    source(s, CONTENT_X, CONTENT_W, "验收准则与判据引自整机研发指标与测试验收大纲")
    status_bar(s, ["design", "doing"])


def p32(prs):
    s = add_slide(prs, PAPER)
    frame(s, "qa", 32)
    page_title(s, "样机阶段的标定与实测工作计划",
               lead="计划按前置依赖排序：执行器台架与样机装配是其余全部实体指标的前置条件。")
    rows = [
        ["1", "执行器台架实测", "建立测力与温升台架，实测连续扭矩与堵转曲线",
         "关节利用率与降额参数", "可立即启动"],
        ["2", "结构件试制与装配", "铝件下料、PETG 打印、总成装配与走线",
         "整机质量与装配精度", "依赖零件备料"],
        ["3", "相机内参与夹爪标定", "棋盘格标定并回填配置，标定夹爪容差",
         "搬运步长增益与像素换算", "依赖样机相机"],
        ["4", "总线联调与零位标定", "半双工总线驱动、关节零位与方向标定",
         "真机运动数据一致性", "依赖样机电气"],
        ["5", "电源与续航验证", "扩展电源选型、充放电与任务循环实测",
         "连续作业时长与热负荷", "依赖功率实测"],
        ["6", "现场条件评测", "真实相机、光照与噪声环境下重跑评测脚本",
         "感知类指标的现场基线", "依赖样机与场地"],
    ]
    table(s, CONTENT_X, Y_BODY, CONTENT_W,
          ["序", "工作项", "内容", "对应指标", "前置条件"],
          rows, col_w=[0.50, 2.40, 3.55, 3.62, 1.60], row_h=0.54, size=9.5, head_size=9.5)
    y = Y_BODY + 0.34 + 6 * 0.54 + 0.14
    text(s, CONTENT_X, y, CONTENT_W, 0.28,
         [P([R("说明：", 9.5, INK, heavy=True),
             R("上述工作项按依赖排序，前置条件满足后即可逐项闭合；"
               "每一项的测量方法与判定阈值已在验收大纲中预先定义。", 9.5, GRAPHITE)])])
    status_bar(s, ["doing", "plan"])


def p33(prs):
    s = add_slide(prs, PAPER)
    frame(s, "qa", 33)
    page_title(s, "指标汇总与数据来源索引",
               lead="下表汇总对外引用的主要指标、数值与口径，便于逐项核验。")
    rows = [
        ["整机包络", f"{F.ENVELOPE_MM[0]:g} × {F.ENVELOPE_MM[1]:g} × {F.ENVELOPE_MM[2]:g} mm",
         "CAD 实算", "同源装配体轴对齐包围盒"],
        ["自由度", f"{F.DOF}（{F.DOF_BREAKDOWN}）", "设计值", "关节表与固件配置同源"],
        ["装配体规模", f"{F.PART_COUNT} 件，几何零相交", "CAD 实算", "B-rep 干涉求解"],
        ["质量账", f"已计 {F.MASS_ACCOUNTED_G} g / 目标 {F.MASS_TARGET_G} g",
         "逐项建账", "材料密度与采购件标称质量"],
        ["关节载荷", f"行走 {F.TORQUE_WALK_PCT}% · 极限保持 {F.TORQUE_HOLD_PCT}%",
         "设计校核", "静力学扫掠 + 动载系数"],
        ["电源配置", f"{F.BATTERY_PACK}", "采购件", "厂家规格与包络"],
        ["成本", f"全口径 ¥{F.COST_CLOSE}–{F.COST_RETAIL}", "BOM 询价", "逐项询价区间"],
        ["离线测试", f"{F.TESTS_MAIN} + {F.TESTS_WEBOTS} + {F.TESTS_V2_CAD} 项",
         "本机复跑", "单元测试离线执行"],
        ["人脸识别", f"rank-1 {F.T01_RANK1_50}%（50 人）", "公开基准集", "困难协议闭集辨识"],
        ["二维码解码", f"主用解码器 {F.T02_DECODERS[2][1]:.0f}%", "合成场景集",
         f"{F.T02_SYNTH_SCENES} 组畸变场景 × 3 解码器"],
        ["搬运与踢球", f"{F.T03_LOOP_TUNED} / {F.T04_CONVERGE_TUNED}", "合成图与几何在环",
         "参数敏感度表"],
    ]
    table(s, CONTENT_X, Y_BODY, CONTENT_W,
          ["指标", "数值", "口径", "来源"], rows,
          col_w=[1.45, 2.90, 2.10, 5.22], row_h=0.30, size=9, head_size=9.5)
    source(s, CONTENT_X, CONTENT_W,
           "完整口径与边界见答辩材料口径说明；所有数值均标注方法来源")
    status_bar(s, ["done", "doing"])


def p34(prs):
    s = add_slide(prs, INK)
    frame(s, "qa", 34, dark=True, right="结论")
    page_title(s, "结论与展望", dark=True,
               lead="项目以数字化样机完成了构型、结构与全离线算法栈的闭环设计，"
                    "并建立了覆盖四类准则的验收大纲。")
    items = [
        ("高紧凑构型已定型", f"{F.DOF} 自由度仿人拓扑，包络 "
         f"{F.ENVELOPE_MM[0]:g} × {F.ENVELOPE_MM[1]:g} × {F.ENVELOPE_MM[2]:g} mm，"
         "铝夹层承力与双侧支承方案完成几何审查。"),
        ("全离线任务栈已闭环", "五项赛务任务在同一套任务卡与状态机上实现，"
         "699 项软件测试与 41 项运动学测试离线复跑通过。"),
        ("算法具备可核查的定量结果", "人脸识别、二维码解码、视觉伺服与离线语音"
         "各自给出数据集或合成场景下的评测结果与参数敏感度表。"),
        ("工程路线清晰", "执行器台架、样机试制、相机与总线标定、现场条件评测"
         "按依赖排序推进，验收准则已先行定义。"),
        ("教学与产业价值明确", f"按 20 台规模，班级投入约为同级平台的三分之一，"
         "使每名学生可以独立完成从构型到任务调度的全流程实践。"),
    ]
    w = (CONTENT_W - 0.45) / 3
    for i, (name, desc) in enumerate(items):
        x = CONTENT_X + (i % 3) * (w + 0.225)
        yy = Y_BODY + 0.16 + (i // 3) * 1.70
        rect(s, x, yy, w, 1.50, fill="14304F")
        rect(s, x, yy, w, 0.045, fill=ORANGE)
        text(s, x + 0.24, yy + 0.24, w - 0.48, 0.32,
             [P([R(name, 12.5, WHITE, heavy=True)])])
        text(s, x + 0.24, yy + 0.66, w - 0.48, 0.72,
             [P([R(desc, 9.5, BLUE_300)], line_spacing=1.30)])
    text(s, CONTENT_X, Y_BODY + 3.52, CONTENT_W, 0.30,
         [P([R("下一步：", 10.5, WHITE, heavy=True),
             R("完成样机试制与标定，把设计口径的指标逐项转化为实测结果。", 10.5, BLUE_300)])])
    status_bar(s, ["done", "doing", "plan"], dark=True)


def p35(prs):
    s = add_slide(prs, PAPER)
    frame(s, "qa", 35, right="团队")
    page_title(s, "团队分工与致谢",
               lead="团队按机械、统筹、算法、系统与小脑总线五条线分工，全栈能力自持。")
    y = Y_BODY + 0.04
    for name, duty in F.TEAM:
        rect(s, CONTENT_X, y, 7.30, 0.62, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, CONTENT_X, y, 0.05, 0.62, fill=BLUE)
        text(s, CONTENT_X + 0.26, y, 1.30, 0.62,
             [P([R(name, 12, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, CONTENT_X + 1.66, y, 5.40, 0.62,
             [P([R(duty, 9.5, GRAPHITE)])], anchor=MSO_ANCHOR.MIDDLE)
        y += 0.72
    bx = CONTENT_X + 7.70
    rect(s, bx, Y_BODY + 0.04, CONTENT_W - 7.70, 1.42, fill=MIST)
    text(s, bx + 0.22, Y_BODY + 0.18, CONTENT_W - 8.14, 0.28,
         [P([R("指导教师", 11.5, INK, heavy=True)])])
    text(s, bx + 0.22, Y_BODY + 0.52, CONTENT_W - 8.14, 0.80,
         [P([R(F.ADVISORS, 11, GRAPHITE)], line_spacing=1.30),
          P([R("路线把关 · 教学应用 · 合规审查", 9, GRAY)], line_spacing=1.30)])
    rect(s, bx, Y_BODY + 1.60, CONTENT_W - 7.70, 1.96, fill=MIST)
    text(s, bx + 0.22, Y_BODY + 1.74, CONTENT_W - 8.14, 0.28,
         [P([R("致谢", 11.5, INK, heavy=True)])])
    text(s, bx + 0.22, Y_BODY + 2.08, CONTENT_W - 8.14, 1.32,
         [P([R("感谢学院在实验室场地、计算资源与教学应用场景上的支持，"
               "感谢指导教师在构型决策与合规口径上的把关。", 9.5, GRAPHITE)],
            line_spacing=1.30)])
    text(s, CONTENT_X, 5.92, CONTENT_W, 0.34,
         [P([R("A.T.R.I. 桌面自主人形智能　|　中国国际大学生创新大赛（2026）"
               "陕西赛区 · 人形机器人专项 · 小人形组", 10, INK, heavy=True)])])
    status_bar(s, ["done"])


# ═══════════════════════════ 组装 ═══════════════════════════
PAGES = [p01, p02, p03, p04, p05, p06, p07, p08, p09, p10, p11, p12,
         p13, p14, p15, p16, p17, p18, p19, p20, p21, p22, p23, p24,
         p25, p26, p27, p28, p29, p30, p31, p32, p33, p34, p35]


def main():
    stem = sys.argv[1] if len(sys.argv) > 1 else "ATRI-答辩PPT-v7"
    assert len(PAGES) == TOTAL, f"页数不一致：PAGES={len(PAGES)} TOTAL={TOTAL}"
    prs = new_deck()
    for fn in PAGES:
        fn(prs)
    for slide in prs.slides:
        add_transition(slide, "fade", 700)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{stem}.pptx"
    prs.save(str(path))
    print(f"saved: {path}  ({len(PAGES)} pages)")


if __name__ == "__main__":
    main()
