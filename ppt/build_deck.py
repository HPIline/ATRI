"""A.T.R.I. 答辩 PPT · 全 51 页构建器。

用法： ./.venv-ppt/bin/python ppt/build_deck.py "ATRI-答辩PPT-定稿"
文案来源：资料/调研/项目文档/答辩PPT-逐页文案-v3.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

from design import *          # noqa: F401,F403
from design import flow_chain, bullets, code_block, table, picture_cover, joint_chain_h
from animate import add_transition, add_entrance
from diagrams import (chapter_page, fsm_diagram, gait_phase, servo_loop,
                      price_bands, positioning_map, funnel, gantt,
                      pipeline_strip, impl_status, task_flow, _seg, _box,
                      _rarrow, joint_topology)

OUT = Path(__file__).resolve().parent / "out"
REPO = OUT.parent.parent          # 仓库根（<repo>/ppt/out → 上两级）
AST = OUT.parent / "assets"
DWG = AST / "drawings"

# 章节号 → (编号, 名称)
CH = {
    0:  ("00", "项目概要"),
    1:  ("01", "立项基础"),
    2:  ("02", "面向市场"),
    3:  ("03", "技术架构与实现"),
    4:  ("04", "五项任务闭环"),
    5:  ("05", "特色与创新"),
    6:  ("06", "验证与推进"),
}

# 朱橙重音数字
def accent(slide, x, y, w, num, unit="", size=34, unit_size=12, align=PP_ALIGN.LEFT):
    text(slide, x, y, w, 0.42,
         [P([R(num, size, ORANGE, heavy=True), R(" " + unit, unit_size, ORANGE, heavy=True)],
            align=align)])


def sec_head(slide, x, y, w, label):
    text(slide, x, y, w, 0.24, [P([R(label, 10.5, BLUE, heavy=True)])])


# ═══════════════════════════════════════════════════════════════════
# 开场
# ═══════════════════════════════════════════════════════════════════
def p01(prs):
    s = add_slide(prs, PAPER)
    X = CONTENT_X
    text(s, X, 0.82, 6.2, 0.26,
         [P([R("中国国际大学生创新大赛（2026）", 10.5, BLUE, heavy=True),
             R("　陕西赛区特色专项 · 人形机器人专项 · 小人形组", 10.5, GRAY)])])
    text(s, X, 1.72, 6.4, 1.00, [P([R("A.T.R.I.", 54, INK, heavy=True, spc=1.5)])])
    text(s, X, 2.68, 6.4, 0.58, [P([R("桌面自主人形智能", 31, INK, heavy=True, spc=1.5)])])
    text(s, X, 3.30, 6.4, 0.26,
         [P([R("AUTONOMOUS TABLETOP ROBOTIC INTELLIGENCE", 9.5, GRAY, spc=2.4)])])
    rect(s, X, 3.84, 0.72, 0.05, fill=ORANGE)
    text(s, X, 4.10, 6.3, 0.36,
         [P([R("一台能自己看、自己想、自己走的桌面双足机器人", 16.5, GRAPHITE)])])
    text(s, X, 4.66, 6.6, 0.30,
         [P([R("22 DOF", 15, ORANGE, heavy=True),
             R("　·　", 11, BLUE_300),
             R("41.8 cm", 15, ORANGE, heavy=True),
             R("　·　", 11, BLUE_300),
             R("169 项测试通过", 15, ORANGE, heavy=True)])])
    joint_chain_h(s, X, 5.32, 5.87, n=22, first_color=ORANGE)
    text(s, X, 5.50, 6.3, 0.24,
         [P([R("22 个主动自由度", 9.5, BLUE, heavy=True),
             R("　双腿 10 · 双臂 8 · 躯干 2 · 头部 2", 9.5, GRAY)])])
    text(s, X, 5.96, 6.4, 0.24, [P([R("项目团队", 9, GRAY)])])
    text(s, X, 6.17, 6.4, 0.28,
         [P([R("何浩睿 · 周柏宇 · 胡晟瑞 · 王旭琪 · 张景昆", 13, GRAPHITE)])])
    text(s, X, 6.50, 6.4, 0.24, [P([R("指导教师　陈妍 · 李璐", 9, GRAY)])])

    vline(s, 7.42, 0.72, SLIDE_H - 1.44, color=LINE, width=0.75)
    dwg = DWG / "01_关节编号图.png"
    if dwg.exists():
        picture_cover(s, 7.60, 1.10, 5.55, 4.60, str(dwg), focus_x=0.26, focus_y=0.5)
    text(s, 7.60, 5.86, 5.6, 0.24,
         [P([R("22 关节结构运动学图", 9.5, BLUE, heavy=True),
             R("　图号 ATRI-DWG-001", 8.5, GRAY)])])
    text(s, 7.60, 6.08, 5.6, 0.44,
         [P([R("软件栈已跑通五项任务闭环；样机在晋级后制造。", 10, GRAPHITE)])])


def p02(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "00", "项目概要", 2, right_label="项目概要")
    page_title(s, "五项赛题共用一套任务系统，软件栈已经跑通",
               lead="左边是要解决的问题，中间是已经做出来的东西，右边是当前推进到哪一步。")
    A_X, A_W = CONTENT_X, 3.30
    B_X, B_W = 4.493, 4.55
    C_X, C_W = 9.403, 3.097

    sec_head(s, A_X, Y_BODY, A_W, "要解决的问题")
    hline(s, A_X, Y_BODY + 0.30, A_W, color=BLUE_300, width=1.0)
    y = Y_BODY + 0.46
    for no, t, d in [("01", "设备贵", "教育型小型双足套件多在数千至万元级，一个班 20 台就是十万级"),
                     ("02", "算法散", "人脸、循迹、抓取、步态散在四五套互不相通的工程里"),
                     ("03", "断网瘫", "依赖云端推理的方案，赛场一断网就失效")]:
        text(s, A_X, y, 0.42, 0.26, [P([R(no, 12, ORANGE, heavy=True)])])
        text(s, A_X + 0.44, y, A_W - 0.44, 0.26, [P([R(t, 13, INK, heavy=True)])])
        text(s, A_X + 0.44, y + 0.28, A_W - 0.44, 0.80,
             [P([R(d, 10, GRAY)], line_spacing=1.35)])
        y += 1.22

    sec_head(s, B_X, Y_BODY, B_W, "已经做出来的")
    hline(s, B_X, Y_BODY + 0.30, B_W, color=BLUE_300, width=1.0)
    cw = (B_W - 0.30) / 2
    ch = 1.72
    y1, y2 = Y_BODY + 0.46, Y_BODY + 0.46 + ch + 0.18
    num_card(s, B_X, y1, cw, ch, "22", "DOF", "主动自由度：双腿 10 + 双臂 8 + 躯干 2 + 头部 2")
    num_card(s, B_X + cw + 0.30, y1, cw, ch, "133", "项",
             "测试全通过 = 软件行为 51 + 设计模型与工程图 82", num_size=32)
    num_card(s, B_X, y2, cw, ch, "5/5", "",
             "五项任务无硬件闭环演示全部通过，可当场复现", num_size=32)
    num_card(s, B_X + cw + 0.30, y2, cw, ch, "¥2100", "–2800",
             "新增采购（全口径 ¥2788–3456；差额为借用主控与已有电池）",
             num_size=24, unit_size=12)

    sec_head(s, C_X, Y_BODY, C_W, "推进到哪一步")
    hline(s, C_X, Y_BODY + 0.30, C_W, color=BLUE_300, width=1.0)
    y = Y_BODY + 0.46
    for kind, t, d in [("done", "软件栈 + 设计模型", "169 项测试、5/5 闭环、22 关节设计模型与 4 张工程图"),
                       ("doing", "仿真验证", "闭环控制律已跑出收敛序列与鲁棒性边界；Webots 22 DOF 运动学联调通过"),
                       ("plan", "实物样机", "晋级后启动采购、3D 打印与装配")]:
        bh = 1.15
        rect(s, C_X, y, C_W, bh, fill=MIST)
        status_chip(s, C_X + 0.16, y + 0.14, kind, size=10)
        text(s, C_X + 0.16, y + 0.48, C_W - 0.32, 0.26,
             [P([R(t, 12.5, INK, heavy=True)])])
        text(s, C_X + 0.16, y + 0.74, C_W - 0.32, 0.34,
             [P([R(d, 9.5, GRAY)], line_spacing=1.28)])
        y += bh + 0.08
    status_bar(s, ["done"])


def p03(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "00", "项目概要", 3, right_label="项目概要")
    page_title(s, "六章，从「为什么做」走到「谁来做、要多少钱」",
               lead="每页只挂一个主状态标签；行内细则用小标。")
    items = [("01", "立项基础", "为什么要在此时此地做这台机器人", "P04–P10"),
             ("02", "面向市场", "卖给谁、市场多大、凭什么赢", "P11–P15"),
             ("03", "技术架构与实现", "怎么做的、技术硬在哪", "P16–P31"),
             ("04", "五项任务闭环", "五项赛题具体怎么跑通", "P32–P39"),
             ("05", "特色与创新", "我们独特在哪", "P40–P44"),
             ("06", "验证与推进", "做到哪步、谁在做、要多少钱", "P45–P51")]
    x, w = CONTENT_X, 7.90
    y = Y_BODY + 0.10
    for no, name, desc, rng in items:
        rect(s, x, y, w, 0.62, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, x, y, 0.045, 0.62, fill=BLUE)
        text(s, x + 0.26, y, 0.60, 0.62,
             [P([R(no, 15, BLUE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 0.92, y, 2.10, 0.62,
             [P([R(name, 13.5, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 3.05, y, 3.25, 0.62,
             [P([R(desc, 10, GRAY)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + w - 1.30, y, 1.10, 0.62,
             [P([R(rng, 10, BLUE, heavy=True)], align=PP_ALIGN.RIGHT)],
             anchor=MSO_ANCHOR.MIDDLE)
        y += 0.72

    px, pw = 9.05, 3.45
    rect(s, px, Y_BODY + 0.10, pw, 4.10, fill=MIST)
    text(s, px + 0.26, Y_BODY + 0.34, pw - 0.52, 0.26,
         [P([R("状态标注制度", 12, INK, heavy=True)])])
    hline(s, px + 0.26, Y_BODY + 0.66, pw - 0.52, color=BLUE_300, width=1.0)
    yy = Y_BODY + 0.86
    for kind, t, d in [("done", "仓库里有代码、测试或工程图可查证", None),
                       ("doing", "已启动、有中间产物", None),
                       ("plan", "方案已定、尚未落地", None),
                       ("design", "有设计模型与图纸，无实物", None)]:
        sym, lab, col = STATUS[kind]
        text(s, px + 0.26, yy, pw - 0.52, 0.24,
             [P([R(sym + " " + lab, 11, col, heavy=True)])])
        text(s, px + 0.26, yy + 0.24, pw - 0.52, 0.46,
             [P([R(t, 9.5, GRAY)], line_spacing=1.30)])
        yy += 0.80
    status_bar(s, [])


# ═══════════════════════════════════════════════════════════════════
# 第一章 立项基础
# ═══════════════════════════════════════════════════════════════════
def p04(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "01", "为什么要在此时、此地，做一台桌面双足机器人",
                 "立项基础 · P04–P10")


def p05(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "01", "立项基础", 5)
    page_title(s, "政策、区域、赛事三条线，在同一年交汇到同一个点",
               lead="这三件事同时要求同一件东西：一台便宜、能拆开讲原理、能跑完整任务链的机器人。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 4.0, "2026.4", "具身智能列入本科专业目录")
    cards = [
        ("国家政策", "2026 年 4 月「具身智能」列入普通高等学校本科专业目录，"
                     "西安交通大学为首批获批建设高校之一，同年秋季开始本科招生。"
                     "新专业需要能成班开出的实验设备。"),
        ("区域政策", "陕西省推进「人工智能+教育」行动计划，需要可落地的教学载体，"
                     "而不只是课程与平台。"),
        ("赛事规则", "人形机器人专项设小人形组，五项任务清单（人脸识别 / 二维码循迹 / "
                     "物品搬运 / 体育运动 / 娱乐休闲）本身就是一份可验收的教学大纲。"),
    ]
    cw = (CONTENT_W - 0.60) / 3
    y = Y_BODY + 0.78
    for i, (t, d) in enumerate(cards):
        x = CONTENT_X + i * (cw + 0.30)
        rect(s, x, y, cw, 2.50, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, x, y, cw, 0.045, fill=BLUE)
        text(s, x + 0.28, y + 0.30, cw - 0.56, 0.30,
             [P([R(t, 14, INK, heavy=True)])])
        hline(s, x + 0.28, y + 0.70, cw - 0.56, color=BLUE_300, width=1.0)
        text(s, x + 0.28, y + 0.88, cw - 0.56, 1.40,
             [P([R(d, 10.5, GRAPHITE)], line_spacing=1.45)])
    rect(s, CONTENT_X, 5.98, CONTENT_W, 0.46, fill=MIST)
    text(s, CONTENT_X + 0.24, 5.98, CONTENT_W - 0.48, 0.46,
         [P([R("三条线指向同一个缺口——", 11, GRAPHITE),
             R("缺少一台「买得起、拆得开、跑得完」的桌面双足平台", 11, INK, heavy=True)])],
         anchor=MSO_ANCHOR.MIDDLE)
    status_bar(s, ["done"])


def p06(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "01", "立项基础", 6)
    page_title(s, "想开一门双足实验课，第一道坎不是教学法，是预算",
               lead="价格门槛不降下来，「成班开课」这四个字就不成立。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 6.6, "¥2100–2800", "新增采购 ／ 全口径 ¥2788–3456（一个班 20 台 ≈ 4.2–6.9 万）")
    price_bands(s, CONTENT_X + 0.15, Y_BODY + 0.86, CONTENT_W - 3.30, 2.30, [
        ("全尺寸人形", 30000, 150000, "C9D6E2", "一个班 20 台 = 百万级"),
        ("教育型小型双足套件", 5000, 12000, "9CC0DC", "一个班 20 台 ≈ 十万级"),
        ("A.T.R.I. 方案", 2100, 2800, ORANGE, "一个班 20 台 ≈ 4.2–5.6 万"),
    ])
    rect(s, CONTENT_X, 5.42, CONTENT_W, 1.00, fill=MIST)
    text(s, CONTENT_X + 0.24, 5.56, CONTENT_W - 0.48, 0.72,
         [P([R("把单价压到两千元级（新增采购），是「能开课」与「只能演示」的分界线。", 11, GRAPHITE)]),
          P([R("口径：本方案为设计目标清单，BOM 逐项见 P49，尚未采购；"
               "竞品价格为公开产品页口径，非实测。", 8.5, GRAY)],
            space_before=6)])
    status_bar(s, ["plan"])


def p07(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "01", "立项基础", 7)
    page_title(s, "五项任务、五套工程——学生学到的是五个互不相通的孤岛",
               lead="现状不是「没有算法」，而是算法之间没有共同的骨架。")
    # 左：现状
    text(s, CONTENT_X, Y_BODY, 5.4, 0.24,
         [P([R("现状：五套工程各自为政", 11, GRAY, heavy=True)])])
    bx, bw = CONTENT_X, 1.00
    for i in range(5):
        x = CONTENT_X + i * (bw + 0.09)
        rect(s, x, Y_BODY + 0.34, bw, 1.05, fill=WHITE, line=LINE, line_w=0.75)
        text(s, x, Y_BODY + 0.34, bw, 1.05,
             [P([R("独立工程", 8.5, GRAPHITE, heavy=True)], align=PP_ALIGN.CENTER),
              P([R("相机初始化", 7, GRAY)], align=PP_ALIGN.CENTER),
              P([R("状态管理", 7, GRAY)], align=PP_ALIGN.CENTER),
              P([R("主循环", 7, GRAY)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)
    _seg(s, CONTENT_X + 5.55, Y_BODY + 0.86, CONTENT_X + 6.10, Y_BODY + 0.86,
         ORANGE, 1.6)
    # 右：本方案
    rx = CONTENT_X + 6.30
    text(s, rx, Y_BODY, 5.4, 0.24,
         [P([R("本方案：一个底座 + 五个插件", 11, BLUE, heavy=True)])])
    for i in range(5):
        x = rx + i * (bw + 0.09)
        rect(s, x, Y_BODY + 0.34, bw, 0.50, fill=MIST, line=BLUE_300, line_w=0.75)
        text(s, x, Y_BODY + 0.34, bw, 0.50,
             [P([R("技能", 9, INK, heavy=True)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)
    rect(s, rx, Y_BODY + 0.98, 5.40, 0.42, fill=INK)
    text(s, rx, Y_BODY + 0.98, 5.40, 0.42,
         [P([R("JSON 任务卡  →  FSM 状态机  →  技能库", 10.5, WHITE, heavy=True)],
            align=PP_ALIGN.CENTER)], anchor=MSO_ANCHOR.MIDDLE)
    bullets(s, CONTENT_X, 4.05, 5.4, [
        ("换任务要改主程序", "实验之间无法对照"),
        ("无法评测系统能力", "只能评测某个脚本能不能跑"),
        ("学到一次性脚本", "不是可扩展的系统设计"),
    ], gap=0.52, name_size=10.5, desc_size=10)
    rect(s, 6.90, 3.98, 5.60, 1.80, fill=MIST)
    text(s, 7.14, 4.16, 5.12, 1.46,
         [P([R("任务 = 一份 JSON 文件", 12, INK, heavy=True)]),
          P([R("能力 = 一个技能模块", 12, INK, heavy=True)], space_before=8),
          P([R("调度 = 一个状态机", 12, INK, heavy=True)], space_before=8),
          P([R("底座已在仓库中实现并通过 169 项测试", 9.5, GRAY)], space_before=14)])
    status_bar(s, ["done"])


def p08(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "01", "立项基础", 8)
    page_title(s, "比赛现场拔掉网线的那一刻，很多方案就失效了",
               lead="全离线不是技术炫技，是赛题要求下的工程必选项。")
    # 云端链路
    text(s, CONTENT_X, Y_BODY, 5.0, 0.24,
         [P([R("云端推理链路", 11, GRAY, heavy=True)])])
    flow_chain(s, CONTENT_X, Y_BODY + 0.32, CONTENT_W, 
               ["相机", "上传", "云推理", "下发", "执行"],
               h=0.52, size=10.5, fill=WHITE, line=LINE, txt=GRAPHITE, heavy=False)
    for i, t in enumerate(["网络抖动", "限速", "服务变更", "数据外传"]):
        x = CONTENT_X + i * 2.95
        text(s, x, Y_BODY + 0.94, 2.80, 0.22,
             [P([R("✕ " + t, 9, ORANGE)])])
    # 本方案链路
    text(s, CONTENT_X, Y_BODY + 1.34, 5.0, 0.24,
         [P([R("本方案：整条链路在一个盒子里", 11, BLUE, heavy=True)])])
    flow_chain(s, CONTENT_X, Y_BODY + 1.66, CONTENT_W,
               ["相机", "板载推理", "FSM", "小脑", "舵机"],
               h=0.52, size=10.5, fill=MIST_2, line=None, txt=INK)
    text(s, CONTENT_X, Y_BODY + 2.28, CONTENT_W, 0.24,
         [P([R("全程 0 次网络出站", 10, GREEN, heavy=True)])])
    rect(s, CONTENT_X, Y_BODY + 2.74, CONTENT_W, 1.30, fill=WHITE, line=LINE,
         line_w=0.75)
    text(s, CONTENT_X + 0.26, Y_BODY + 2.94, CONTENT_W - 0.52, 0.96,
         [P([R("代价与边界", 11, INK, heavy=True)]),
          P([R("本地小模型的识别精度不如云端大模型。我们用固定光照 + 固定颜色目标先把稳定性做上去，"
               "再逐步扩展工况。教学场景对数据外传敏感，离线同时解决了这一层顾虑。",
               10, GRAPHITE)], space_before=6, line_spacing=1.40)])
    status_bar(s, ["plan"])


def p09(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "01", "立项基础", 9)
    page_title(s, "小型双足机器人，如何在有限算力和断网条件下，用统一任务描述完成多任务自主执行？",
               lead="这一句是后面所有技术工作的靶心。", title_size=26)
    subs = [("子问题一", "怎么描述任务，才能让五项任务共用一套程序？", "P21–P23"),
            ("子问题二", "怎么在无 GPU 的板载算力上完成感知与决策？", "P26–P28"),
            ("子问题三", "怎么让动作跟着视觉反馈走？", "P28、P37")]
    cw = (CONTENT_W - 0.60) / 3
    for i, (no, q, ref) in enumerate(subs):
        x = CONTENT_X + i * (cw + 0.30)
        rect(s, x, Y_BODY + 0.30, cw, 2.40, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, x, Y_BODY + 0.30, cw, 0.045, fill=ORANGE)
        text(s, x + 0.28, Y_BODY + 0.62, cw - 0.56, 0.24,
             [P([R(no, 10, ORANGE, heavy=True)])])
        text(s, x + 0.28, Y_BODY + 0.92, cw - 0.56, 1.10,
             [P([R(q, 14, INK, heavy=True)], line_spacing=1.35)])
        text(s, x + 0.28, Y_BODY + 2.20, cw - 0.56, 0.24,
             [P([R("见 " + ref, 9.5, BLUE)])])
    text(s, CONTENT_X, 5.40, CONTENT_W, 0.60,
         [P([R("全片「具身智能」一词出现不超过 3 次，每次紧跟一个具体机制。", 10, GRAY)])])
    status_bar(s, [])


def p10(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "01", "立项基础", 10)
    page_title(s, "项目立项的四条硬标准，后面每一章都要对得上",
               lead="这四条是我们给自己定的验收线，也是这份材料的组织逻辑。")
    rows = [("1", "合规", "过得了检录：尺寸 / 关节 / 电压 / 传感器逐项核验", "P18"),
            ("2", "能跑", "五项任务在同一台机器上闭环", "P32–P39"),
            ("3", "便宜", "新增采购控制在两千元级", "P49"),
            ("4", "可复现", "设计、代码、仿真、日志在同一套仓库里", "P48")]
    y = Y_BODY + 0.20
    for no, t, d, ref in rows:
        rect(s, CONTENT_X, y, CONTENT_W, 0.86, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, CONTENT_X, y, 0.045, 0.86, fill=BLUE)
        text(s, CONTENT_X + 0.30, y, 0.70, 0.86,
             [P([R(no, 24, ORANGE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, CONTENT_X + 1.20, y, 1.60, 0.86,
             [P([R(t, 16, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, CONTENT_X + 3.00, y, 6.60, 0.86,
             [P([R(d, 11.5, GRAPHITE)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, CONTENT_X + CONTENT_W - 1.60, y, 1.40, 0.86,
             [P([R(ref, 11, BLUE, heavy=True)], align=PP_ALIGN.RIGHT)],
             anchor=MSO_ANCHOR.MIDDLE)
        y += 0.90
    text(s, CONTENT_X, 6.14, CONTENT_W, 0.30,
         [P([R("口径：四条为项目自设标准，不是官方评分维度；官方评分细则尚未发布。",
               9, GRAY)])])
    status_bar(s, ["done", "plan"])


# ═══════════════════════════════════════════════════════════════════
# 第二章 面向市场
# ═══════════════════════════════════════════════════════════════════
def p11(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "02", "同样的预算，别人卖硬件，我们交付能完成任务的系统",
                 "面向市场 · P11–P15")


def p12(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "02", "面向市场", 12)
    page_title(s, "三层真实需求，指向同一台机器",
               lead="首先它是一台小型双足机器人，其次它统一执行五项任务，最后它才是教学平台。")
    users = [("高校专业课教师与学生", "具身智能 / 自动化 / 机器人工程",
              "低成本、可复现、能拆开讲原理的实验设备",
              "22 个关节每个都能单独下发角度并回读，实验可切片到单关节级"),
             ("人形机器人专项竞赛队伍", "换场次不用重写代码",
              "覆盖五项任务的训练平台",
              "任务卡换一个 JSON 文件就是一套新赛题配置"),
             ("创新工坊与实验室二次开发", "接口清楚、能加自己的模块",
              "可扩展的开发底座",
              "技能库插件式注册，感知后端可替换")]
    cw = (CONTENT_W - 0.60) / 3
    for i, (t, sub, need, ans) in enumerate(users):
        x = CONTENT_X + i * (cw + 0.30)
        rect(s, x, Y_BODY + 0.16, cw, 3.60, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, x, Y_BODY + 0.16, cw, 0.045, fill=BLUE)
        text(s, x + 0.28, Y_BODY + 0.44, cw - 0.56, 0.60,
             [P([R(t, 13, INK, heavy=True)], line_spacing=1.25)])
        text(s, x + 0.28, Y_BODY + 1.10, cw - 0.56, 0.24,
             [P([R(sub, 9, GRAY)])])
        hline(s, x + 0.28, Y_BODY + 1.44, cw - 0.56, color=BLUE_300, width=1.0)
        text(s, x + 0.28, Y_BODY + 1.60, cw - 0.56, 0.24,
             [P([R("需求", 9, GRAY, heavy=True)])])
        text(s, x + 0.28, Y_BODY + 1.86, cw - 0.56, 0.70,
             [P([R(need, 10.5, GRAPHITE)], line_spacing=1.35)])
        text(s, x + 0.28, Y_BODY + 2.62, cw - 0.56, 0.24,
             [P([R("本项目的应答", 9, BLUE, heavy=True)])])
        text(s, x + 0.28, Y_BODY + 2.88, cw - 0.56, 0.80,
             [P([R(ans, 10.5, GRAPHITE)], line_spacing=1.35)])
    text(s, CONTENT_X, 6.10, CONTENT_W, 0.30,
         [P([R("口径：用户画像为设计阶段设定，尚未开展用户访谈；访谈计划在 P48 阶段二。",
               9, GRAY)])])
    status_bar(s, ["plan"])


def p13(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "02", "面向市场", 13)
    page_title(s, "不吹 TAM，只算一条能走通的路",
               lead="下面是自下而上的模型与全部假设，参数欢迎质疑。")
    funnel(s, CONTENT_X, Y_BODY + 0.10, 6.60, 3.30, [
        ("陕西省普通高校", "约 90 所（公开统计口径，待逐校核实）", 1.00),
        ("开设相关专业", "自动化 / 机器人工程 / 人工智能 ≈ 40 所", 0.80),
        ("首批试点院校", "有具身智能实验室建设意向 5–8 所（估算，需调研验证）", 0.60),
        ("单校首批订单", "2–5 台 × ¥2100–2800 ≈ 0.42–1.40 万元", 0.42),
    ])
    rx, rw = 7.85, 4.65
    rect(s, rx, Y_BODY + 0.10, rw, 3.30, fill=MIST)
    text(s, rx + 0.28, Y_BODY + 0.34, rw - 0.56, 0.30,
         [P([R("测算结果", 11, BLUE, heavy=True)])])
    accent(s, rx + 0.28, Y_BODY + 0.72, rw - 0.56, "2.1–11.2", "万元", size=30, unit_size=13)
    text(s, rx + 0.28, Y_BODY + 1.34, rw - 0.56, 0.26,
         [P([R("首批试点院校合计可及规模", 10, GRAPHITE)])])
    hline(s, rx + 0.28, Y_BODY + 1.76, rw - 0.56, color=BLUE_300, width=1.0)
    text(s, rx + 0.28, Y_BODY + 1.92, rw - 0.56, 1.30,
         [P([R("先证明「第一批客户是谁、第一单怎么签」，", 10.5, GRAPHITE)],
            line_spacing=1.45),
          P([R("而不是给一个撑不起来的 TAM。", 10.5, GRAPHITE)],
            line_spacing=1.45, space_before=4)])
    rect(s, CONTENT_X, 5.84, CONTENT_W, 0.72, fill=WHITE, line=ORANGE, line_w=1.0)
    text(s, CONTENT_X + 0.24, 5.84, CONTENT_W - 0.48, 0.72,
         [P([R("口径：", 9.5, ORANGE, heavy=True),
             R("本页全部为设计阶段的估算模型，非已签约订单、非市场调研结论。"
               "标注「待核实」的参数需在阶段二通过走访补齐。", 9.5, GRAPHITE)])],
         anchor=MSO_ANCHOR.MIDDLE)
    status_bar(s, ["plan"])


def p14(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "02", "面向市场", 14)
    page_title(s, "两千元级 + 高开放度，这一格目前人不多",
               lead="我们不是在做更便宜的同类产品，是在补一个没有被占据的位置。")
    positioning_map(s, CONTENT_X + 0.60, Y_BODY + 0.46, 6.30, 3.06, [
        ("全尺寸人形", 0.92, 0.50, "9CC0DC", "l"),
        ("教育型小型双足", 0.64, 0.14, "9CC0DC", "l"),
        ("成品竞赛套件", 0.46, 0.30, "9CC0DC", "r"),
        ("自组 18DOF 套件", 0.22, 0.78, "5B8FB9", "r"),
        ("二手整机 ¥1000–2500", 0.06, 0.52, "8FB6D6", "r"),
        ("A.T.R.I.", 0.10, 0.88, ORANGE, "r"),
    ])
    rx, rw = 8.30, 4.20
    rect(s, rx, Y_BODY + 0.16, rw, 3.36, fill=WHITE, line=ORANGE, line_w=1.0)
    text(s, rx + 0.26, Y_BODY + 0.44, rw - 0.52, 0.30,
         [P([R("诚实的麻烦", 12, ORANGE, heavy=True)])])
    text(s, rx + 0.26, Y_BODY + 0.86, rw - 0.52, 2.60,
         [P([R("自组 18DOF 套件（¥2800–3500）在价格与开放度上与我们处在同一区域。",
               10.5, GRAPHITE)], line_spacing=1.45),
          P([R("真正拉开距离的只有一项：", 10.5, GRAPHITE)],
            space_before=12, line_spacing=1.45),
          P([R("统一任务编排", 15, INK, heavy=True)], space_before=4),
          P([R("对手需要逐任务写脚本；我们换一份 JSON。", 10, GRAY)],
            space_before=6, line_spacing=1.45)])
    text(s, CONTENT_X, 6.06, CONTENT_W, 0.30,
         [P([R("口径：坐标为依公开产品资料的定性判断，非精确测评。", 9, GRAY)])])
    status_bar(s, ["plan"])


def p15(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "02", "面向市场", 15)
    page_title(s, "能力逐条对比，差距写在表里",
               lead="自评只区分「已验证 / 部分验证 / 未验证」，不给能力打分。")
    headers = ["", "价格带", "自由度合规", "软件开放度", "统一任务编排", "断网运行", "成熟度"]
    rows = [
        ["全尺寸人形", "数万–十余万", "超尺寸上限", "中", "需自建", "一般", "已验证"],
        ["教育型小型双足", "数千–万元", "部分低于 18", "低", "无", "部分依赖云", "已验证"],
        ["成品竞赛套件", "¥2800–6000", "合规", "低", "逐任务写脚本", "一般", "已验证"],
        ["A.T.R.I.", "¥2100–2800", "22 DOF 合规", "高", "有（统一 FSM）", "全离线", "部分验证"],
    ]
    col_w = [1.85, 1.60, 1.55, 1.40, 1.95, 1.45, 1.90]
    table(s, CONTENT_X, Y_BODY + 0.14, CONTENT_W, headers, rows,
          col_w=col_w, row_h=0.56, head_h=0.40, size=10)
    # 高亮本方案行
    rect(s, CONTENT_X, Y_BODY + 0.14 + 0.40 + 3 * 0.56, CONTENT_W, 0.56,
         fill=None, line=ORANGE, line_w=1.5)
    y = 4.95
    rect(s, CONTENT_X, y, 5.65, 1.30, fill=MIST)
    text(s, CONTENT_X + 0.24, y + 0.18, 5.17, 0.98,
         [P([R("差距说明", 10.5, INK, heavy=True)]),
          P([R("对手在「开箱即用、结构成熟度」上是已验证的；"
               "我们的软件侧部分验证，硬件侧完全未验证。", 10, GRAPHITE)],
            space_before=6, line_spacing=1.40)])
    rect(s, 6.86, y, 5.64, 1.30, fill=INK)
    text(s, 7.10, y + 0.18, 5.16, 0.98,
         [P([R("差异化一句话", 10.5, BLUE_300, heavy=True)]),
          P([R("交付的不是一台机器人，是一条从「任务怎么描述」到「关节怎么动」的链路。",
               10.5, WHITE)], space_before=6, line_spacing=1.40)])
    status_bar(s, ["plan"])


# ═══════════════════════════════════════════════════════════════════
# 第三章 技术架构与实现
# ═══════════════════════════════════════════════════════════════════
def p16(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "03", "从相机出帧到关节到位，中间发生了什么",
                 "技术架构与实现 · P16–P31")


def p17(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 17)
    page_title(s, "五层架构，一次任务走 8 步，两条边界",
               lead="上层不关心关节怎么转，下层不关心任务是什么，两层之间只传一份 JSON 协议。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 6.0, "8 步", "· 全程 0 次网络出站", size=22, unit_size=13)

    TX, TW = CONTENT_X, 1.20
    PX, PW = 2.13, 8.05
    BX, BW = 10.35, 2.15
    LH, LG = 0.54, 0.09
    ys = [Y_BODY + 0.50 + i * (LH + LG) for i in range(5)]
    INNER, by = 0.10, 0.08
    ix, iw = PX + INNER, PW - 2 * INNER
    bh = LH - 2 * by

    def tab(y, name, color):
        rect(s, TX, y, TW, LH, fill=color)
        text(s, TX, y, TW, LH, [P([R(name, 11, WHITE, heavy=True)],
                                  align=PP_ALIGN.CENTER)], anchor=MSO_ANCHOR.MIDDLE)

    def box(x, y, w, lab, size=10, fill=WHITE, line=BLUE_300, color=INK, heavy=False):
        rect(s, x, y, w, bh, fill=fill, line=line, line_w=0.75)
        text(s, x + 0.05, y, w - 0.10, bh,
             [P([R(lab, size, color, heavy=heavy)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)

    def bracket(y, h, name, sub, status):
        arm = 0.14
        _seg(s, BX, y, BX, y + h, BLUE, 1.5)
        _seg(s, BX, y, BX + arm, y, BLUE, 1.5)
        _seg(s, BX, y + h, BX + arm, y + h, BLUE, 1.5)
        sym, lab, col = STATUS[status]
        text(s, BX + arm + 0.12, y, BW - arm - 0.12, h,
             [P([R(name, 11.5, INK, heavy=True)]),
              P([R(sub, 8, GRAY)], space_before=2, line_spacing=1.15),
              P([R(sym + " " + lab, 8, col, heavy=True)], space_before=3)],
             anchor=MSO_ANCHOR.MIDDLE)

    y = ys[0]
    tab(y, "任务层", "5B8FB9")
    rect(s, PX, y, PW, LH, fill=WHITE, line=LINE, line_w=0.75)
    tasks = ["人脸识别", "二维码循迹", "物品搬运", "体育运动", "娱乐交互"]
    cw = (iw - 4 * 0.08) / 5
    for i, t in enumerate(tasks):
        box(ix + i * (cw + 0.08), y + by, cw, t, size=10, line=LINE)
    bracket(y, LH, "赛题", "五项任务清单", "done")

    y = ys[1]
    tab(y, "编排层", INK)
    rect(s, PX, y, PW, LH, fill=MIST)
    items = ["JSON 任务卡", "任务调度器", "有限状态机 FSM", "技能库"]
    aw = 0.26
    bw = (iw - 3 * aw) / 4
    for i, t in enumerate(items):
        x = ix + i * (bw + aw)
        box(x, y + by, bw, t, size=10, heavy=True)
        if i < 3:
            _rarrow(s, x + bw + 0.04, y + LH / 2, aw - 0.08)

    y = ys[2]
    tab(y, "感知交互", INK)
    rect(s, PX, y, PW, LH, fill=MIST)
    gbw, gaw, ggap = 1.70, 0.26, 0.55
    xs = [ix, ix + gbw + gaw, ix + 2 * (gbw + gaw) + ggap,
          ix + 2 * (gbw + gaw) + ggap + gbw + gaw]
    for i, (x, t) in enumerate(zip(xs, ["单目相机", "视觉检测", "麦克风", "离线语音"])):
        box(x, y + by, gbw, t, size=10)
        if i in (0, 2):
            _rarrow(s, x + gbw + 0.04, y + LH / 2, gaw - 0.08)

    y = ys[3]
    tab(y, "控制层", BLUE)
    rect(s, PX, y, PW, LH, fill=MIST_2)
    ctrls = ["步态生成", "动作库回放", "视觉伺服", "姿态闭环·失稳保护"]
    cw4 = (iw - 3 * 0.10) / 4
    for i, t in enumerate(ctrls):
        box(ix + i * (cw4 + 0.10), y + by, cw4, t, size=9.5, heavy=True)

    bracket(ys[1], 2 * LH + LG, "大脑", "边缘计算板 · Linux", "done")
    bracket(ys[3], LH, "小脑", "STM32 + 6 轴 IMU", "doing")

    y = ys[4]
    tab(y, "执行层", "5B8FB9")
    rect(s, PX, y, PW, LH, fill=WHITE, line=LINE, line_w=0.75)
    box(ix, y + by, iw, "串行总线　→　22 路总线舵机（双腿 10 · 双臂 8 · 躯干 2 · 头部 2）",
        size=10, line=LINE)
    bracket(y, LH, "执行", "22 路串行总线", "plan")

    fy = ys[4] + LH + 0.12
    rect(s, CONTENT_X, fy, CONTENT_W, 0.70, fill=MIST)
    text(s, CONTENT_X + 0.22, fy + 0.04, CONTENT_W - 0.44, 0.22,
         [P([R("一次任务的 8 步通路", 9.5, BLUE, heavy=True)])])
    pipeline_strip(s, CONTENT_X + 0.22, fy + 0.24, CONTENT_W - 0.44,
                   ["相机出帧", "感知推理", "任务卡匹配", "FSM 流转",
                    "技能执行", "小脑解算", "总线下发", "IMU 反馈"],
                   h=0.28, size=8.5)
    text(s, CONTENT_X + 0.22, fy + 0.50, CONTENT_W - 0.44, 0.18,
         [P([R("注：第 1 步（取帧）与第 6–8 步当前尚无对应代码，为设计路径；第 2–5 步已实现。",
               7.5, GRAY)])])
    status_bar(s, ["done", "doing", "plan"])


def p18(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 18)
    page_title(s, "赛题约束基本合规；真正的风险在质量与力矩",
               lead="尺寸与电气逐条过检；但整机质量 3437 g，腿部关节力矩占官方连续额定 0.98 N·m 的 167%，已越过主判据，必须走减重路径。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 8.0, "167%", "腿部关节力矩 ／ 连续额定 0.98 N·m（主判据）",
           size=20, unit_size=12)
    headers = ["约束项", "大赛要求", "本项目设计", "余量"]
    rows = [
        ["高度", "≤ 60 cm", "41.8 cm（CAD 实装）", "+18.2 cm（占上限 70%）"],
        ["体宽", "≤ 30 cm", "19.0 cm", "+11.0 cm"],
        ["深度（自设参考）", "官方未列", "12.3 cm", "—"],
        ["臂长（单侧）", "≤ 30 cm", "9.57 cm（肩关节→夹爪末端直线距离）", "+20.4 cm"],
        ["关节数量", "总数 ≥18 / 每腿 ≥4 / 上肢+躯干 ≥10", "22 = 10 + 8 + 2 + 2", "上肢躯干 10 = 10，无余量"],
        ["传感配置", "IMU + 摄像头 + 麦克风 + 扬声器", "6 轴 IMU + 单目广角 + 环形麦 + 扬声器", "满足"],
        ["供电电压", "锂电池、≥ 7.4 V", "11.1 V 3S", "+3.7 V"],
        ["场地适配", "2400×2400 mm，含 5 个任务区域", "任务卡按区域编号切换技能", "满足"],
        ["整机质量", "官方未设上限", "3437 g（结构 1790〔CAD 实算〕+ 舵机 1210 + 电子件与电池 316 + 线束 120）", "超判据；减重后目标 2.2–2.7 kg"],
        ["腿部关节力矩", "官方未设上限", "1.629 N·m（CoP 25 mm × 动载 2.0）", "占连续额定 0.98 N·m 的 167% ❌（峰值 1.47 为 111%）"],
    ]
    table(s, CONTENT_X, Y_BODY + 0.42, CONTENT_W, headers, rows,
          col_w=[1.75, 3.40, 4.10, 2.42], row_h=0.26, head_h=0.26, size=8.5)
    ry = Y_BODY + 0.42 + 0.26 + 10 * 0.26 + 0.14
    rect(s, CONTENT_X, ry, CONTENT_W, 0.90, fill=WHITE, line=ORANGE, line_w=1.25)
    text(s, CONTENT_X + 0.24, ry + 0.08, CONTENT_W - 0.48, 0.76,
         [P([R("两处必须讲清楚：", 10.5, ORANGE, heavy=True)]),
          P([R("① 合规口径——", 9, ORANGE, heavy=True),
             R("官方若", 9, GRAPHITE), R("不把夹爪计入「上肢关节」", 9, ORANGE, heavy=True),
             R("，则上肢 + 躯干 = 3×2 + 2 = 8 < 10，直接不合格。我们的设计把夹爪（编号 17/21）计入上肢，此口径需向组委会书面确认。",
               9, GRAPHITE)], space_before=3, line_spacing=1.28),
          P([R("② 力矩余量——", 9, ORANGE, heavy=True),
             R("按 CAD 实装质量，腿部关节需要 1.629 N·m，占官方连续额定 0.98 N·m 的 167% ❌，峰值口径 1.47 N·m 也已到 111%。三条减重路径（A 拓扑 / B 买金属件 / C 减自由度）见 P49，可把峰值口径压到 73–90%，但连续额定口径仍超载——连续工况还需放缓步态或换更大扭矩舵机。",
               9, GRAPHITE)], space_before=2, line_spacing=1.28)])
    status_bar(s, ["design"])


def p19(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 19)
    page_title(s, "22 个关节，编号、限位、轴向、设计扭矩全部同源",
               lead="结构图由设计模型投影生成；右侧明细表逐行取自同一份模型。")

    # 左：真工程图（只保留正视图 + 侧视图；右侧合规框已裁出画面，合规结论以 P18 为准）
    dwg = DWG / "01_关节编号图-视图区.png"
    if dwg.exists():
        picture_cover(s, CONTENT_X, Y_BODY, 4.55, 3.18, str(dwg),
                      focus_x=0.5, focus_y=0.5)
    text(s, CONTENT_X, Y_BODY + 3.26, 4.55, 0.42,
         [P([R("22 关节编号图", 9.5, BLUE, heavy=True),
             R("　图号 ATRI-DWG-001", 8.5, GRAY)]),
          P([R("原图合规框未含臂长，本页不引用其结论（合规见 P18）。", 7.5, ORANGE)],
            space_before=2, line_spacing=1.25)])

    # 右：22 关节明细（原生表格，列全收录）
    rows = [
        ["00", "head_yaw", "−90 ~ +90", "Z", "1.0"],
        ["01", "head_pitch", "−45 ~ +45", "Y", "1.0"],
        ["02", "trunk_roll", "−10 ~ +10", "X", "2.0"],
        ["03", "trunk_pitch", "−15 ~ +15", "Y", "2.0"],
        ["04", "left_hip_yaw", "−45 ~ +45", "Z", "2.5"],
        ["05", "left_hip_roll", "−25 ~ +25", "X", "2.5"],
        ["06", "left_hip_pitch", "−60 ~ +60", "Y", "3.0"],
        ["07", "left_knee_pitch", "0 ~ +90", "Y", "3.0"],
        ["08", "left_ankle_pitch", "−40 ~ +40", "Y", "2.0"],
        ["09", "right_hip_yaw", "−45 ~ +45", "Z", "2.5"],
        ["10", "right_hip_roll", "−25 ~ +25", "X", "2.5"],
        ["11", "right_hip_pitch", "−60 ~ +60", "Y", "3.0"],
        ["12", "right_knee_pitch", "0 ~ +90", "Y", "3.0"],
        ["13", "right_ankle_pitch", "−40 ~ +40", "Y", "2.0"],
        ["14", "left_shoulder_pitch", "−90 ~ +90", "Y", "1.5"],
        ["15", "left_shoulder_roll", "−90 ~ +90", "X", "1.5"],
        ["16", "left_elbow_pitch", "−120 ~ 0", "Y", "1.0"],
        ["17", "left_gripper", "0 ~ +60", "Y", "0.4"],
        ["18", "right_shoulder_pitch", "−90 ~ +90", "Y", "1.5"],
        ["19", "right_shoulder_roll", "−90 ~ +90", "X", "1.5"],
        ["20", "right_elbow_pitch", "−120 ~ 0", "Y", "1.0"],
        ["21", "right_gripper", "0 ~ +60", "Y", "0.4"],
    ]
    rx, rw = 5.60, 6.90
    table(s, rx, Y_BODY, rw,
          ["#", "关节名", "限位（deg）", "轴向", "设计扭矩 N·m"],
          rows, col_w=[0.52, 2.62, 1.72, 0.68, 1.36],
          row_h=0.155, head_h=0.28, size=7.5, head_size=8.5)

    text(s, CONTENT_X, 5.96, CONTENT_W, 0.20,
         [P([R("代码里有三条断言强制校验：len(JOINTS) == 22 ｜ 关节 id 必须是 0..21 ｜ 分组自由度之和必须等于 22",
               8.5, BLUE, heavy=True)])])
    text(s, CONTENT_X, 6.18, CONTENT_W, 0.28,
         [P([R("口径：限位与轴向取自 design/robot_model.json（config.py::JOINTS 只有 id/group/limit/rest，无轴向）；"
               "「设计扭矩」为模型标称值；按 CAD 实装质量腿部关节需求 1.629 N·m，占连续额定 0.98 的 167%（峰值 111%），"
               "减重路径详见 P18 与 P49。", 8, GRAY)],
            line_spacing=1.25)])
    status_bar(s, ["done"])


def p20(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 20)
    page_title(s, "少掉的每一个自由度，都是一个主动的工程取舍",
               lead="这三条取舍的结果，就是 41.8 cm（CAD 实装）这组规格。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 6.0, "−2 个关节", "· 踝 1 DOF、无独立腕关节", size=20, unit_size=12)
    cards = [("踝关节只保留 1 个（俯仰）",
              [("收益", "省下重量、成本与结构复杂度"),
               ("代价", "侧向扰动容忍度下降。当前步态生成器里没有髋 roll 参与补偿，横向稳定依赖宽足距与实机整定")]),
             ("末端不设独立腕关节",
              [("收益", "减少 2 个关节，单侧臂长压到 9.57 cm"),
               ("代价", "抓取姿态受限，只能做「正对目标」的抓取"),
               ("目标", "只做桌面轻物抓取（≤100 g）")]),
             ("躯干保留 2 个自由度",
              [("收益", "给重心补偿留余量，行程 ±10° / ±15° 是微调量"),
               ("风险", "上肢 + 躯干 = 10 正好压线，口径需组委会确认（见 P18）")])]
    cw = (CONTENT_W - 0.60) / 3
    for i, (t, rows) in enumerate(cards):
        x = CONTENT_X + i * (cw + 0.30)
        rect(s, x, Y_BODY + 0.46, cw, 3.30, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, x, Y_BODY + 0.46, cw, 0.045, fill=ORANGE)
        text(s, x + 0.26, Y_BODY + 0.72, cw - 0.52, 0.60,
             [P([R(t, 13, INK, heavy=True)], line_spacing=1.25)])
        hline(s, x + 0.26, Y_BODY + 1.38, cw - 0.52, color=BLUE_300, width=1.0)
        yy = Y_BODY + 1.54
        for lab, txt in rows:
            text(s, x + 0.26, yy, cw - 0.52, 0.22,
                 [P([R(lab, 9.5, BLUE, heavy=True)])])
            text(s, x + 0.26, yy + 0.24, cw - 0.52, 0.76,
                 [P([R(txt, 10, GRAPHITE)], line_spacing=1.40)])
            yy += 1.06
    status_bar(s, ["design"])


def p21(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 21)
    page_title(s, "一个任务六个状态，非法跳转直接报错",
               lead="状态机保证任务不会走到一半状态不明。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 3.0, "6", "个状态", size=24, unit_size=12)
    fsm_diagram(s, CONTENT_X, Y_BODY + 0.46, CONTENT_W, 1.95)
    yy = 4.66
    h = code_block(s, CONTENT_X, yy, 6.55, [
        "_TRANSITIONS = {",
        "    FSMState.STANDBY:   {FSMState.ENTERING},",
        "    FSMState.ENTERING:  {FSMState.EXECUTING, FSMState.ERROR},",
        "    FSMState.EXECUTING: {FSMState.FEEDBACK,  FSMState.ERROR},",
        "    FSMState.FEEDBACK:  {FSMState.DONE,      FSMState.ERROR},",
        "    FSMState.DONE: set(), FSMState.ERROR: set(),",
        "}",
    ], size=9)
    rx, rw = 7.75, 4.75
    rect(s, rx, yy, rw, h, fill=WHITE, line=LINE, line_w=0.75)
    text(s, rx + 0.26, yy + 0.20, rw - 0.52, h - 0.40,
         [P([R("设计要点", 10.5, INK, heavy=True)]),
          P([R("异常收敛到 ERROR，并保留完整 history——走过的每一个状态都记录在案，便于复盘。",
               10, GRAPHITE)], space_before=6, line_spacing=1.40),
          P([R("非法跳转（例如 STANDBY 直接到 DONE）会抛 FSMError，不允许静默通过。",
               10, GRAPHITE)], space_before=6, line_spacing=1.40)])
    status_bar(s, ["done"])


def p22(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 22)
    page_title(s, "换一项任务，换一个 JSON 文件",
               lead="任务变成数据，调度交给引擎。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 5.0, "5 张任务卡", "· 每张 5 行", size=22, unit_size=12)
    yy = Y_BODY + 0.46
    code_block(s, CONTENT_X, yy, CONTENT_W, [
        'T-01 人脸识别    {"skills":["face"],  "params":{"face_db":"config/face_db.json",',
        '                  "expect_names":["测试员A","测试员B"], "tts":true}, "timeout_s":60}',
        'T-02 二维码循迹  {"skills":["qr"],    "params":{"default_payload":{"action":"walk","steps":3}},',
        '                  "timeout_s":60}',
        'T-03 物品搬运    {"skills":["carry"], "params":{"target":"红块","distance_cm":8.0}, "timeout_s":90}',
        'T-04 体育运动    {"skills":["kick"],  "params":{}, "timeout_s":60}',
        'T-05 娱乐交互    {"skills":["dance"], "params":{"keyword":"跳舞","bars":2}, "timeout_s":60}',
    ], size=8.5, lh=0.195)
    ry = Y_BODY + 2.10
    rect(s, CONTENT_X, ry, CONTENT_W, 0.92, fill=MIST)
    text(s, CONTENT_X + 0.24, ry + 0.14, CONTENT_W - 0.48, 0.64,
         [P([R("字段规范", 10.5, BLUE, heavy=True)]),
          P([R("必填 task_id / name / skills；可选 params / timeout_s（默认 120 秒）。"
               "skills 必须非空列表；技能名合法性校验见 P23；timeout_s 必须是数字。"
               "违反任一条抛 TaskCardError，不允许带病启动。",
               9.5, GRAPHITE)], space_before=5, line_spacing=1.35)])
    status_bar(s, ["done"])


def p23(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 23)
    page_title(s, "五个技能共用一个接口",
               lead="技能之间互不知道对方存在，都只跟 ctx 打交道。")
    lx, lw = CONTENT_X, 4.60
    rect(s, lx, Y_BODY, lw, 0.42, fill=INK)
    text(s, lx, Y_BODY, lw, 0.42,
         [P([R("Skill（基类：name + run(ctx)）", 11, WHITE, heavy=True)],
            align=PP_ALIGN.CENTER)], anchor=MSO_ANCHOR.MIDDLE)
    for i, t in enumerate(["FaceSkill", "QRCodeSkill", "CarrySkill", "KickSkill", "DanceSkill"]):
        x = lx + i * (0.88 + 0.05)
        rect(s, x, Y_BODY + 0.56, 0.88, 0.44, fill=WHITE, line=BLUE_300, line_w=0.75)
        text(s, x, Y_BODY + 0.56, 0.88, 0.44,
             [P([R(t, 7.5, INK, heavy=True)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)
    rect(s, lx, Y_BODY + 1.18, lw, 2.42, fill=MIST)
    text(s, lx + 0.26, Y_BODY + 1.38, lw - 0.52, 2.06,
         [P([R("SkillContext 提供的四样东西", 10.5, BLUE, heavy=True)]),
          P([R("params　任务卡传来的业务参数", 10, GRAPHITE)], space_before=10),
          P([R("perception　感知后端（可替换）", 10, GRAPHITE)], space_before=6),
          P([R("cerebellum　运动控制接口", 10, GRAPHITE)], space_before=6),
          P([R("tts_engine　语音播报接口", 10, GRAPHITE)], space_before=6)])
    rx, rw = 5.90, 6.60
    rect(s, rx, Y_BODY, rw, 0.42, fill=ORANGE)
    text(s, rx, Y_BODY, rw, 0.42,
         [P([R("新增一个技能要改三处（诚实版）", 11, WHITE, heavy=True)],
            align=PP_ALIGN.CENTER)], anchor=MSO_ANCHOR.MIDDLE)
    steps = [("1", "写一个类继承 Skill，实现 run(ctx)"),
             ("2", "在 Brain.skills 里注册"),
             ("3", "把技能名加进 task_card.py 的 VALID_SKILLS——这是一个冻结集合，不加会被 TaskCardError: unknown skills 拦下")]
    y = Y_BODY + 0.60
    for no, t in steps:
        rect(s, rx, y, rw, 0.86, fill=WHITE, line=LINE, line_w=0.75)
        text(s, rx + 0.24, y, 0.40, 0.86,
             [P([R(no, 15, ORANGE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, rx + 0.78, y, rw - 1.02, 0.86,
             [P([R(t, 10, GRAPHITE)], line_spacing=1.35)], anchor=MSO_ANCHOR.MIDDLE)
        y += 0.96
    rect(s, rx, y, rw, 0.72, fill=WHITE, line=ORANGE, line_w=1.0)
    text(s, rx + 0.24, y, rw - 0.48, 0.72,
         [P([R("已知缺陷：", 10, ORANGE, heavy=True),
             R("白名单里的 idle 没有对应实现，运行时会抛「未注册的技能: idle」。"
               "修法是把 VALID_SKILLS 改为由 Brain.skills.keys() 动态派生（约 5 行）。",
               9.5, GRAPHITE)], line_spacing=1.35)], anchor=MSO_ANCHOR.MIDDLE)
    status_bar(s, ["done", "plan"])


def p24(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 24)
    page_title(s, "步态是每个周期现算出来的 40 帧关节角序列",
               lead="摆动腿与支撑腿相差半个相位。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 4.0, "40 帧", "/ 周期 · 20 ms 控制周期",
           size=22, unit_size=12)
    gait_phase(s, CONTENT_X + 0.75, Y_BODY + 0.58, 5.20, 1.50)
    text(s, CONTENT_X, Y_BODY + 2.26, 6.20, 0.22,
         [P([R("步态相位图：左腿（深蓝）与右腿（浅蓝）正弦相位相差 π", 9, GRAY)])])
    rx, rw = 7.05, 5.45
    text(s, rx, Y_BODY - 0.24, rw, 0.22,
         [P([R("参数取自 config/robot.json::motion.gait", 8.5, GRAY)])])
    headers = ["参数", "当前值", "含义"]
    rows = [["步长系数", "2.0", "生成公式的线性系数（隐含 4°/cm）"],
            ["抬脚系数", "1.2", "生成公式的线性系数（隐含 12°/cm）"],
            ["步态周期", "0.8 s", "一个完整左右交替周期"],
            ["控制周期", "20 ms", "每周期采样 40 帧"],
            ["6 步总帧数", "240 帧", "6 × 40"]]
    table(s, rx, Y_BODY, rw, headers, rows, col_w=[1.40, 1.05, 3.00],
          row_h=0.36, head_h=0.32, size=9.5)
    yy = Y_BODY + 2.56
    code_block(s, CONTENT_X, yy, CONTENT_W, [
        "phase = 2.0 * math.pi * t",
        "left_amp  = max(0.0, math.sin(phase))",
        "right_amp = max(0.0, math.sin(phase + math.pi))",
        'frame = {"left_hip_pitch":   8.0 * left_amp  * step_length_cm / 2.0,',
        '         "left_knee_pitch": 12.0 * left_amp  * step_height_cm,',
        '         "left_ankle_pitch": -6.0 * left_amp,',
        '         "trunk_pitch": 1.5 * math.sin(phase),',
        '         "trunk_roll":  1.0 * math.sin(phase / 2.0)}',
    ], size=8, lh=0.168)
    status_bar(s, ["done", "plan"])


def p25(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 25)
    page_title(s, "仿真里标定出来的动作，能原样搬到实机上",
               lead="动作和代码解耦——调一个动作不需要改 Python，只需要改 JSON。")
    pipeline_strip(s, CONTENT_X, Y_BODY, CONTENT_W,
                   ["Webots 标定", "导出关键帧 JSON", "动作库校验",
                    "play_action() 回放", "实机迁移"], h=0.50, size=10)
    headers = ["字段", "约束"]
    rows = [["schema_version", '必须为 "1.0"'],
            ["action_id", "不能为空"],
            ["frames", "非空数组"],
            ["frames[i].duration_s", "必须大于 0"],
            ["frames[i].joints", "键必须来自 22 个合法关节名"]]
    table(s, CONTENT_X, Y_BODY + 0.72, 6.05, headers, rows,
          col_w=[2.35, 3.70], row_h=0.36, head_h=0.32, size=9.5)
    rx, rw = 7.25, 5.25
    rect(s, rx, Y_BODY + 0.72, rw, 1.90, fill=WHITE, line=LINE, line_w=0.75)
    text(s, rx + 0.24, Y_BODY + 0.90, rw - 0.48, 1.54,
         [P([R("为什么这样设计", 10.5, INK, heavy=True)]),
          P([R("动作与代码解耦：调一个动作只改 JSON，并跑一遍校验器。"
               "校验不通过的动作库不会被回放，避免把坏数据灌进舵机。",
               10, GRAPHITE)], space_before=6, line_spacing=1.40)])
    ry = Y_BODY + 2.80
    rect(s, CONTENT_X, ry, CONTENT_W, 1.34, fill=MIST)
    text(s, CONTENT_X + 0.26, ry + 0.16, CONTENT_W - 0.52, 1.02,
         [P([R("姿态闭环与失稳保护", 10.5, BLUE, heavy=True),
             R("　○ 规划中", 9.5, GRAY)]),
          P([R("控制周期 20 ms 读一次姿态；倾角超阈值立即切断舵机扭矩；落地瞬间不做姿态修正，避免震荡；"
               "上电自检逐路读取舵机位置与预期位姿比对。以上均为设计，尚无代码与实测。",
               9.5, GRAPHITE)], space_before=6, line_spacing=1.40)])
    status_bar(s, ["done", "plan"])


def p26(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 26)
    page_title(s, "上层技能代码不知道底下用的是 Mock 还是真摄像头",
               lead="无硬件时用 Mock 跑通全链路；有硬件时换一个后端对象，上层一行代码不改。")
    rect(s, CONTENT_X, Y_BODY, 4.30, 0.44, fill=INK)
    text(s, CONTENT_X, Y_BODY, 4.30, 0.44,
         [P([R("PerceptionBackend（抽象）", 11, WHITE, heavy=True)],
            align=PP_ALIGN.CENTER)], anchor=MSO_ANCHOR.MIDDLE)
    for i, t in enumerate(["MockPerception", "OpenCVPerception"]):
        x = CONTENT_X + i * (2.10 + 0.10)
        rect(s, x, Y_BODY + 0.62, 2.10, 0.50, fill=WHITE, line=BLUE_300, line_w=0.75)
        text(s, x, Y_BODY + 0.62, 2.10, 0.50,
             [P([R(t, 10, INK, heavy=True)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)
    rect(s, CONTENT_X, Y_BODY + 1.32, 4.30, 1.30, fill=MIST)
    text(s, CONTENT_X + 0.26, Y_BODY + 1.50, 3.78, 0.94,
         [P([R("统一返回结构", 10, BLUE, heavy=True)]),
          P([R("PerceptionResult", 9.5, INK, heavy=True)], space_before=4),
          P([R("(kind, data, confidence, raw)", 8.5, GRAY)], space_before=3)])
    headers = ["方法", "返回"]
    rows = [["detect_face(frame)", "{found, bbox} + confidence"],
            ["detect_qr(frame)", "{found, payload} + confidence"],
            ["detect_ball(frame)", "{found, x_cm, distance_cm, bbox, center_px}"]]
    table(s, 5.60, Y_BODY, 6.90, headers, rows, col_w=[2.30, 4.60],
          row_h=0.44, head_h=0.34, size=9.5)
    rect(s, 5.60, Y_BODY + 1.90, 6.90, 1.36, fill=WHITE, line=LINE, line_w=0.75)
    text(s, 5.84, Y_BODY + 2.06, 6.42, 1.04,
         [P([R("设计要点", 10.5, INK, heavy=True)]),
          P([R("raw 保留后端原始返回值（OpenCV 的 points / contour），便于替换算法与排查误检。",
               10, GRAPHITE)], space_before=6, line_spacing=1.40)])
    status_bar(s, ["done"])


def p27(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 27)
    page_title(s, "三种目标，三套方法，参数写死以便复现",
               lead="三路检测共用同一个返回结构，所以上层技能只写一次调用逻辑。")
    headers = ["", "人脸", "二维码", "球"]
    rows = [["原理", "Haar Cascade 检测", "QRCodeDetector\ndetectAndDecode", "HSV 颜色分割\n+ 最大轮廓"],
            ["预处理", "转灰度 + 直方图均衡", "内置透视矫正", "inRange 二值化"],
            ["关键参数", "scaleFactor=1.1\nminNeighbors=5\nminSize=30×30",
             "解码结果按 JSON 解析\n失败原样返回字符串",
             "绿区间 (35,80,80)–(85,255,255)\nRETR_EXTERNAL 取最大轮廓"],
            ["输出", "bbox + confidence", "结构化 payload", "x_cm / distance_cm\nbbox / center_px"],
            ["测距", "—", "—", "针孔模型 d = D·f / d_px"]]
    table(s, CONTENT_X, Y_BODY, CONTENT_W, headers, rows,
          col_w=[1.35, 3.25, 3.55, 3.52], row_h=0.60, head_h=0.32, size=8.5)
    ry = Y_BODY + 0.34 + 5 * 0.60 + 0.16
    rect(s, CONTENT_X, ry, CONTENT_W, 0.86, fill=WHITE, line=ORANGE, line_w=1.0)
    text(s, CONTENT_X + 0.24, ry + 0.10, CONTENT_W - 0.48, 0.78,
         [P([R("必须说明：", 10.5, ORANGE, heavy=True),
             R("detect_face 只返回人脸位置，不返回身份", 10, ORANGE, heavy=True),
             R("——身份识别需要单独的特征比对模块，见 P34。", 10, GRAPHITE)]),
          P([R("cv2 为懒加载可选依赖，CI 默认不装；三路检测均未做真实摄像头实测。",
               9, GRAY)], space_before=4)])
    status_bar(s, ["done", "plan"])


def p28(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 28)
    page_title(s, "闭环控制律已经跑出收敛序列，缺的是把它搬进技能层",
               lead="设计数据包里有一个可复现的闭环；技能层目前还是一次开环修正。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 6.4, "12/12 · 9/12 · 4/12",
           "带噪感知下的成功数（ideal / harsh / adversarial）", size=19, unit_size=11)

    # 左：技能层现状
    lx, lw = CONTENT_X, 5.55
    text(s, lx, Y_BODY + 0.46, lw, 0.22,
         [P([R("技能层 kick.py：一次开环修正", 10.5, ORANGE, heavy=True)])])
    code_block(s, lx, Y_BODY + 0.72, lw, [
        'obs = ctx.perceive("ball")        # 只检测一次',
        "if abs(ball_x) > 1.0:             # 单次判断",
        "    yaw = max(-10.0, min(10.0, ball_x / 2.0))",
        '    ctx.cerebellum.set_pose({"left_hip_yaw": yaw, ...})',
        "ctx.cerebellum.kick(...)",
    ], size=8.5, lh=0.19)
    text(s, lx, Y_BODY + 1.88, lw, 0.50,
         [P([R("没有 while，没有二次检测，没有收敛判据。", 9.5, ORANGE)],
            line_spacing=1.32),
          P([R("±10° 限幅在任务区间内几乎总是饱和：球距 10 cm 时 |x|>1.76 cm 即饱和，"
               "20 cm 时 >3.53 cm 即饱和——单次修正不可能收敛，这是几何决定的。",
               8.5, GRAY)], space_before=4, line_spacing=1.30)])

    # 右：设计数据包里的真闭环
    rx, rw = 6.85, 5.65
    text(s, rx, Y_BODY + 0.46, rw, 0.22,
         [P([R("设计数据包 run_sim.py：真闭环（已实现）", 10.5, GREEN, heavy=True)])])
    code_block(s, rx, Y_BODY + 0.72, rw, [
        "while 迭代 < max_iter 且 未超时:",
        "    obs = 重新检测球位",
        "    if |x| <= tol_cm: break      # 收敛出口",
        "    yaw = clamp(gain * x, ±max_step)",
        "    调整朝向；振荡则自动降增益",
    ], size=8.5, lh=0.19, fill=MIST_2)
    text(s, rx, Y_BODY + 1.88, rw, 0.24,
         [P([R("实测收敛序列", 9.5, GREEN, heavy=True),
             R("　seed 20260910 · 与 design/README.md §5.1 同源", 8, GRAY)])])
    headers = ["初始偏移", "轮次", "误差序列", "末误差"]
    rows = [["5.0 cm", "4", "5.00 → 2.42 → 1.45 → 0.38", "0.38"],
            ["12.0 cm", "6", "12.00 → 7.92 → 4.20 → 1.76 → 1.48 → 0.48", "0.48"],
            ["20.0 cm", "7", "20.00 → 15.92 → 12.16 → 7.82 → 4.50 → 1.99 → 0.35", "0.35"]]
    table(s, rx, Y_BODY + 2.10, rw, headers, rows,
          col_w=[0.95, 0.62, 3.20, 0.88], row_h=0.38, head_h=0.28, size=8)

    ry = Y_BODY + 3.56
    rect(s, CONTENT_X, ry, CONTENT_W, 0.84, fill=WHITE, line=GREEN, line_w=1.25)
    text(s, CONTENT_X + 0.24, ry + 0.10, CONTENT_W - 0.48, 0.66,
         [P([R("鲁棒性边界：", 10, GREEN, heavy=True),
             R("python3 design/run_sim.py --sweep perception --episodes 12 "
               "→ ideal 12/12 ｜ nominal 12/12 ｜ harsh 9/12 ｜ adversarial 4/12",
               9.5, GRAPHITE)]),
          P([R("这是本项目唯一的量化证据：它给出的是失效边界，而不只是「能跑」。"
               "当前缺口是移植——把这段循环搬进 skills/kick.py，不是从零写。",
               9, GRAY)], space_before=4)])
    status_bar(s, ["done", "doing"])


def p29(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 29)
    page_title(s, "语音是接口不是依赖；工程质量是可查的",
               lead="下面四项都可以当场执行复现。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 6.0, "169 项测试", "· 核心 0 第三方依赖",
           size=22, unit_size=12)
    cards = [("核心零第三方依赖",
              "atri 包全部 import 只有 abc / argparse / dataclasses / enum / json / math / "
              "pathlib / subprocess / sys / time / typing；cv2、qrcode 为懒加载可选依赖。"),
             ("169 项测试 · 构成拆开说",
              "软件行为 51 项 + 设计模型 / 工程图 / 几何断言 82 项（占 61.7%）。"
              "软件行为部分覆盖 FSM / 任务卡 / 技能 / 感知 / 语音 / 动作库 / 配置。"),
             ("CI 自动验证",
              "GitHub Actions 在 Python 3.14 上跑编译 + 测试 + 无硬件闭环演示。"),
             ("协作规范",
              "改前 pull、小步 commit、禁 force push、功能分支；设计与代码同源。")]
    cw = (CONTENT_W - 0.60) / 2
    for i, (t, d) in enumerate(cards):
        x = CONTENT_X + (i % 2) * (cw + 0.30)
        y = Y_BODY + 0.46 + (i // 2) * 1.22
        rect(s, x, y, cw, 1.10, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, x, y, 0.045, 1.10, fill=GREEN)
        text(s, x + 0.26, y + 0.16, cw - 0.50, 0.26,
             [P([R(t, 11.5, INK, heavy=True)])])
        text(s, x + 0.26, y + 0.46, cw - 0.50, 0.56,
             [P([R(d, 9.5, GRAPHITE)], line_spacing=1.35)])
    yy = Y_BODY + 2.92
    h = code_block(s, CONTENT_X, yy, 6.60, [
        "$ python3 -m unittest discover -s tests",
        "Ran 169 tests in 1.6s",
        "OK",
        "",
        "$ python3 run_demo.py --fast",
        "闭环演示完成: 5/5 项任务通过",
    ], size=9, lh=0.185)
    rx, rw = 7.80, 4.70
    rect(s, rx, yy, rw, h, fill=WHITE, line=ORANGE, line_w=1.0)
    text(s, rx + 0.24, yy + 0.16, rw - 0.48, h - 0.32,
         [P([R("语音链路的当前状态", 10.5, ORANGE, heavy=True)]),
          P([R("KeywordRecognizer 与 TTS 均为抽象接口，现有 Mock 实现保证演示可复现。"
               "VoiceService 尚未接入 Brain；", 9.5, GRAPHITE)],
            space_before=6, line_spacing=1.38),
          P([R("全仓无音频播放代码", 9.5, ORANGE, heavy=True),
             R("，「音乐播放」为设计目标。", 9.5, GRAPHITE)],
            space_before=3, line_spacing=1.38)])
    status_bar(s, ["done"])


def p30(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 30)
    page_title(s, "同一份代码，三个后端",
               lead="单个平台受阻时，另外两个继续推进。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 6.0, "1 份代码", "· 3 个后端", size=22, unit_size=13)
    cx = CONTENT_X + CONTENT_W / 2
    rect(s, cx - 4.20, Y_BODY + 0.46, 8.40, 0.86, fill=INK)
    text(s, cx - 4.20, Y_BODY + 0.46, 8.40, 0.86,
         [P([R("atri 包", 15, WHITE, heavy=True)], align=PP_ALIGN.CENTER),
          P([R("Brain / FSM / Skills / Perception 接口 / Cerebellum", 9.5, BLUE_300)],
            align=PP_ALIGN.CENTER, space_before=3)], anchor=MSO_ANCHOR.MIDDLE)
    _seg(s, cx, Y_BODY + 1.32, cx, Y_BODY + 1.62, BLUE, 1.2)
    text(s, cx + 0.12, Y_BODY + 1.34, 4.8, 0.26,
         [P([R("只换这一个实现（Cerebellum 支持注入 sleeper）", 9.5, BLUE, heavy=True)])])
    bk = [("MockServoBus", "内存舵机", "done", GREEN, "无硬件即可跑通全链路"),
          ("WebotsServoBus", "robot.step + 电机", "doing", ORANGE,
           "atri_22dof.wbt（零重力运动学世界）+ 19 项离线桩测试；"
           "标定的是关节角序列与调度时序，不含重力与接触"),
          ("SerialServoBus", "串口总线", "plan", GRAY, "样机阶段接入")]
    bw = 3.70
    for i, (name, sub, kind, col, note) in enumerate(bk):
        x = CONTENT_X + i * (bw + 0.28)
        _seg(s, x + bw / 2, Y_BODY + 1.62, x + bw / 2, Y_BODY + 1.86, BLUE, 1.2)
        rect(s, x, Y_BODY + 1.86, bw, 1.50, fill=WHITE, line=col, line_w=1.25)
        text(s, x + 0.22, Y_BODY + 2.02, bw - 0.44, 0.28,
             [P([R(name, 11.5, INK, heavy=True)])])
        text(s, x + 0.22, Y_BODY + 2.32, bw - 0.44, 0.24,
             [P([R(sub, 9, GRAY)])])
        status_chip(s, x + 0.22, Y_BODY + 2.64, kind, size=9.5)
        text(s, x + 0.22, Y_BODY + 3.00, bw - 0.44, 0.30,
             [P([R(note, 8.5, GRAPHITE)], line_spacing=1.25)])
    rect(s, CONTENT_X, 5.86, CONTENT_W, 0.62, fill=MIST)
    text(s, CONTENT_X + 0.24, 5.86, CONTENT_W - 0.48, 0.62,
         [P([R("口径：", 9.5, BLUE, heavy=True),
             R("仿真为运动学/解析验证（simulation: kinematic-analytical），"
               "不是物理动力学仿真；动力学参数标定列入阶段三。", 9.5, GRAPHITE)])],
         anchor=MSO_ANCHOR.MIDDLE)
    status_bar(s, ["done", "doing", "plan"])


def p31(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 31)
    page_title(s, "六项真能执行的产物，每条都附命令",
               lead="后面所有的「规划中」，都建立在这六项之上。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 3.4, "6 项", "可执行产物", size=22, unit_size=12)
    rect(s, CONTENT_X, Y_BODY + 0.42, CONTENT_W, 0.92, fill=MIST_2, line=BLUE, line_w=1.0)
    text(s, CONTENT_X + 0.24, Y_BODY + 0.54, 7.40, 0.70,
         [P([R("视觉伺服闭环 + 鲁棒性边界", 13, INK, heavy=True)]),
          P([R("python3 design/run_sim.py --sweep perception --episodes 12", 9, GRAPHITE)],
            space_before=4)])
    text(s, CONTENT_X + 7.85, Y_BODY + 0.54, 3.80, 0.70,
         [P([R("12/12 · 12/12 · 9/12 · 4/12", 13, ORANGE, heavy=True)], align=PP_ALIGN.RIGHT),
          P([R("ideal / nominal / harsh / adversarial", 8, GRAY)],
            align=PP_ALIGN.RIGHT, space_before=2)], anchor=MSO_ANCHOR.MIDDLE)
    rows = [["169 项测试 + 三版本 CI", "python3 -m unittest discover -s tests　→ Ran 169 tests … OK"],
            ["五项任务无硬件闭环演示", "python3 run_demo.py --fast　→ 闭环演示完成: 5/5 项任务通过"],
            ["22 关节设计模型与 URDF", "design/robot_model.json；python3 design/gen_urdf.py"],
            ["4 张工程图（编号 / 三视图 / 尺寸链 / 舵机布局）", "design/drawings/　图号 001 / 002 / 004 / 005，第 3 张暂缺"],
            ["22 DOF Webots 运动学联调", "webots/worlds/atri_22dof.wbt；19 项离线桩测试（完整运行需 Windows + Webots R2025a）"]]
    table(s, CONTENT_X, Y_BODY + 1.46, CONTENT_W, ["已完成的产物", "查证方式 / 路径"],
          rows, col_w=[5.30, 6.37], row_h=0.46, head_h=0.34, size=9.5)
    status_bar(s, ["done"])


# ═══════════════════════════════════════════════════════════════════
# 第四章 五项任务闭环
# ═══════════════════════════════════════════════════════════════════
def p32(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "04", "五项赛题，五条实现路径，同一套底座",
                 "五项任务闭环 · P32–P39")


def p33(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "04", "五项任务闭环", 33)
    page_title(s, "赛题要求 → 实现路径 → 考核指标 → 当前状态",
               lead="标记为「待开发」的三处是流程中尚未实现真实感知或执行的环节，逐项在 P34–P38 说明。")
    rows = [["人脸识别", "采集 → 人脸检测 → 身份比对待开发 → 本地 TTS 播报", "成功率 ≥90%（≤1.5 m）", "◐"],
            ["二维码循迹", "捕获 → 透视矫正 → 解码 JSON → FSM 调度前进/转向", "识别 ≥90%；指令执行 ≥95%", "◐"],
            ["物品搬运", "目标检测待开发 → 视觉对齐 → 夹爪闭合 → 平移 → 释放", "抓取成功率 ≥80%（≤100 g）", "◐"],
            ["体育运动", "检测球位 → 朝向伺服 → 腿部踢球", "踢球成功率 ≥70%（10–20 cm）", "◐"],
            ["娱乐休闲", "离线关键词 → 音频播放待开发 → 22 DOF 短舞序列", "连续执行完成度 100%", "◐"]]
    table(s, CONTENT_X, Y_BODY + 0.16, CONTENT_W, ["赛题任务", "实现路径", "考核指标（目标值）", "状态"],
          rows, col_w=[1.65, 6.10, 3.35, 0.57], row_h=0.62, head_h=0.34, size=10)
    yy = Y_BODY + 0.34 + 5 * 0.62 + 0.16
    rect(s, CONTENT_X, yy, CONTENT_W, 0.62, fill=MIST)
    text(s, CONTENT_X + 0.24, yy, CONTENT_W - 0.48, 0.62,
         [P([R("五项任务的软件流程都已在无硬件闭环演示中跑通（5/5）；考核指标为目标值，实机指标全部待测。",
               10.5, GRAPHITE)])], anchor=MSO_ANCHOR.MIDDLE)
    status_bar(s, ["doing"])


def progress_bar(slide, x, y, w, n_done, n_total, label=""):
    """完成度条：让连翻五页的读者看到一条起伏的进度，而不是一排空心圆。"""
    seg = (w - (n_total - 1) * 0.06) / n_total
    for i in range(n_total):
        rect(slide, x + i * (seg + 0.06), y, seg, 0.13,
             fill=GREEN if i < n_done else MIST_2)
    text(slide, x + w + 0.14, y - 0.06, 1.30, 0.26,
         [P([R(f"{n_done}/{n_total}", 12, GREEN if n_done else GRAY, heavy=True)])])


def _task_page(prs, page_no, title, lead, accent_num, accent_unit,
               flow, done, todo, metric, metric_note, status, vis_note,
               n_done=0, n_total=1, bar_label=""):
    s = add_slide(prs, PAPER)
    page_frame(s, "04", "五项任务闭环", page_no)
    page_title(s, title, lead=lead)
    accent(s, CONTENT_X, Y_BODY - 0.06, 4.2, accent_num, accent_unit,
           size=22, unit_size=12)
    text(s, CONTENT_X + 4.55, Y_BODY - 0.02, 2.6, 0.22,
         [P([R("实现完成度", 9, GRAY)])])
    progress_bar(s, CONTENT_X + 4.55, Y_BODY + 0.24, 2.60, n_done, n_total, bar_label)
    lx, lw = CONTENT_X, 4.55
    rect(s, lx, Y_BODY + 0.44, lw, 3.42, fill=MIST)
    text(s, lx + 0.24, Y_BODY + 0.62, lw - 0.48, 0.24,
         [P([R("① 流程链", 10, BLUE, heavy=True)])])
    yy = Y_BODY + 0.94
    for i, step in enumerate(flow):
        rect(s, lx + 0.24, yy, lw - 0.48, 0.40, fill=WHITE, line=BLUE_300, line_w=0.75)
        text(s, lx + 0.34, yy, lw - 0.68, 0.40,
             [P([R(step, 9.5, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        if i < len(flow) - 1:
            text(s, lx + lw / 2 - 0.12, yy + 0.38, 0.24, 0.20,
                 [P([R("↓", 9, BLUE)], align=PP_ALIGN.CENTER)])
        yy += 0.57
    text(s, lx + 0.24, Y_BODY + 3.58, lw - 0.48, 0.24,
         [P([R(vis_note, 8, GRAY)])])

    rx, rw = 5.72, 6.78
    impl_status(s, rx, Y_BODY + 0.44, rw, done, todo)
    my = Y_BODY + 3.30
    rect(s, rx, my, rw, 0.62, fill=WHITE, line=ORANGE, line_w=1.0)
    text(s, rx + 0.22, my + 0.05, rw - 0.44, 0.52,
         [P([R("③ 考核指标　", 9.5, BLUE, heavy=True),
             R(metric, 12, ORANGE, heavy=True)]),
          P([R(metric_note, 8.5, GRAY)], space_before=2)])
    status_bar(s, [status])
    return s


def p34(prs):
    _task_page(prs, 34, "当前只能看到「这里有一张脸」，认人还差一步",
               "四步链路里，第一步已经跑通。", "人脸检测", "已可用",
               ["摄像头采集", "人脸检测", "特征比对（未实现）", "TTS 播报"],
               ["OpenCVPerception.detect_face() 用 Haar Cascade 返回 bbox + 置信度",
                "TTS 播报链路可用（Mock / macOS say）"],
               ["config/face_db.json 从未被任何代码加载",
                "detect_face 不返回姓名；FaceSkill 取不到时回落到任务卡的默认名，置信度写死 0.93",
                "现有 face_db.json 只有 2 条、4 维手写向量，不足以支撑识别"],
               "识别成功率 ≥ 90%", "固定光照、≤1.5 m；当前无实测",
               "doing", "视觉：config/face_db.json 真实内容 + PerceptionResult 字段",
               n_done=1, n_total=4)


def p35(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "04", "五项任务闭环", 35)
    page_title(s, "二维码不只是位置标签，它本身是一段指令",
               lead="现场改路径 = 换一张二维码贴纸，不用刷机、不用重编译。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 4.2, '{"action":"walk","steps":3}',
           "", size=17)
    text(s, CONTENT_X + 4.55, Y_BODY - 0.02, 2.6, 0.22,
         [P([R("实现完成度", 9, GRAY)])])
    progress_bar(s, CONTENT_X + 4.55, Y_BODY + 0.24, 2.60, 3, 5)
    lx, lw = CONTENT_X, 4.20
    rect(s, lx, Y_BODY + 0.50, lw, 3.36, fill=WHITE, line=LINE, line_w=0.75)
    qr = REPO / "软件" / "atri" / "qr_samples" / "qr_walk_steps3.png"
    if qr.exists():
        s.shapes.add_picture(str(qr), Inches(lx + 1.02), Inches(Y_BODY + 0.78),
                             width=Inches(2.16), height=Inches(2.16))
    text(s, lx + 0.24, Y_BODY + 3.06, lw - 0.48, 0.24,
         [P([R("qr_samples/qr_walk_steps3.png", 8.5, GRAY)], align=PP_ALIGN.CENTER)])
    text(s, lx + 0.24, Y_BODY + 3.30, lw - 0.48, 0.36,
         [P([R("真二维码样例 · 解码得 walk / steps=3", 9, BLUE, heavy=True)],
            align=PP_ALIGN.CENTER)])
    rx, rw = 5.40, 7.10
    impl_status(s, rx, Y_BODY + 0.50, rw, [
        "指令内嵌：二维码内容就是 JSON，支持 walk（带 steps）与 turn（带 deg）",
        "生成器：python3 -m atri.qrgen --action walk --steps 3 --output qr_walk.png",
        "qr_samples/ 下已有 3 张真实样例码（walk / turn / dance）",
    ], [
        "真实摄像头取帧与解码路径一次都没执行过；本机未装 cv2，解码逻辑仅由 fake cv2 单元测试覆盖",
        "turn 指令当前用 set_pose(hip_yaw) 实现（转向问题见 P28）；超过 135° 会被静默限幅",
    ])
    my = Y_BODY + 2.90
    rect(s, rx, my, rw, 0.96, fill=WHITE, line=ORANGE, line_w=1.0)
    text(s, rx + 0.22, my + 0.12, rw - 0.44, 0.72,
         [P([R("③ 考核指标　", 9.5, BLUE, heavy=True),
             R("识别 ≥90%　指令执行 ≥95%", 12, ORANGE, heavy=True)]),
          P([R("10 组指令回放；当前无实测", 8.5, GRAY)], space_before=3)])
    status_bar(s, ["doing"])


def p36(prs):
    _task_page(prs, 36, "搬运的夹爪和步数换算已经写好，缺的是一双眼睛",
               "抓取的前提是对齐，但当前还没有能提供对齐误差的检测器。", "2/6", "步已实现",
               ["视觉识别目标（未实现）", "计算相对偏航", "步态微调对齐", "夹爪闭合", "平移与释放"],
               ["夹爪开合、平移步数换算：steps = max(2, int(distance_cm / 2.0))",
                "调用序列 align → grasp → walk → release 已在闭环演示中跑通"],
               ["感知后端没有 detect_object，ctx.perceive(\"object\") 恒返回 {}，"
                "target / distance_cm 永远取任务卡默认值",
                "execute_motion(\"align\", obs) 落到默认分支，写死一个姿态且丢弃 obs",
                "全仓无任何检测器返回 target 字段"],
               "抓取成功率 ≥ 80%", "轻物 ≤100 g；当前无实测",
               "doing", "视觉：搬运技能真实调用序列代码", n_done=2, n_total=6)


def p37(prs):
    _task_page(prs, 37, "球在哪，机器人转过去——但目前只转一次",
               "闭环控制律已在设计数据包中跑通，尚未移植到技能层。", "|x| > 1.0", "cm",
               ["检测球位", "计算横向误差", "朝向伺服（单次）", "执行踢球"],
               ["误差判据：|x| > 1.0 cm 触发修正（阈值 0 会让机器人在噪声里抖）",
                "控制律：yaw = clamp(x / 2, −10°, +10°)，比例增益 1/2"],
               ["技能层没有二次检测，是一次开环修正（闭环已实现于 design/run_sim.py，见 P28）",
                "x(cm) → yaw(deg) 缺雅可比；设计相机模型（640×480 / HFOV 70°）下控制律偏小约 2.5 倍",
                "执行的是 hip_yaw，双脚着地时不改变机体朝向"],
               "踢球成功率 ≥ 70%", "球距 10–20 cm；当前无实测",
               "doing", "视觉：atri/skills/kick.py 真实控制律代码", n_done=2, n_total=5)


def p38(prs):
    _task_page(prs, 38, "关节轨迹已经能算，音乐还没有出声",
               "舞蹈不是播视频，是每个关节按时间轴算出来的轨迹。", "22", "关节 · 时间轴",
               ["麦克风拾音", "离线关键词识别", "音频播放（未实现）", "22 DOF 短舞", "语音应答"],
               ["关键词识别与 TTS 抽象接口：MockKeywordRecognizer / MockTTS / MacOSTTS",
                "舞蹈轨迹生成真实参数：head_yaw ±20°(2π)、head_pitch ±10°(4π)、trunk_roll ±4°、"
                "hip_pitch ∓8° 反相、shoulder_pitch ∓20° 反相、elbow_pitch −25°±15°"],
               ["全仓无音频播放代码，只有 TTS 文本；「音乐播放」是设计目标",
                "VoiceService 尚未接入 Brain"],
               "连续执行完成度 100%", "本地 TTS 响应延迟 ≤1 s",
               "doing", "视觉：cerebellum.dance() 真实帧生成代码", n_done=2, n_total=5)


def p39(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "04", "五项任务闭环", 39)
    page_title(s, "这四块空白是计划内的，产出一项补一项",
               lead="已跑通的部分全部可当场复现；没跑的写待测。")
    boxes = [("仿真截图位", "Webots 双足行走", "阶段二产出后补"),
             ("实机截图位", "三项视觉任务实测画面", "阶段三产出后补"),
             ("指标数据表", "单项成功率与测试日期", "每轮测试后更新，见 P47"),
             ("演示视频位", "3 分钟实物视频", "阶段三产出后补")]
    cw = (CONTENT_W - 0.60) / 2
    for i, (t, sub, when) in enumerate(boxes):
        x = CONTENT_X + (i % 2) * (cw + 0.30)
        y = Y_BODY + 0.20 + (i // 2) * 1.24
        rect(s, x, y, cw, 1.08, fill=PAPER, line=BLUE_300, line_w=1.0)
        text(s, x, y + 0.30, cw, 0.28,
             [P([R(t, 12, BLUE, heavy=True)], align=PP_ALIGN.CENTER)])
        text(s, x, y + 0.58, cw, 0.24,
             [P([R(sub, 10, GRAPHITE)], align=PP_ALIGN.CENTER)])
        text(s, x, y + 0.80, cw, 0.22,
             [P([R(when, 8.5, GRAY)], align=PP_ALIGN.CENTER)])
    yy = Y_BODY + 2.90
    rect(s, CONTENT_X, yy, CONTENT_W, 1.06, fill=MIST)
    text(s, CONTENT_X + 0.26, yy + 0.20, 3.10, 0.70,
         [P([R("现在就能拿出的证据", 11, GREEN, heavy=True)]),
          P([R("完整清单与命令见 P31", 8.5, GRAY)], space_before=5)])
    for i, (t, v) in enumerate([("视觉伺服鲁棒性边界", "12/12 · 9/12 · 4/12"),
                                ("设计包测试", "169 项 OK"),
                                ("五项任务闭环", "5/5")]):
        x = 4.35 + i * 2.68
        text(s, x, yy + 0.22, 2.55, 0.22, [P([R(t, 9, GRAPHITE)])])
        text(s, x, yy + 0.46, 2.55, 0.28,
             [P([R(v, 13, ORANGE, heavy=True)])])
    status_bar(s, ["done", "plan"])


# ═══════════════════════════════════════════════════════════════════
# 第五章 特色与创新
# ═══════════════════════════════════════════════════════════════════
def p40(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "05", "我们的创新不在重新发明双足机器人，在任务如何被描述与执行",
                 "特色与创新 · P40–P44")


def _innov(prs, page_no, title, lead, accent_num, accent_unit, chain, body_draw, foot):
    s = add_slide(prs, PAPER)
    page_frame(s, "05", "特色与创新", page_no)
    page_title(s, title, lead=lead)
    accent(s, CONTENT_X, Y_BODY - 0.06, 6.0, accent_num, accent_unit,
           size=22, unit_size=12)
    body_draw(s)
    if foot:
        rect(s, CONTENT_X, 5.90, CONTENT_W, 0.72, fill=MIST)
        text(s, CONTENT_X + 0.24, 5.90, CONTENT_W - 0.48, 0.72,
             [P([R(foot, 10, GRAPHITE)])], anchor=MSO_ANCHOR.MIDDLE)
    status_bar(s, ["done"])
    return s


def p41(prs):
    def body(s):
        pipeline_strip(s, CONTENT_X, Y_BODY + 0.52, CONTENT_W,
                       ["统一任务描述 JSON", "FSM 调度", "技能库执行",
                        "感知反馈", "回到 FSM"], h=0.54, size=10.5)
        text(s, CONTENT_X, Y_BODY + 1.14, CONTENT_W, 0.22,
             [P([R("task_cards/*.json　→　fsm.py　→　skills/*.py　→　perception/*.py",
                  9, GRAY)], align=PP_ALIGN.CENTER)])
        headers = ["", "常规做法", "本方案"]
        rows = [["任务是什么", "一段主程序", "一份 JSON 数据"],
                ["任务之间", "if 硬分叉", "FSM 状态流转"],
                ["新增能力", "改主程序", "加一个技能类 + 改一行白名单"]]
        table(s, CONTENT_X, Y_BODY + 1.56, CONTENT_W, headers, rows,
              col_w=[3.10, 4.20, 4.37], row_h=0.52, head_h=0.36, size=10.5)
    _innov(prs, 41, "五项任务不是五套程序，是五份 JSON",
           "把「任务」从代码里拿出来，变成可替换的数据。", "5", "张任务卡",
           None, body,
           "口径：本创新为系统架构层面，非算法原创。不宣称「完全不用改调度器」——白名单那一行目前仍需改（见 P23）。")


def p42(prs):
    def body(s):
        lx, lw = CONTENT_X, 5.60
        rect(s, lx, Y_BODY + 0.44, lw, 1.52, fill=WHITE, line=LINE, line_w=0.75)
        text(s, lx + 0.26, Y_BODY + 0.58, lw - 0.52, 1.24,
             [P([R("常规做法", 10.5, GRAY, heavy=True)]),
              P([R("二维码 = 位置标识，路径写死在代码里。换一条路线就要改程序、重新烧录。",
                   11, GRAPHITE)], space_before=8, line_spacing=1.42)])
        rect(s, lx, Y_BODY + 2.10, lw, 1.52, fill=MIST_2, line=BLUE, line_w=1.25)
        text(s, lx + 0.26, Y_BODY + 2.24, lw - 0.52, 1.24,
             [P([R("本方案", 10.5, BLUE, heavy=True)]),
              P([R("二维码 = 指令载体，内容就是 JSON。现场贴一张新码就是一条新路径。",
                   11, INK, heavy=True)], space_before=8, line_spacing=1.42)])
        rx, rw = 6.80, 5.70
        for i, (t, d) in enumerate([
            ("赛前改路线", "不用重编译、不用带电脑"),
            ("现场换任务", "同一台机器人切换成完全不同的任务序列"),
            ("教学场景", "学生改路径只需要改一张贴纸，理解成本几乎为零")]):
            y = Y_BODY + 0.44 + i * 1.06
            rect(s, rx, y, rw, 0.96, fill=WHITE, line=LINE, line_w=0.75)
            rect(s, rx, y, 0.045, 0.96, fill=ORANGE)
            text(s, rx + 0.26, y + 0.13, rw - 0.50, 0.26,
                 [P([R(t, 11.5, INK, heavy=True)])])
            text(s, rx + 0.26, y + 0.42, rw - 0.50, 0.42,
                 [P([R(d, 10, GRAPHITE)], line_spacing=1.35)])
    _innov(prs, 42, "把配置从电脑里搬到了地板上",
           "现场改任务的成本，从「重编译」降到「换一张贴纸」。", "换一张贴纸", "",
           None, body,
           "二维码承载的是结构化指令，不是可执行代码；不做任意代码执行。")


def p43(prs):
    def body(s):
        lx, lw = CONTENT_X, 5.60
        rect(s, lx, Y_BODY + 0.44, lw, 1.86, fill=WHITE, line=LINE, line_w=0.75)
        text(s, lx + 0.26, Y_BODY + 0.60, lw - 0.52, 1.56,
             [P([R("固定脚本", 10.5, GRAY, heavy=True)]),
              P([R("目标必须在 A 点 → 播放动作 → 结束。位置不对就失败，没有任何补救。",
                   11, GRAPHITE)], space_before=8, line_spacing=1.42),
              P([R("判据：无", 10, GRAY)], space_before=12)])
        rect(s, lx, Y_BODY + 2.44, lw, 1.86, fill=MIST_2, line=BLUE, line_w=1.25)
        text(s, lx + 0.26, Y_BODY + 2.60, lw - 0.52, 1.56,
             [P([R("本方案", 10.5, BLUE, heavy=True)]),
              P([R("检测 → 算误差 → 判定 → 调整。动作由误差决定，不是由固定坐标决定。",
                   11, INK, heavy=True)], space_before=8, line_spacing=1.42),
              P([R("判据：|x| > 1.0 cm 触发修正；yaw = clamp(x/2, ±10°)",
                   9.5, ORANGE, heavy=True)], space_before=12, line_spacing=1.40)])
        rx, rw = 6.80, 5.70
        rect(s, rx, Y_BODY + 0.44, rw, 1.86, fill=WHITE, line=ORANGE, line_w=1.0)
        text(s, rx + 0.26, Y_BODY + 0.60, rw - 0.52, 1.56,
             [P([R("边界（写清楚）", 10.5, ORANGE, heavy=True)]),
              P([R("· 技能层仍是一次开环修正；闭环形态已实现于设计数据包，待移植（见 P28）",
                   9.5, GRAPHITE)], space_before=8, line_spacing=1.40),
              P([R("· 是比例控制，不是学习型策略；增益与阈值是工程整定值",
                   9.5, GRAPHITE)], space_before=4, line_spacing=1.40),
              P([R("· 缺相机到关节角的雅可比：按设计相机模型估算，控制律偏小约 2.5 倍",
                   9.5, GRAPHITE)], space_before=4, line_spacing=1.40)])
        rect(s, rx, Y_BODY + 2.44, rw, 1.86, fill=MIST)
        text(s, rx + 0.26, Y_BODY + 2.60, rw - 0.52, 1.56,
             [P([R("这一条的现状", 10.5, BLUE, heavy=True)]),
              P([R("闭环控制律已在 design/run_sim.py 中实现并跑出收敛序列"
                   "（seed 20260910：5 cm → 4 轮 → 0.38；12 cm → 6 轮 → 0.48；20 cm → 7 轮 → 0.35），"
                   "带噪感知下 ideal 12/12、harsh 9/12、adversarial 4/12。",
                   10, GRAPHITE)], space_before=8, line_spacing=1.42),
              P([R("尚未接进技能层 kick.py——那是移植，不是从零写。",
                   10, ORANGE, heavy=True)], space_before=6, line_spacing=1.42)])
    _innov(prs, 43, "动作由误差决定，不是由固定坐标决定",
           "这一条的闭环已经跑出收敛数据，缺的是把它搬进技能层。", "±1.0", "cm",
           None, body, None)


def p44(prs):
    def body(s):
        rows = [["全离线", "赛场断网是常态；教学场景对数据外传有顾虑",
                 "人脸检测 / 二维码解码 / TTS 全部板载，主流程零网络出站"],
                ["两千八百元级", "万元级设备无法成班配置，「可复现」无从谈起",
                 "标准总线舵机 + 3D 打印结构 + 借用实验室已有计算板，新增 ¥2100–2800"],
                ["可复现", "别人照着做不出来，就不算平台",
                 "设计模型、代码、仿真、工程图、日志同一套 Git 仓库；核心零第三方依赖"]]
        table(s, CONTENT_X, Y_BODY + 0.44, CONTENT_W, ["条件", "为什么必须", "怎么做到"],
              rows, col_w=[1.80, 4.30, 5.57], row_h=0.88, head_h=0.34, size=10.5)
        rect(s, CONTENT_X, 5.82, CONTENT_W, 0.64, fill=MIST)
        text(s, CONTENT_X + 0.24, 5.82, CONTENT_W - 0.48, 0.64,
             [P([R("这三条互相约束——为了便宜要砍自由度，为了离线要压模型，为了可复现要限依赖。",
                   10.5, GRAPHITE)])], anchor=MSO_ANCHOR.MIDDLE)
    _innov(prs, 44, "三个条件必须同时成立，少一个都不叫能进课堂",
           "单看每一条都不稀奇，三条同时满足才是这个项目的位置。", "3", "个条件必须同时成立",
           None, body, None)


# ═══════════════════════════════════════════════════════════════════
# 第六章 验证与推进
# ═══════════════════════════════════════════════════════════════════
def p45(prs):
    s = add_slide(prs, INK)
    chapter_page(s, "06", "做到哪一步、谁在做、要多少钱、万一做不成怎么办",
                 "验证与推进 · P45–P51")


def p46(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "06", "验证与推进", 46)
    page_title(s, "四个我们预判会被问到的问题，先给出答案",
               lead="答法正在同步进 资料/调研/项目文档/答辩Q&A.md；本页以下的答案以本稿为准。")
    qa = [("为什么晋级后才做样机？",
           "报名阶段以「方案设计 + 设计模型 + 软件栈 + 仿真」为交付，避免在无明确晋级信号前投入整机成本。"
           "推进顺序是 0 预算 → 借用平台 → 自组样机。"),
          ("你们的创新到底是什么？",
           "不做「重新发明双足机器人」的包装。技术主线是在有限算力与断网条件下，"
           "用统一任务描述驱动一台小型双足机器人完成五项赛题任务。"
           "原创性主要在系统架构与工程实现，不在算法。"),
          ("现在到底完成了什么？",
           "22 关节设计模型与 4 张工程图、22 DOF Webots 世界与控制器、169 项测试、"
           "五项任务无硬件闭环 5/5、任务卡与动作库规范。没有实物样机，没有实机实测数据。"),
          ("断网后语音 / 人脸 / 二维码还能用吗？",
           "二维码解码与 TTS 是纯本地路径；人脸检测为本地 Haar，身份比对尚未实现。"
           "离线是设计目标且软件路径已具备，实机验证在样机阶段。")]
    cw = (CONTENT_W - 0.36) / 2
    for i, (q, a) in enumerate(qa[:2]):
        x = CONTENT_X + i * (cw + 0.36)
        y = Y_BODY + 0.16
        rect(s, x, y, cw, 2.62, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, x, y, cw, 0.045, fill=ORANGE)
        text(s, x + 0.28, y + 0.30, cw - 0.56, 0.60,
             [P([R(q, 14, INK, heavy=True)], line_spacing=1.25)])
        hline(s, x + 0.28, y + 1.04, cw - 0.56, color=BLUE_300, width=1.0)
        text(s, x + 0.28, y + 1.22, cw - 0.56, 1.24,
             [P([R(a, 11, GRAPHITE)], line_spacing=1.48)])
    for i, (q, a) in enumerate(qa[2:]):
        x = CONTENT_X + i * (cw + 0.36)
        y = Y_BODY + 2.96
        rect(s, x, y, cw, 1.36, fill=MIST)
        text(s, x + 0.28, y + 0.16, cw - 0.56, 0.28,
             [P([R(q, 11, INK, heavy=True)])])
        text(s, x + 0.28, y + 0.48, cw - 0.56, 0.78,
             [P([R(a, 9.5, GRAPHITE)], line_spacing=1.38)])
    status_bar(s, [])


def p47(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "06", "验证与推进", 47)
    page_title(s, "四项已经出了结果，其余写清怎么测",
               lead="每个指标都写清「怎么测」，不留模糊。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 4.0, "4 项", "已有结果", size=22, unit_size=13)
    rect(s, CONTENT_X, Y_BODY + 0.40, CONTENT_W, 1.28, fill=MIST_2)
    text(s, CONTENT_X + 0.26, Y_BODY + 0.52, 4.00, 0.22,
         [P([R("现在就有结果的四项", 10, GREEN, heavy=True)])])
    for i, (name, val, cmd) in enumerate([
            ("测试通过率", "169 / 169", "python3 -m unittest discover -s tests"),
            ("五项任务软件闭环", "5 / 5", "python3 run_demo.py --fast"),
            ("伺服闭环收敛（20cm）", "7 轮 / 0.85cm", "design/run_sim.py::servo_loop"),
            ("鲁棒性边界（harsh / 对抗）", "9/12 · 4/12",
             "run_sim.py --sweep perception --episodes 12")]):
        x = CONTENT_X + 0.26 + (i % 2) * 5.72
        y = Y_BODY + 0.80 + (i // 2) * 0.42
        text(s, x, y, 2.55, 0.20, [P([R(name, 8.5, GRAPHITE)])])
        text(s, x + 2.55, y - 0.03, 1.70, 0.22,
             [P([R(val, 11, GREEN, heavy=True)])])
        text(s, x, y + 0.19, 5.40, 0.18, [P([R(cmd, 7, GRAY)])])
    headers = ["指标", "目标值", "验证方式"]
    rows = [["双足连续行走距离", "≥1.0 m", "带重力与接触的动力学世界 → 借机实测（当前世界零重力，不承担此项）"],
            ["地面 QR 识别成功率 / 指令正确率", "≥90% / ≥95%", "固定光照、≤1 m；10 组指令回放"],
            ["人脸检测成功率（身份比对未实现）", "≥90%", "固定光照、≤1.5 m"],
            ["物品抓取成功率", "≥80%", "轻物 ≤100 g"],
            ["视觉定位踢球成功率", "≥70%", "球距 10–20 cm"],
            ["离线运行时间 / 本地 TTS 延迟", "≥30 min / ≤1 s", "样机满电实测；TTS 延迟现可在 macOS 实测"]]
    table(s, CONTENT_X, Y_BODY + 1.88, CONTENT_W, headers, rows,
          col_w=[4.20, 2.20, 5.27], row_h=0.34, head_h=0.28, size=8.5)
    text(s, CONTENT_X, Y_BODY + 1.64, CONTENT_W, 0.20,
         [P([R("口径：下表的「当前结果」列在样机测试前保持空白；目标值可在仿真/借机阶段按实际调参更新。",
               8.5, GRAY)])])
    status_bar(s, ["done", "plan"])


def p48(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "06", "验证与推进", 48)
    page_title(s, "四个阶段，每个阶段都有出口条件",
               lead="阶段二至四的时间点依赖官方赛程，不在此页承诺具体日期。")
    gantt(s, CONTENT_X, Y_BODY + 0.08, CONTENT_W - 1.60, 1.26, [
        ("一 · 方案设计与报名", 0, 1, INK, "done"),
        ("二 · 仿真与借机验证", 1, 1, BLUE, "doing"),
        ("三 · 硬件自组与离线实测", 2, 1, "5B8FB9", "plan"),
        ("四 · 全流程彩排与优化", 3, 1, "C9D6E2", "plan"),
    ])
    rect(s, CONTENT_X + CONTENT_W - 1.40, Y_BODY + 0.08, 1.40, 1.26, fill=MIST)
    text(s, CONTENT_X + CONTENT_W - 1.26, Y_BODY + 0.14, 1.14, 1.14,
         [P([R("出口条件", 9.5, BLUE, heavy=True)]),
          P([R("材料可复现", 8.5, GRAPHITE)], space_before=6, line_spacing=1.30),
          P([R("（行走 ≥1 m 在阶段三）", 8, ORANGE)], space_before=2, line_spacing=1.25),
          P([R("22/22 绑定 + 五任务连续两轮", 8.5, GRAPHITE)], space_before=5, line_spacing=1.30),
          P([R("五任务各跑通一次", 8.5, GRAPHITE)], space_before=5, line_spacing=1.30),
          P([R("连续两次成功", 8.5, GRAPHITE)], space_before=5, line_spacing=1.30)])
    ry = Y_BODY + 1.58
    text(s, CONTENT_X, ry, 5.0, 0.24, [P([R("风险与应对", 11, INK, heavy=True)])])
    risks = [("整机质量 3437 g（CAD 实装）；腿部力矩占连续额定 0.98 N·m 的 167%（峰值 1.47 的 111%），必须执行减重路径 A+B",
              "结构减重已在数学上堵死（需砍掉 54% 结构）；换 SM45BL 舵机可行但成本升至 ¥4856；"
              "降动态系数（2.0 → 1.4）零硬件成本、峰值口径回到 78%（连续额定口径仍 116%）——待核对评分细则是否限速", True),
             ("舵机装不进关节壳（0/8 通过）、电池放不下（105 > 94 mm）",
              "按真实元件尺寸重做关节壳与电池仓，或改用更小容量电池", True),
             ("上肢+躯干 = 10 压线，夹爪是否计入上肢关节口径未定",
              "报名前向组委会书面确认；若口径收紧，优先增加躯干自由度", True),
             ("技能层开环、缺雅可比；闭环待移植", "把 run_sim.py 的闭环搬进 kick.py，并标定像素—角度映射", False),
             ("Webots 世界为零重力运动学世界", "不承担「行走 ≥1 m」指标；需新建带重力与接触的动力学世界", False),
             ("人脸身份比对模块缺失", "阶段二第一优先项，先做 5 人以内的局部特征比对", False)]
    y = ry + 0.26
    for t, a, hot in risks:
        h = 0.50 if len(a) > 62 else 0.32
        rect(s, CONTENT_X, y, CONTENT_W, h, fill=WHITE if not hot else MIST,
             line=ORANGE if hot else LINE, line_w=1.0 if hot else 0.75)
        text(s, CONTENT_X + 0.22, y, 5.30, h,
             [P([R(t, 8, ORANGE if hot else GRAPHITE, heavy=hot)], line_spacing=1.20)],
             anchor=MSO_ANCHOR.MIDDLE)
        text(s, CONTENT_X + 5.65, y, CONTENT_W - 5.87, h,
             [P([R(a, 8, GRAPHITE)], line_spacing=1.20)], anchor=MSO_ANCHOR.MIDDLE)
        y += h + 0.04
    status_bar(s, ["done", "doing", "plan"])


def p49(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "06", "验证与推进", 49)
    page_title(s, "两千八百元级，附一条成本困局",
               lead="基于已确认元件参数；同时把「换更强舵机」这条出路的价格也写出来。")
    accent(s, CONTENT_X, Y_BODY - 0.06, 6.0, "¥2788–3456", "全口径 BOM（借用主控与已有电池后 ¥2100–2800）",
           size=20, unit_size=12)

    rows = [
        ["舵机", "飞特 STS3215 × 22 @ ¥85–95", "¥1870–2090"],
        ["电子件", "树莓派 4B / STM32F405 / URT-1 驱动板 / 相机 / 麦克风 / 功放喇叭 / IMU",
         "¥515–735"],
        ["电源", "3S 11.1V 2200–3000mAh + XL4015 降压 + XT60 接插件线材", "¥123–185"],
        ["标准件", "MF106ZZ 轴承 × 22 + 25T 金属舵盘 × 22（不可打印）+ 热熔铜螺母 + 螺钉 + 线束",
         "¥220–356"],
        ["打印耗材", "结构件净重 552 g × 损耗 1.35 = 745 g → 1 卷 PETG", "¥60–90"],
    ]
    table(s, CONTENT_X, Y_BODY + 0.44, 7.55,
          ["类别", "明细", "小计"], rows,
          col_w=[0.95, 5.10, 1.50], row_h=0.48, head_h=0.30, size=8.5)
    sy = Y_BODY + 0.44 + 0.30 + 5 * 0.48 + 0.06
    rect(s, CONTENT_X, sy, 7.55, 0.44, fill=MIST_2)
    text(s, CONTENT_X + 0.20, sy, 4.90, 0.44,
         [P([R("合计", 11, INK, heavy=True),
             R("　队员自备 FDM 打印机，只算耗材", 7.5, GRAY)])],
         anchor=MSO_ANCHOR.MIDDLE)
    text(s, 5.90, sy, 1.55, 0.44,
         [P([R("¥2788–3456", 12, ORANGE, heavy=True)], align=PP_ALIGN.RIGHT)],
         anchor=MSO_ANCHOR.MIDDLE)

    rx, rw = 8.60, 3.90
    for i, (t, v, d) in enumerate([
            ("全口径", "¥2788–3456", "含主控与电池；上限贴 3600 元申报预算的边"),
            ("可省后", "¥2100–2800", "借树莓派 −350~500 / 已有电池 −85~120 / 舵盘随舵机附赠 −88"),
            ("换 SM45BL 舵机", "¥4856", "升级 7 个关节，成本 +35%；力矩回到 89% 额定")]):
        y = Y_BODY + 0.44 + i * 1.06
        rect(s, rx, y, rw, 0.96, fill=MIST if i < 2 else WHITE,
             line=None if i < 2 else ORANGE, line_w=1.0)
        text(s, rx + 0.22, y + 0.12, rw - 0.44, 0.22,
             [P([R(t, 9.5, BLUE if i < 2 else ORANGE, heavy=True)])])
        text(s, rx + 0.22, y + 0.34, rw - 0.44, 0.26,
             [P([R(v, 13, ORANGE, heavy=True)])])
        text(s, rx + 0.22, y + 0.62, rw - 0.44, 0.30,
             [P([R(d, 7.5, GRAY)], line_spacing=1.22)])

    rect(s, CONTENT_X, 5.96, CONTENT_W, 0.56, fill=WHITE, line=ORANGE, line_w=1.0)
    text(s, CONTENT_X + 0.24, 5.96, CONTENT_W - 0.48, 0.56,
         [P([R("口径：", 9, ORANGE, heavy=True),
             R("设计目标清单，尚未采购；价格为量级估算，随行就市。若评分细则不限速，"
               "降动态系数（2.0 → 1.4）是零硬件成本的出路。", 9, GRAPHITE)])],
         anchor=MSO_ANCHOR.MIDDLE)
    status_bar(s, ["plan"])


def p50(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "06", "验证与推进", 50)
    page_title(s, "五个方向、五个接口：谁定义关节角度，谁保证关节真的转到了",
               lead="交付物按「已完成 / 进行中 / 规划中」分别标注。")
    members = [("何浩睿", "项目负责人 · 机械与步态", "done",
                "22 DOF 机构拓扑、3D 打印装配、舵机选型与扭矩校核、双足运动学",
                "机构三视图、装配件、步态参数表"),
               ("周柏宇", "项目统筹 · 系统集成", "doing",
                "大赛申报与材料统筹、答辩汇报、软硬件联调组织与验收",
                "申报材料、答辩稿、联调记录"),
               ("胡晟瑞", "算法研发 · 视觉感知", "doing",
                "人脸检测与特征匹配、二维码解码、目标检测、视觉伺服控制律",
                "感知模块、控制律参数、识别数据"),
               ("王旭琪", "系统架构 · 交互与仿真", "done",
                "大脑 FSM 与任务卡规范、技能库接口、离线语音、Webots 仿真",
                "编排层代码、任务卡规范、仿真工程"),
               ("张景昆", "小脑控制 · 嵌入式联调", "plan",
                "STM32 舵机总线驱动与 22 路标定、IMU 采集与姿态解算、串口协议、上电自检与失稳保护",
                "小脑固件、通信协议、标定记录、测试数据表")]
    y = Y_BODY + 0.14
    for name, role, kind, duty, deliv in members:
        rect(s, CONTENT_X, y, CONTENT_W, 0.66, fill=WHITE, line=LINE, line_w=0.75)
        rect(s, CONTENT_X, y, 0.045, 0.66,
             fill=GREEN if kind == "done" else (ORANGE if kind == "doing" else GRAY))
        text(s, CONTENT_X + 0.26, y, 1.45, 0.66,
             [P([R(name, 12.5, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, CONTENT_X + 1.80, y, 2.30, 0.66,
             [P([R(role, 9, BLUE)])], anchor=MSO_ANCHOR.MIDDLE)
        text(s, CONTENT_X + 4.20, y, 4.90, 0.66,
             [P([R(duty, 8.5, GRAPHITE)], line_spacing=1.25)], anchor=MSO_ANCHOR.MIDDLE)
        text(s, CONTENT_X + 9.20, y, CONTENT_W - 9.42, 0.66,
             [P([R(deliv, 8, GRAY)], line_spacing=1.25)], anchor=MSO_ANCHOR.MIDDLE)
        y += 0.72
    rect(s, CONTENT_X, 6.06, CONTENT_W, 0.52, fill=MIST)
    text(s, CONTENT_X + 0.24, 6.06, CONTENT_W - 0.48, 0.52,
         [P([R("接口边界：", 9.5, BLUE, heavy=True),
             R("何浩睿定义「关节应该转到什么角度」，张景昆保证「关节确实转到了、并且系统知道它转到了」——"
               "以「关节目标角序列 + IMU 姿态回传」为界，并行推进、互不阻塞。", 9.5, GRAPHITE)],
            line_spacing=1.30)], anchor=MSO_ANCHOR.MIDDLE)
    status_bar(s, ["done", "doing", "plan"])


def p51(prs):
    s = add_slide(prs, INK)
    vline(s, 0, 0, 0, color=INK, width=0.5)
    text(s, CONTENT_X, 1.10, 11.0, 0.30,
         [P([R("06  验证与推进", 10, BLUE_300)])])
    text(s, CONTENT_X, 1.62, 11.6, 0.80,
         [P([R("接下来 90 天，我们要把三件事做完", 34, WHITE, heavy=True)])])
    rect(s, CONTENT_X, 2.66, 0.80, 0.05, fill=ORANGE)
    items = [("借到同构双足平台，跑出一段真机视频",
              "把「软件能跑」变成「机器人在动」"),
             ("在 Webots 里标定出连续行走 ≥1 m 的步态",
              "把设计模型变成可复现的仿真结果"),
             ("移植一个已跑通的闭环，补齐两个缺失模块",
              "把 run_sim.py 的闭环搬进技能层；补人脸身份比对与目标检测器")]
    cw = (CONTENT_W - 0.60) / 3
    for i, (t, d) in enumerate(items):
        x = CONTENT_X + i * (cw + 0.30)
        rect(s, x, 3.06, cw, 1.86, fill="122F4E")
        text(s, x + 0.26, 3.28, cw - 0.52, 0.30,
             [P([R(f"0{i+1}", 15, ORANGE, heavy=True)])])
        text(s, x + 0.26, 3.66, cw - 0.52, 0.90,
             [P([R(t, 13.5, WHITE, heavy=True)], line_spacing=1.30)])
        text(s, x + 0.26, 4.56, cw - 0.52, 0.30,
             [P([R(d, 9.5, BLUE_300)], line_spacing=1.30)])
    hline(s, CONTENT_X, 5.42, CONTENT_W, color="1E4A73", width=1.0)
    text(s, CONTENT_X, 5.62, 11.6, 0.30,
         [P([R("A.T.R.I. 桌面自主人形智能", 12, WHITE, heavy=True),
             R("　｜　中国国际大学生创新大赛（2026）· 陕西赛区特色专项 · 小人形组",
               10, BLUE_300)])])
    text(s, CONTENT_X, 6.00, 11.6, 0.30,
         [P([R("西安交通大学　｜　项目团队：何浩睿 · 周柏宇 · 胡晟瑞 · 王旭琪 · 张景昆　｜　"
               "指导教师：陈妍 · 李璐", 10, BLUE_300)])])
    text(s, CONTENT_X, 6.62, 11.6, 0.40,
         [P([R("恳请各位专家评委批评指正", 16, WHITE, heavy=True)])])


PAGES = [p01, p02, p03, p04, p05, p06, p07, p08, p09, p10,
         p11, p12, p13, p14, p15, p16, p17, p18, p19, p20,
         p21, p22, p23, p24, p25, p26, p27, p28, p29, p30,
         p31, p32, p33, p34, p35, p36, p37, p38, p39, p40,
         p41, p42, p43, p44, p45, p46, p47, p48, p49, p50, p51]


def apply_motion(prs, chapter_slides):
    """给全片加转场。

    ⚠️ 只做转场，不做逐元素入场动画——这是踩过坑之后的决定：

    手写 DrawingML `<p:timing>` 实现入场动画，在页数少时 PowerPoint 能凑合打开，
    但 45 页 × 每页若干形状时（约 3200 个 cTn 节点）PowerPoint 会**直接拒绝打开
    文件**（表现为 AppleEvent 超时 / count of presentations = 0）。补上 bldLst
    后仍未解决。经二分定位确认：无动画的 51 页可正常打开，加动画即失败。

    交付物打不开是致命的，而入场动画只是锦上添花，所以这里只保留转场。
    若需要入场动画，请在 PowerPoint 里手动添加（一次操作可框选多页）。

    ppt/animate.py 里的 add_entrance 保留但不再调用，供后续排查。
    """
    for slide in prs.slides:
        add_transition(slide, "fade", 700)


def main():
    stem = sys.argv[1] if len(sys.argv) > 1 else "ATRI-答辩PPT-定稿"
    prs = new_deck()
    for fn in PAGES:
        fn(prs)
    apply_motion(prs, chapter_slides={4, 11, 16, 32, 40, 45})
    path = OUT / f"{stem}.pptx"
    prs.save(str(path))
    print(f"saved: {path}  ({len(PAGES)} pages)")


if __name__ == "__main__":
    main()
