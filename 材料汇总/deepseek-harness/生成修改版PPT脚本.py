# -*- coding: utf-8 -*-
"""
生成修改版 A.T.R.I. 宣传 PPT
深色赛博风，内容依据项目企划书(修改版)与修改意见。
输出到 /Users/hpi/Documents/deepseek harness/搞机器人/
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ---------- 画布 ----------
SLIDE_W = Emu(12192000)   # 13.333 in
SLIDE_H = Emu(6858000)    # 7.5 in
prs = Presentation()
prs.slide_width = SLIDE_W
prs.slide_height = SLIDE_H

# ---------- 主题色 ----------
BG      = RGBColor(0x0A, 0x0F, 0x1F)
CARD    = RGBColor(0x12, 0x1B, 0x35)
CARD2   = RGBColor(0x17, 0x22, 0x45)
LINE    = RGBColor(0x28, 0x3A, 0x5E)
CYAN    = RGBColor(0x00, 0xE5, 0xFF)
VIOLET  = RGBColor(0x8B, 0x5C, 0xF6)
GREEN   = RGBColor(0x34, 0xD3, 0x99)
AMBER   = RGBColor(0xFB, 0xBF, 0x24)
RED     = RGBColor(0xF8, 0x71, 0x71)
TEXT    = RGBColor(0xF5, 0xF7, 0xFF)
SUB     = RGBColor(0xA8, 0xB3, 0xD0)
DIM     = RGBColor(0x6C, 0x7A, 0x9E)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)

FONT = "微软雅黑"
FONT_EN = "Arial"


def set_run_font(run, name=FONT, size=12, bold=False, color=TEXT, italic=False):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn('a:ea'))
    if ea is None:
        ea = rPr.makeelement(qn('a:ea'), {})
        rPr.append(ea)
    ea.set('typeface', name)


def add_bg(slide, color=BG):
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = color


def add_text(slide, x, y, w, h, text, size=12, color=TEXT, bold=False,
             align=PP_ALIGN.LEFT, valign=None, font=FONT, line_spacing=None,
             anchor=None):
    tb = slide.shapes.add_textbox(Emu(int(x * 914400)), Emu(int(y * 914400)),
                                  Emu(int(w * 914400)), Emu(int(h * 914400)))
    tf = tb.text_frame
    tf.word_wrap = True
    if valign is not None:
        tf.vertical_anchor = valign
    lines = text.split('\n')
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if line_spacing is not None:
            p.line_spacing = Pt(line_spacing)
        run = p.add_run()
        run.text = line
        set_run_font(run, name=font, size=size, bold=bold, color=color)
    if anchor is not None:
        tb.text_frame.word_wrap = True
    return tb


def add_rect(slide, x, y, w, h, fill_color=CARD, line_color=None, line_width=0.75,
             shape=MSO_SHAPE.RECTANGLE, radius=None):
    sp = slide.shapes.add_shape(shape, Emu(int(x * 914400)), Emu(int(y * 914400)),
                                Emu(int(w * 914400)), Emu(int(h * 914400)))
    if fill_color is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill_color
    if line_color is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line_color
        sp.line.width = Pt(line_width)
    sp.shadow.inherit = False
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sp.adjustments[0] = radius
        except Exception:
            pass
    return sp


def add_ellipse(slide, x, y, w, h, fill_color):
    sp = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(x * 914400)), Emu(int(y * 914400)),
                                Emu(int(w * 914400)), Emu(int(h * 914400)))
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill_color
    sp.line.fill.background()
    sp.shadow.inherit = False
    return sp


def add_card(slide, x, y, w, h, title, body, accent=CYAN, title_size=15, body_size=11.5):
    add_rect(slide, x, y, w, h, fill_color=CARD, line_color=LINE, line_width=0.75,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    add_ellipse(slide, x + 0.18, y + 0.18, 0.16, 0.16, accent)
    add_text(slide, x + 0.22, y + 0.42, w - 0.44, 0.4, title, size=title_size,
             bold=True, color=TEXT)
    add_text(slide, x + 0.22, y + 0.88, w - 0.44, h - 1.05, body, size=body_size,
             color=SUB, line_spacing=12)


def add_kicker(slide, text, x=0.55, y=0.34, color=CYAN):
    add_text(slide, x, y, 11.0, 0.35, text, size=11, color=color, bold=True,
             font=FONT_EN)


def add_title(slide, text, x=0.55, y=0.66, color=TEXT, size=28):
    add_text(slide, x, y, 12.0, 0.8, text, size=size, color=color, bold=True)


def add_footer(slide, idx):
    add_text(slide, 0.55, 7.06, 6.0, 0.3, "A.T.R.I. · 人形机器人专项 · 小人形组",
             size=9, color=DIM, font=FONT_EN)
    add_text(slide, 12.35, 7.06, 0.45, 0.3, "%02d" % idx, size=10, color=DIM,
             bold=True, align=PP_ALIGN.RIGHT, font=FONT_EN)


def add_glow_deco(slide):
    # 不使用不透明光晕，避免遮挡内容；仅保留背景留白。
    return


# ======================= 页面构建 =======================

# S1 封面
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_glow_deco(s)
add_text(s, 0.7, 0.55, 12.0, 0.4,
         "中国国际大学生创新大赛（2026）· 陕西赛区特色专项 · 人形机器人专项 · 小人形组",
         size=12, color=SUB, align=PP_ALIGN.CENTER)
add_text(s, 0.6, 1.85, 12.13, 1.5, "A.T.R.I.", size=66, color=WHITE, bold=True,
         align=PP_ALIGN.CENTER, font=FONT_EN)
add_text(s, 0.6, 3.45, 12.13, 0.7, "桌面自主人形智能", size=28, color=CYAN,
         bold=True, align=PP_ALIGN.CENTER)
add_text(s, 0.6, 4.15, 12.13, 0.45,
         "Autonomous Tabletop Robotic Intelligence", size=13, color=SUB,
         align=PP_ALIGN.CENTER, font=FONT_EN)
add_text(s, 0.6, 4.85, 12.13, 0.6,
         "一台低成本桌面双足机器人，统一五项比赛任务的离线自主执行",
         size=17, color=TEXT, align=PP_ALIGN.CENTER)
add_text(s, 0.6, 6.35, 12.13, 0.4,
         "评审遴选汇报  |  项目简称：A.T.R.I.  |  西安交通大学",
         size=12, color=DIM, align=PP_ALIGN.CENTER)

# S2 项目速览
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "ONE-LINE INTRO")
add_title(s, "项目速览")
add_text(s, 0.55, 1.55, 12.2, 0.9,
         "一台低成本桌面双足机器人，把五项比赛任务统一到同一套软硬件框架中，默认全离线自主运行。",
         size=20, color=TEXT, bold=True, line_spacing=16)
cards = [
    ("22 DOF", "目标自由度",
     "目标采用 22 个主动自由度：双腿各 5、双臂各 4、躯干 2、头部 2。当前为方案设计值，待样机阶段验证。",
     CYAN),
    ("5 TASKS", "五项任务一体",
     "人脸识别、二维码循迹、物品搬运、体育运动、娱乐交互，用 JSON 任务卡和同一套状态机统一调度。",
     VIOLET),
    ("OFFLINE", "默认离线运行",
     "识别、解析、决策与动作执行全部在本地完成，现场断网后仍可继续自主工作。",
     GREEN),
]
cx = [0.55, 4.75, 8.95]
for i, (tag, title, body, accent) in enumerate(cards):
    x = cx[i]
    add_card(s, x, 2.75, 3.85, 2.9, title, body, accent=accent)
    add_text(s, x + 0.22, 5.78, 3.4, 0.4, tag, size=13, color=accent, bold=True,
             font=FONT_EN)
add_footer(s, 2)

# S3 问题与定位
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "WHY A.T.R.I.")
add_title(s, "为什么做")
pains = [
    ("教育门槛高", "全尺寸人形机器人价格高、体积大，本科教学难以大规模配置和复现。", CYAN),
    ("竞赛整合难", "人脸、循迹、搬运、体育、娱乐散落在不同平台，训练、演示与交接成本高。", AMBER),
    ("套件不开放", "成品竞赛套件上手快，但软件框架封闭，二次开发与任务扩展受限。", RED),
]
cx = [0.55, 4.75, 8.95]
for i, (title, body, accent) in enumerate(pains):
    add_card(s, cx[i], 1.65, 3.85, 3.2, title, body, accent=accent)
add_rect(s, 0.55, 5.3, 12.23, 1.15, fill_color=CARD2, line_color=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.12)
add_text(s, 0.85, 5.52, 11.7, 0.75,
         "我们的回答：A.T.R.I. = 低成本自组构型  +  五任务统一调度  +  全离线本地推理  +  可二次开发",
         size=15, color=TEXT, bold=True, align=PP_ALIGN.CENTER)
add_footer(s, 3)

# S4 赛道合规对照
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "RULE COMPLIANCE")
add_title(s, "赛道合规对照")
rows = [
    ("官方要求", "A.T.R.I. 设计", "状态"),
    ("身高 ≤ 60cm", "目标约 37.3cm", "达标（设计值）"),
    ("体宽 / 厚 ≤ 30cm", "约 18.7cm × 10.6cm", "达标（设计值）"),
    ("主动关节 ≥ 18", "22 自由度：腿5×2 / 臂4×2 / 躯干2 / 头2", "达标"),
    ("电源电压 ≥ 7.4V", "11.1V 3S 锂电池组", "达标"),
    ("IMU / 摄像头 / 麦克风 / 扬声器", "6轴IMU · 单目广角相机 · 环形麦克风 · 扬声器", "达标"),
    ("自主离线运行", "默认全离线，断网后继续自主工作", "达标"),
    ("场地 2400 × 2400mm", "面向五个任务区整体设计", "达标"),
]
tbl_shape = s.shapes.add_table(len(rows), 3, Emu(int(0.55*914400)), Emu(int(1.6*914400)),
                               Emu(int(12.23*914400)), Emu(int(4.4*914400)))
tbl = tbl_shape.table
tbl.columns[0].width = Emu(int(4.3*914400))
tbl.columns[1].width = Emu(int(5.6*914400))
tbl.columns[2].width = Emu(int(2.33*914400))
for _r in range(len(rows)):
    tbl.rows[_r].height = Emu(int(0.52 * 914400))

for r, row in enumerate(rows):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c)
        cell.text = val
        cell.margin_left = Emu(int(0.12*914400))
        cell.margin_right = Emu(int(0.12*914400))
        cell.margin_top = Emu(int(0.04*914400))
        cell.margin_bottom = Emu(int(0.04*914400))
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT if c < 2 else PP_ALIGN.CENTER
        run = p.runs[0] if p.runs else p.add_run()
        if p.runs:
            run = p.runs[0]
        else:
            run = p.add_run()
            run.text = val
        if r == 0:
            set_run_font(run, size=12, bold=True, color=WHITE)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0x1B, 0x27, 0x4A)
        else:
            set_run_font(run, size=11, bold=(c == 0), color=TEXT if c == 0 else SUB)
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD if r % 2 == 1 else CARD2
add_text(s, 0.55, 6.15, 12.2, 0.7,
         "说明：目标尺寸与构型为当前方案设计值，具体型号与 BOM 在样机阶段逐项确认；所有硬性指标均按官方口径预留余量。",
         size=10.5, color=DIM)
add_footer(s, 4)

# S5 硬件架构
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "HARDWARE")
add_title(s, "硬件架构")
# 左卡
add_rect(s, 0.55, 1.55, 6.1, 4.9, fill_color=CARD, line_color=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
add_text(s, 0.85, 1.75, 5.6, 0.45, "22 自由度目标构型", size=16, bold=True)
parts = [
    ("头部 2", "视觉巡视 · 人机示意"),
    ("躯干 2", "重心调整 · 上身姿态补偿"),
    ("双臂 8", "肩2·肘1·夹爪1 × 2（桌面轻物抓取）"),
    ("双腿 10", "髋3·膝1·踝1 × 2（行走/踢球）"),
]
py = 2.3
for title, body in parts:
    add_text(s, 0.9, py, 2.0, 0.4, title, size=13, bold=True, color=CYAN)
    add_text(s, 2.9, py, 3.6, 0.4, body, size=11.5, color=SUB)
    py += 0.72
add_text(s, 0.9, py + 0.1, 5.4, 0.5, "合计 22 DOF  ≥  官方要求 18 DOF",
         size=14, bold=True, color=GREEN)
# 右卡
add_rect(s, 7.0, 1.55, 5.78, 4.9, fill_color=CARD, line_color=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
add_text(s, 7.3, 1.75, 5.2, 0.45, "感知与供电", size=16, bold=True)
add_text(s, 7.3, 2.35, 5.2, 0.4, "传感器组", size=13, bold=True, color=CYAN)
add_text(s, 7.3, 2.8, 5.2, 0.8, "6 轴 IMU · 单目广角相机 · 环形麦克风 · 扬声器",
         size=11.5, color=SUB)
add_text(s, 7.3, 3.75, 5.2, 0.4, "电源", size=13, bold=True, color=CYAN)
add_text(s, 7.3, 4.2, 5.2, 0.8, "11.1V 3S 锂电池组，满足 ≥7.4V；大脑/小脑/舵机独立供电",
         size=11.5, color=SUB)
add_text(s, 7.3, 5.2, 5.2, 1.0,
         "当前为方案级选型：具体舵机、STM32 与边缘计算板型号，在样机阶段按扭矩、重量与供电需求确定。",
         size=10.5, color=DIM)
add_footer(s, 5)

# S6 软件架构
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "SOFTWARE")
add_title(s, "软件架构")
add_rect(s, 0.55, 1.55, 5.6, 4.4, fill_color=CARD, line_color=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
add_text(s, 0.85, 1.75, 5.0, 0.45, "大脑 · 边缘计算板（设计）", size=15, bold=True,
         color=CYAN)
add_text(s, 0.85, 2.3, 5.0, 3.4,
         "视觉感知：人脸 / 二维码 / 物体 / 球体\n任务状态机：JSON 任务卡解析与调度\n离线语音：本地 TTS 与关键词应答\n高层指令：前进 / 转向 / 抓取序列",
         size=11.5, color=SUB, line_spacing=14)
add_rect(s, 6.55, 1.55, 6.23, 4.4, fill_color=CARD, line_color=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
add_text(s, 6.85, 1.75, 5.7, 0.45, "小脑 · STM32 + IMU（设计）", size=15, bold=True,
         color=GREEN)
add_text(s, 6.85, 2.3, 5.7, 3.4,
         "逆运动学（IK）解算\nZMP 步态生成\n姿态闭环与跌倒保护\n22 路总线舵机控制",
         size=11.5, color=SUB, line_spacing=14)
add_rect(s, 0.55, 6.15, 12.23, 0.75, fill_color=CARD2, line_color=None)
add_text(s, 0.85, 6.3, 11.7, 0.5,
         "同一套任务卡与接口贯穿仿真、借机、样机三阶段；模块可独立替换、逐步接入真实硬件。",
         size=12, color=TEXT, bold=True)
add_footer(s, 6)

# S7 五项任务实现路线
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "FIVE MISSIONS")
add_title(s, "五项任务实现路线")
missions = [
    ("1", "人脸识别", "检测 → 特征 → 匹配 → TTS 播报", CYAN),
    ("2", "二维码循迹", "识别 → 透视矫正 → JSON → 状态机", VIOLET),
    ("3", "物品搬运", "检测 → 对齐 → 抓取 → 平移 → 释放", GREEN),
    ("4", "体育运动", "球体定位 → 调整朝向 → 踢球", AMBER),
    ("5", "娱乐交互", "关键词 → 动作 → 语音 → 音乐", RED),
]
cw = 2.32
for i, (num, title, body, accent) in enumerate(missions):
    x = 0.55 + i * (cw + 0.16)
    add_card(s, x, 1.6, cw, 3.0, title, body, accent=accent, title_size=14,
             body_size=10.5)
    add_ellipse(s, x + cw/2 - 0.3, 4.72, 0.6, 0.6, accent)
    add_text(s, x + cw/2 - 0.3, 4.72, 0.6, 0.6, num, size=14, bold=True,
             align=PP_ALIGN.CENTER, font=FONT_EN)
add_text(s, 0.55, 5.75, 12.2, 0.8,
         "五项任务共享同一套硬件与状态机，通过 JSON 任务卡切换；校赛阶段先完成各任务最小闭环，晋级后再按评分细则补强。",
         size=12.5, color=TEXT, bold=True)
add_footer(s, 7)

# S8 项目特点
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "PROJECT FEATURES")
add_title(s, "项目特点")
features = [
    ("01", "一台机器人完成五项任务",
     "五项任务共用同一套技能库和状态机，不为每项任务单独编写程序。", CYAN),
    ("02", "二维码既识别，也下发任务",
     "任务信息写入二维码，识别后解析为 JSON 直接执行；换任务只需改二维码内容，不用改主程序。", VIOLET),
    ("03", "主流程不依赖网络",
     "人脸识别、二维码解析、语音播报和任务切换全部本地完成，现场可断网运行。", GREEN),
]
cy = [1.65, 3.15, 4.65]
for i, (num, title, body, accent) in enumerate(features):
    y = cy[i]
    add_rect(s, 0.55, y, 12.23, 1.25, fill_color=CARD, line_color=LINE,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    add_ellipse(s, 0.85, y + 0.42, 0.42, 0.42, accent)
    add_text(s, 0.85, y + 0.42, 0.42, 0.42, num, size=12, bold=True,
             align=PP_ALIGN.CENTER, font=FONT_EN)
    add_text(s, 1.5, y + 0.18, 4.4, 0.9, title, size=15, bold=True, color=TEXT)
    add_text(s, 6.0, y + 0.18, 6.6, 0.9, body, size=11.5, color=SUB,
             line_spacing=12)
add_text(s, 0.55, 6.1, 12.2, 0.6,
         "说明：当前项目处于报名与方案设计阶段，以上为实现路径，尚未形成实物测试数据。",
         size=11, color=DIM)
add_footer(s, 8)

# S9 优势一
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "ADVANTAGE 01")
add_title(s, "全离线本地推理")
add_text(s, 0.55, 1.55, 12.2, 0.7,
         "演示时关闭网络，识别、决策、控制与交互继续执行。", size=18, bold=True,
         color=TEXT)
adv1 = [
    ("全部本地处理", "人脸识别、二维码解析、语音播报与任务状态机均在板载计算单元运行。"),
    ("不怕现场断网", "关闭网络后，识别、决策、控制与交互仍按原流程运行。"),
    ("数据不出设备", "任务数据不依赖云端 API，适合课堂、竞赛与实验室场景。"),
]
cx = [0.55, 4.75, 8.95]
for i, (title, body) in enumerate(adv1):
    add_card(s, cx[i], 2.5, 3.85, 2.9, title, body, accent=GREEN)
add_footer(s, 9)

# S10 优势二
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "ADVANTAGE 02")
add_title(s, "低成本一体化")
comps = [
    ("全尺寸人形", "体积大、价格高", "不适合本科教学大规模配置"),
    ("教育双足", "功能偏向单一场景", "多任务统一编排不足"),
    ("成品竞赛套件", "上手快、硬件完整", "软件封闭、扩展需自改"),
]
cx = [0.55, 3.9, 7.25]
for i, (title, body, sub) in enumerate(comps):
    add_card(s, cx[i], 1.6, 3.1, 2.7, title, body + "\n" + sub, accent=DIM,
             title_size=13, body_size=10.5)
# A.T.R.I. 卡片
add_rect(s, 10.6, 1.6, 2.18, 2.7, fill_color=CARD2, line_color=CYAN, line_width=1.5,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
add_text(s, 10.75, 1.85, 1.9, 0.5, "A.T.R.I.", size=16, bold=True, color=CYAN,
         font=FONT_EN)
add_text(s, 10.75, 2.5, 1.9, 1.6,
         "低成本自组\n五任务统一\n全离线", size=11.5, color=TEXT, line_spacing=12)
add_rect(s, 0.55, 4.75, 12.23, 1.4, fill_color=CARD2, line_color=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
add_text(s, 0.85, 4.95, 11.7, 1.0,
         "样机预算约 ¥3600；边缘计算板与 STM32 开发板由实验室现有设备提供，不计入本次新增预算，进一步降低进入门槛。",
         size=13, color=TEXT, bold=True, line_spacing=14)
add_footer(s, 10)

# S11 阶段规划与预算
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "ROADMAP")
add_title(s, "项目规划与阶梯预算")
stages = [
    ("阶段 0", "报名与方案设计", "完成合规构型与五项任务路线；提交企划书与 PPT 材料", "0–100 元"),
    ("阶段 1", "仿真 + 借机验证", "Webots/PyBullet 仿真，借用平台跑通五项任务最小闭环", "0–500 元"),
    ("阶段 2", "自组样机", "晋级后按 BOM 组装 22 自由度样机，逐项联调与留痕", "1500–3500 元"),
    ("阶段 3", "省赛冲刺", "按评分细则补强演示，完善训练数据、视频与研发日志", "按经费/赞助"),
]
cy = 1.6
for tag, title, body, budget in stages:
    add_rect(s, 0.55, cy, 12.23, 1.2, fill_color=CARD, line_color=LINE,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    add_text(s, 0.85, cy + 0.2, 2.4, 0.4, tag, size=12, bold=True, color=CYAN,
             font=FONT_EN)
    add_text(s, 0.85, cy + 0.6, 2.4, 0.4, title, size=11, color=SUB)
    add_text(s, 3.4, cy + 0.25, 7.4, 0.75, body, size=11.5, color=TEXT,
             line_spacing=12)
    add_text(s, 10.9, cy + 0.35, 1.7, 0.5, budget, size=12, bold=True, color=AMBER,
             align=PP_ALIGN.RIGHT)
    cy += 1.35
add_footer(s, 11)

# S12 当前进展
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "CURRENT STATUS")
add_title(s, "当前进展")
status_rows = [
    ("模块", "当前状态", "说明"),
    ("方案设计", "已完成", "确定 22 自由度构型、软硬件分工、五项任务实现路径"),
    ("报名填报", "进行中", "完成系统报名与校内备案"),
    ("仿真环境", "未开始", "报名后搭建 Webots / PyBullet 模型与任务环境"),
    ("硬件样机", "未开始", "晋级后启动自组或借用"),
    ("五项任务实现", "未开始", "校赛阶段完成最小闭环"),
]
tbl_shape = s.shapes.add_table(len(status_rows), 3, Emu(int(0.55*914400)), Emu(int(1.6*914400)),
                               Emu(int(12.23*914400)), Emu(int(4.0*914400)))
tbl = tbl_shape.table
tbl.columns[0].width = Emu(int(2.6*914400))
tbl.columns[1].width = Emu(int(2.2*914400))
tbl.columns[2].width = Emu(int(7.43*914400))
for _r in range(len(status_rows)):
    tbl.rows[_r].height = Emu(int(0.62 * 914400))
for r, row in enumerate(status_rows):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c)
        cell.text = val
        cell.margin_left = Emu(int(0.12*914400))
        cell.margin_right = Emu(int(0.12*914400))
        cell.margin_top = Emu(int(0.04*914400))
        cell.margin_bottom = Emu(int(0.04*914400))
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT if c == 2 else PP_ALIGN.CENTER
        run = p.runs[0] if p.runs else p.add_run()
        if p.runs:
            run = p.runs[0]
        else:
            run = p.add_run()
            run.text = val
        if r == 0:
            set_run_font(run, size=12, bold=True, color=WHITE)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0x1B, 0x27, 0x4A)
        else:
            set_run_font(run, size=11, bold=(c == 0),
                         color=GREEN if val == "已完成" else (AMBER if val == "进行中" else SUB))
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD if r % 2 == 1 else CARD2
add_text(s, 0.55, 5.85, 12.2, 0.7,
         "项目处于报名与方案设计阶段，尚未有实物样机和测试数据；后续按阶段推进并如实补充。",
         size=11.5, color=DIM)
add_footer(s, 12)

# S13 阶段性技术指标
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "TECH TARGETS")
add_title(s, "阶段性技术指标")
ind_rows = [
    ("指标", "当前目标", "当前结果"),
    ("双足连续行走", "≥ 1 m", "未测试"),
    ("二维码识别成功率", "≥ 90%", "未测试"),
    ("人脸识别成功率", "≥ 90%", "未测试"),
    ("抓取成功率", "≥ 80%", "未测试"),
    ("踢球成功率", "≥ 80%", "未测试"),
    ("单机离线运行时间", "≥ 30 min", "未测试"),
]
tbl_shape = s.shapes.add_table(len(ind_rows), 3, Emu(int(0.55*914400)), Emu(int(1.6*914400)),
                               Emu(int(12.23*914400)), Emu(int(4.2*914400)))
tbl = tbl_shape.table
tbl.columns[0].width = Emu(int(4.5*914400))
tbl.columns[1].width = Emu(int(3.4*914400))
tbl.columns[2].width = Emu(int(4.33*914400))
for _r in range(len(ind_rows)):
    tbl.rows[_r].height = Emu(int(0.58 * 914400))
for r, row in enumerate(ind_rows):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c)
        cell.text = val
        cell.margin_left = Emu(int(0.12*914400))
        cell.margin_right = Emu(int(0.12*914400))
        cell.margin_top = Emu(int(0.04*914400))
        cell.margin_bottom = Emu(int(0.04*914400))
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT if c < 2 else PP_ALIGN.CENTER
        run = p.runs[0] if p.runs else p.add_run()
        if p.runs:
            run = p.runs[0]
        else:
            run = p.add_run()
            run.text = val
        if r == 0:
            set_run_font(run, size=12, bold=True, color=WHITE)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0x1B, 0x27, 0x4A)
        else:
            set_run_font(run, size=11, bold=(c == 0), color=TEXT if c == 0 else SUB)
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD if r % 2 == 1 else CARD2
add_text(s, 0.55, 6.0, 12.2, 0.7,
         "说明：目标值随官方评分细则与样机测试结果滚动更新；当前无实测数据，不编造结果。",
         size=10.5, color=DIM)
add_footer(s, 13)

# S14 风险与应对
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "RISK")
add_title(s, "风险与应对")
risks = [
    ("样机尚未到位", "仿真先行 + 借用平台联调，不阻塞算法验证与任务闭环。", CYAN),
    ("双足步态稳定性", "ZMP 步态 + 姿态闭环 + 躯干 2 自由度余量；分模块逐步调参。", AMBER),
    ("经费与周期有限", "阶梯解锁预算：0–100 → 0–500 → 1500–3500 元档；复用实验室设备降本。", RED),
]
cx = [0.55, 4.75, 8.95]
for i, (title, body, accent) in enumerate(risks):
    add_card(s, cx[i], 1.7, 3.85, 3.0, title, body, accent=accent)
add_rect(s, 0.55, 5.15, 12.23, 1.3, fill_color=CARD2, line_color=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
add_text(s, 0.85, 5.35, 11.7, 0.9,
         "原则：不把“规划”说成“已完成”；仿真、借机与样机使用同一套任务卡和接口，某平台出问题时先在其他平台继续测试。",
         size=12.5, color=TEXT, bold=True, line_spacing=14)
add_footer(s, 14)

# S15 团队与技术储备
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "TEAM")
add_title(s, "团队与技术储备")
add_text(s, 0.55, 1.5, 12.2, 0.5,
         "学科交叉：计算机 / 电子 / 自动化 —— 覆盖感知、控制、硬件与系统集成",
         size=13, color=SUB)
members = [
    ("何浩睿", "项目负责人", "机械结构 · 双足步态 · 舵机配置", CYAN),
    ("周柏宇", "项目统筹", "系统集成 · 报名答辩", VIOLET),
    ("胡晟瑞", "视觉感知", "人脸识别 · 二维码 · 物体检测", GREEN),
    ("王旭琪", "交互与仿真", "状态机 · 离线语音 · 仿真环境", AMBER),
    ("张景昆", "自动化专业", "运动控制 · 硬件支持", RED),
]
cx = [0.55, 3.05, 5.55, 8.05, 10.55]
for i, (name, role, desc, accent) in enumerate(members):
    x = cx[i]
    add_card(s, x, 2.2, 2.3, 2.9, name, role + "\n" + desc, accent=accent,
             title_size=13, body_size=10)
add_text(s, 0.55, 5.5, 12.2, 0.5,
         "指导老师：陈妍 · 李璐（技术方向把关 / 设备协调）", size=13, color=SUB,
         bold=True)
add_footer(s, 15)

# S16 项目愿景
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_kicker(s, "VISION")
add_title(s, "项目愿景")
add_text(s, 0.55, 1.7, 12.2, 1.2,
         "让低成本桌面双足机器人，成为具身智能教育的公共基础设施。",
         size=26, bold=True, color=TEXT, align=PP_ALIGN.CENTER, line_spacing=18)
visions = [
    ("可复现", "同一套任务卡/接口，课程与竞赛可复用"),
    ("可扩展", "新增任务只需增加任务卡与技能模块，不重写整机"),
    ("可负担", "低成本自组 + 实验室设备复用"),
]
cx = [0.55, 4.75, 8.95]
for i, (title, body) in enumerate(visions):
    add_card(s, cx[i], 3.3, 3.85, 2.0, title, body, accent=CYAN if i == 0 else (VIOLET if i == 1 else GREEN))
add_text(s, 0.55, 5.8, 12.2, 0.6,
         "研发链路：仿真 → 借用平台 → 自组样机 → 课程/竞赛落地",
         size=13, color=SUB, align=PP_ALIGN.CENTER)
add_footer(s, 16)

# S17 结束页
s = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(s)
add_glow_deco(s)
add_text(s, 0.6, 1.8, 12.13, 1.3, "A.T.R.I.", size=60, color=WHITE, bold=True,
         align=PP_ALIGN.CENTER, font=FONT_EN)
add_text(s, 0.6, 3.3, 12.13, 0.7,
         "一台机器人，一个统一任务链，让具身智能实验走进课堂与赛场。",
         size=20, color=TEXT, align=PP_ALIGN.CENTER)
add_text(s, 0.6, 4.4, 12.13, 0.5, "恳请各位专家给予支持与指导", size=16,
         color=SUB, align=PP_ALIGN.CENTER)
add_text(s, 0.6, 6.3, 12.13, 0.4,
         "A.T.R.I. 项目组 · 西安交通大学\n项目负责人：何浩睿  |  指导老师：陈妍 · 李璐",
         size=12, color=DIM, align=PP_ALIGN.CENTER)

# ---------- 保存 ----------
out = "/Users/hpi/Documents/deepseek harness/搞机器人/A.T.R.I.-宣传PPT-交差版-修改版.pptx"
prs.save(out)
print("saved:", out)
print("slides:", len(prs.slides.__iter__.__self__._sldIdLst))
print("size:", os.path.getsize(out))
