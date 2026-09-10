"""生成 3 页视觉样张：封面 / 一页摘要 / 总体技术架构图。

用法： ./.venv-ppt/bin/python ppt/build_sample.py
输出： ppt/out/ATRI_样张.pptx
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.dml import MSO_LINE_DASH_STYLE as DASH
from pptx.util import Inches

from design import *  # noqa: F401,F403
from diagrams import joint_topology, joint_topology_legend

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


# ══════════════════════════ P01 · 封面 ══════════════════════════
def slide_cover(prs):
    s = add_slide(prs, PAPER)

    # ── 右侧配图位（cover-hero.png 落位后替换此面板）
    # ── 右侧：自绘的 22 关节结构运动学图（图纸，不是产品渲染图）
    vline(s, 7.42, 0.72, SLIDE_H - 1.44, color=LINE, width=0.75)
    joint_topology(s, cx=10.45, top=1.22, h=5.22, labels=True)
    text(s, 7.72, 6.60, 5.2, 0.24,
         [P([R("22 关节结构运动学图", 9.5, BLUE, heavy=True),
             R("　结构已定义 · 样机未制造", 9, GRAY)])])

    # ── 左侧文字
    X = CONTENT_X

    text(s, X, 0.82, 6.2, 0.26,
         [P([R("中国国际大学生创新大赛（2026）", 10.5, BLUE, heavy=True),
             R("　陕西赛区特色专项 · 人形机器人专项 · 小人形组", 10.5, GRAY)])])

    text(s, X, 1.92, 6.4, 1.00,
         [P([R("A.T.R.I.", 56, INK, heavy=True, spc=1.5)])])

    text(s, X, 2.92, 6.4, 0.58,
         [P([R("桌面自主人形智能", 32, INK, heavy=True, spc=1.5)])])

    text(s, X, 3.56, 6.4, 0.26,
         [P([R("AUTONOMOUS TABLETOP ROBOTIC INTELLIGENCE", 9.5, GRAY, spc=2.4)])])

    rect(s, X, 4.12, 0.72, 0.05, fill=ORANGE)

    text(s, X, 4.38, 6.3, 0.36,
         [P([R("一台能自己看、自己想、自己走的桌面双足机器人", 17, GRAPHITE)])])

    # ── 关节节点母题（22 个点 = 22 个主动自由度）
    joint_chain_h(s, X, 5.06, 5.87, n=22, first_color=ORANGE)
    text(s, X, 5.24, 6.3, 0.24,
         [P([R("22 个主动自由度", 9.5, BLUE, heavy=True),
             R("　双腿 10 · 双臂 8 · 躯干 2 · 头部 2", 9.5, GRAY)])])

    # ── 团队信息
    text(s, X, 5.78, 6.4, 0.24,
         [P([R("项目团队", 9, GRAY)])])
    text(s, X, 5.99, 6.4, 0.28,
         [P([R("何浩睿 · 周柏宇 · 胡晟瑞 · 王旭琪 · 张景昆", 13, GRAPHITE)])])
    text(s, X, 6.34, 6.4, 0.24,
         [P([R("指导教师", 9, GRAY)])])
    text(s, X, 6.55, 6.4, 0.28,
         [P([R("陈妍 · 李璐", 13, GRAPHITE)])])

    # ── 状态口径声明
    hline(s, X, 6.86, 7.42 - X - 0.36, color=LINE, width=0.75)
    text(s, X, 6.96, 6.6, 0.26,
         [P([R("本材料所有技术声明均按 ", 8.5, GRAY),
             R("● 已完成", 8.5, GREEN), R(" / ", 8.5, GRAY),
             R("◐ 进行中", 8.5, ORANGE), R(" / ", 8.5, GRAY),
             R("○ 规划中", 8.5, GRAY),
             R(" 三种状态如实标注", 8.5, GRAY)])])
    return s


# ══════════════════════════ P02 · 一页摘要 ══════════════════════════
def slide_summary(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "00", "项目概要", 2, right_label="项目概要")
    page_title(
        s,
        "一台千元级桌面双足机器人，把五项赛题装进同一套任务系统",
        lead="左边是我们要解决的问题，中间是已经做出来的东西，右边是当前推进到什么位置。",
    )

    # ── 三栏栅格
    A_X, A_W = CONTENT_X, 3.30
    B_X, B_W = 4.493, 4.55
    C_X, C_W = 9.403, 3.097

    # ── 栏 A：要解决的问题
    text(s, A_X, Y_BODY, A_W, 0.26,
         [P([R("要解决的问题", 11, BLUE, heavy=True)])])
    hline(s, A_X, Y_BODY + 0.30, A_W, color=BLUE_300, width=1.0)

    pains = [
        ("01", "设备贵", "教育型小型双足套件多在万元级，一个班 20 台就是二十万，无法成班配置。"),
        ("02", "算法散", "人脸、循迹、抓取、步态散在四五套互不相通的工程里，实验之间无法对照。"),
        ("03", "断网瘫", "依赖云端推理的方案，赛场一断网就失效；教学场景也不愿数据外传。"),
    ]
    y = Y_BODY + 0.46
    for no, title, desc in pains:
        text(s, A_X, y, 0.42, 0.26, [P([R(no, 12, ORANGE, heavy=True)])])
        text(s, A_X + 0.44, y, A_W - 0.44, 0.26,
             [P([R(title, 13, INK, heavy=True)])])
        text(s, A_X + 0.44, y + 0.28, A_W - 0.44, 0.80,
             [P([R(desc, 10, GRAY)], line_spacing=1.35)])
        y += 1.22

    # ── 栏 B：已经做出来的
    text(s, B_X, Y_BODY, B_W, 0.26,
         [P([R("已经做出来的", 11, BLUE, heavy=True)])])
    hline(s, B_X, Y_BODY + 0.30, B_W, color=BLUE_300, width=1.0)

    cw = (B_W - 0.30) / 2
    ch = 1.72
    y1, y2 = Y_BODY + 0.46, Y_BODY + 0.46 + ch + 0.18
    num_card(s, B_X, y1, cw, ch, "22", "DOF", "主动自由度：双腿 10 + 双臂 8 + 躯干 2 + 头部 2")
    num_card(s, B_X + cw + 0.30, y1, cw, ch, "5", "项",
             "赛题共用同一套 JSON 任务卡、状态机与技能库")
    num_card(s, B_X, y2, cw, ch, "51", "项",
             "单元测试全部通过，CI 覆盖 3 个 Python 版本")
    num_card(s, B_X + cw + 0.30, y2, cw, ch, "¥1500", "–2800",
             "新增采购；不含实验室已有的计算板与控制板",
             num_size=26, unit_size=13)

    # ── 栏 C：推进到哪一步
    text(s, C_X, Y_BODY, C_W, 0.26,
         [P([R("推进到哪一步", 11, BLUE, heavy=True)])])
    hline(s, C_X, Y_BODY + 0.30, C_W, color=BLUE_300, width=1.0)

    prog = [
        ("done", "软件栈", "五张任务卡的无硬件闭环演示 5/5 通过，可当场复现"),
        ("doing", "仿真联调", "Webots 控制器已提交，待 Windows 侧跑出仿真图"),
        ("plan", "实物样机", "晋级后启动采购、3D 打印与装配"),
    ]
    y = Y_BODY + 0.46
    for kind, title, desc in prog:
        bh = 1.15
        rect(s, C_X, y, C_W, bh, fill=MIST)
        status_chip(s, C_X + 0.16, y + 0.14, kind, size=10)
        text(s, C_X + 0.16, y + 0.48, C_W - 0.32, 0.26,
             [P([R(title, 12.5, INK, heavy=True)])])
        text(s, C_X + 0.16, y + 0.74, C_W - 0.32, 0.34,
             [P([R(desc, 9.5, GRAY)], line_spacing=1.28)])
        y += bh + 0.08

    status_bar(s, ["done", "doing", "plan"])
    return s


# ══════════════════════════ P17 · 总体技术架构图 ══════════════════════════
def slide_architecture(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "03", "技术架构与实现", 17)
    page_title(
        s,
        "五层架构，两条边界——一条是算力边界，一条是硬件边界",
        lead="上层不关心关节怎么转，下层不关心任务是什么，两层之间只传一份 JSON 协议。",
    )

    # ── 栅格
    TX, TW = CONTENT_X, 1.25                 # 层名 tab
    PX = 2.183
    PW = 8.35                                # 面板
    BX, BW = 10.653, 1.847                   # 右侧括号列

    LH, LG = 0.66, 0.11                      # 层高 / 层间距
    ys = [2.20 + i * (LH + LG) for i in range(5)]

    INNER = 0.10
    ix = PX + INNER
    iw = PW - 2 * INNER
    by = 0.09                                # 盒在层内的上边距
    bh = LH - 2 * by

    def tab(y, name, en, color):
        rect(s, TX, y, TW, LH, fill=color)
        text(s, TX, y + 0.11, TW, LH - 0.22,
             [P([R(name, 12, WHITE, heavy=True)], align=PP_ALIGN.CENTER),
              P([R(en, 6.5, "C9DCEC", spc=0.8)], align=PP_ALIGN.CENTER,
                space_before=2)],
             anchor=MSO_ANCHOR.MIDDLE)

    def box(x, y, w, label, size=11, fill=WHITE, line=BLUE_300,
            color=INK, heavy=False):
        rect(s, x, y, w, bh, fill=fill, line=line, line_w=0.75)
        text(s, x + 0.06, y, w - 0.12, bh,
             [P([R(label, size, color, heavy=heavy)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)

    def bracket(y, h, name, sub, status):
        arm = 0.15
        vline(s, BX, y, h, color=BLUE, width=1.5)
        hline(s, BX, y, arm, color=BLUE, width=1.5)
        hline(s, BX, y + h, arm, color=BLUE, width=1.5)
        sym, label, color = STATUS[status]
        text(s, BX + arm + 0.14, y, BW - arm - 0.14, h,
             [P([R(name, 12.5, INK, heavy=True)]),
              P([R(sub, 8.5, GRAY)], space_before=3, line_spacing=1.2),
              P([R(sym + " " + label, 8.5, color, heavy=True)], space_before=4)],
             anchor=MSO_ANCHOR.MIDDLE)

    # ── L1 任务层
    y = ys[0]
    tab(y, "任务层", "TASK", "5B8FB9")
    rect(s, PX, y, PW, LH, fill=WHITE, line=LINE, line_w=0.75)
    tasks = ["人脸识别", "二维码循迹", "物品搬运", "体育运动", "娱乐交互"]
    cw = (iw - 4 * 0.09) / 5
    for i, t in enumerate(tasks):
        box(ix + i * (cw + 0.09), y + by, cw, t, size=11, line=LINE)
    bracket(y, LH, "赛题", "五项任务清单", "done")

    # ── L2 编排层
    y = ys[1]
    tab(y, "编排层", "ORCHESTRATION", INK)
    rect(s, PX, y, PW, LH, fill=MIST)
    items = ["JSON 任务卡", "任务调度器", "有限状态机 FSM", "技能库"]
    aw = 0.30
    bw = (iw - 3 * aw) / 4
    for i, t in enumerate(items):
        x = ix + i * (bw + aw)
        box(x, y + by, bw, t, size=11, heavy=True)
        if i < 3:
            arrow(s, x + bw + 0.04, y + LH / 2, aw - 0.08)

    # ── L3 感知·交互层
    y = ys[2]
    tab(y, "感知交互", "PERCEPTION", INK)
    rect(s, PX, y, PW, LH, fill=MIST)
    gbw, gaw, ggap = 1.75, 0.28, 0.59
    xs = [ix, ix + gbw + gaw, ix + 2 * (gbw + gaw) + ggap,
          ix + 2 * (gbw + gaw) + ggap + gbw + gaw]
    for i, (x, t) in enumerate(zip(xs, ["单目相机", "视觉检测", "麦克风", "离线语音"])):
        box(x, y + by, gbw, t, size=11)
        if i in (0, 2):
            arrow(s, x + gbw + 0.04, y + LH / 2, gaw - 0.08)

    # ── L4 控制层
    y = ys[3]
    tab(y, "控制层", "CONTROL", BLUE)
    rect(s, PX, y, PW, LH, fill=MIST_2)
    ctrls = ["步态生成", "动作库回放", "视觉伺服", "姿态闭环 · 失稳保护"]
    cw4 = (iw - 3 * 0.12) / 4
    for i, t in enumerate(ctrls):
        box(ix + i * (cw4 + 0.12), y + by, cw4, t, size=11, heavy=True)

    bracket(ys[1], 2 * LH + LG, "大脑", "边缘计算板 · Linux\n任务编排与离线感知", "done")
    bracket(ys[3], LH, "小脑", "STM32 + 6 轴 IMU", "doing")

    # ── L5 执行层
    y = ys[4]
    tab(y, "执行层", "ACTUATION", "5B8FB9")
    rect(s, PX, y, PW, LH, fill=WHITE, line=LINE, line_w=0.75)
    box(ix, y + by, iw, "串行总线　→　22 路总线舵机（双腿 10 · 双臂 8 · 躯干 2 · 头部 2）",
        size=11, line=LINE)
    bracket(y, LH, "执行", "22 路串行总线", "done")

    # ── 底部三条设计原则
    fy = ys[4] + LH + 0.14
    rect(s, CONTENT_X, fy, CONTENT_W, 0.38, fill=MIST)
    principles = [
        "上层不关心下层怎么实现",
        "下层不关心任务是什么",
        "两层之间只传一份 JSON 协议",
    ]
    seg = CONTENT_W / 3
    for i, p in enumerate(principles):
        text(s, CONTENT_X + i * seg + 0.22, fy, seg - 0.30, 0.38,
             [P([R(f"0{i+1}", 10, ORANGE, heavy=True),
                 R("　" + p, 10.5, GRAPHITE)])],
             anchor=MSO_ANCHOR.MIDDLE)
        if i:
            vline(s, CONTENT_X + i * seg, fy, 0.38, color=BLUE_300, width=0.75)

    status_bar(s, ["done", "doing", "plan"])
    return s


# ══════════════════════ P37 · 任务四 · 体育运动（踢球）══════════════════════
def slide_task_kick(prs):
    s = add_slide(prs, PAPER)
    page_frame(s, "04", "五项任务闭环", 37)
    page_title(
        s,
        "球在哪，机器人自己转过去——位置不对就再调一次",
        lead="这一步不是播放一段预设动画，而是一条带阈值的反馈回路。",
    )

    # ── 左：场景配图
    IMG_X, IMG_W = CONTENT_X, 4.44
    IMG_H = 4.16
    img = OUT.parent / "assets" / "task-kick.png"
    if img.exists():
        picture_cover(s, IMG_X, Y_BODY, IMG_W, IMG_H, str(img), focus_x=0.51)
    else:
        rect(s, IMG_X, Y_BODY, IMG_W, IMG_H, fill=MIST, line=BLUE_300)
        text(s, IMG_X, Y_BODY + IMG_H / 2 - 0.2, IMG_W, 0.4,
             [P([R("配图位 · task-kick", 11, BLUE, heavy=True)],
                align=PP_ALIGN.CENTER)])

    # ── 右：三块
    CX, CW = 5.57, 6.93

    # ① 流程链
    text(s, CX, Y_BODY, CW, 0.24,
         [P([R("① 流程链", 10.5, BLUE, heavy=True)])])
    steps = ["检测球位", "计算横向误差", "朝向伺服", "执行踢球"]
    cw = (CW - 3 * 0.30) / 4
    for i, t in enumerate(steps):
        x = CX + i * (cw + 0.30)
        rect(s, x, Y_BODY + 0.28, cw, 0.50, fill=WHITE, line=BLUE_300)
        text(s, x + 0.06, Y_BODY + 0.28, cw - 0.12, 0.50,
             [P([R(t, 10.5, INK, heavy=True)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)
        if i < 3:
            arrow(s, x + cw + 0.05, Y_BODY + 0.53, 0.20)

    # ② 技术要点
    ty = Y_BODY + 1.00
    text(s, CX, ty, CW, 0.24,
         [P([R("② 技术要点", 10.5, BLUE, heavy=True)])])
    pts = [
        ("误差判据", "横向偏差 |x| > 1.0 cm 就触发修正；阈值为 0 会让机器人在噪声里来回抖。"),
        ("控制律", "yaw = clamp(x / 2, −10°, +10°)——比例增益 1/2，单步限幅 10° 防止过冲震荡。"),
        ("收敛后动作", "按球的偏向选左右脚，进入预标定踢球序列；动作先在仿真里标定，再迁移实机。"),
    ]
    y = ty + 0.30
    for name, desc in pts:
        rect(s, CX, y + 0.045, 0.055, 0.055, fill=ORANGE, shape=MSO_SHAPE.OVAL)
        text(s, CX + 0.20, y - 0.02, CW - 0.20, 0.24,
             [P([R(name + "　", 11, INK, heavy=True), R(desc, 10.5, GRAPHITE)])])
        y += 0.52

    # ③ 指标与状态
    by = Y_BODY + 3.06
    rect(s, CX, by, CW, 1.10, fill=MIST)
    text(s, CX + 0.22, by + 0.15, CW - 0.44, 0.24,
         [P([R("③ 考核指标", 10, BLUE, heavy=True)])])
    text(s, CX + 0.22, by + 0.45, CW - 1.7, 0.34,
         [P([R("踢球成功率 ", 12, GRAPHITE), R("≥ 70%", 17, ORANGE, heavy=True),
             R("　（球距 10–20 cm）", 11, GRAY)])])
    text(s, CX + 0.22, by + 0.82, CW - 0.44, 0.22,
         [P([R("yaw = max(-10.0, min(10.0, ball_x / 2.0))    # atri/skills/kick.py",
             9, GRAY)])])
    status_chip(s, CX + CW - 1.28, by + 0.14, "doing", size=10)

    status_bar(s, ["done", "doing", "plan"])
    return s


def main():
    stem = sys.argv[1] if len(sys.argv) > 1 else "ATRI_答辩PPT-样张"
    prs = new_deck()
    slide_cover(prs)
    slide_summary(prs)
    slide_architecture(prs)
    slide_task_kick(prs)
    path = OUT / f"{stem}.pptx"
    prs.save(str(path))
    print("saved:", path)


if __name__ == "__main__":
    main()
