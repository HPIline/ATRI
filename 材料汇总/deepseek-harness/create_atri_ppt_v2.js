// A.T.R.I. 宣传PPT v2（PPTX 交差版：深色赛博 + AI 主视觉）
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
const assets = "A.T.R.I.-宣传PPT-v2/assets/";

const BG = "0A0F1F";
const CARD = "131C36";
const CARD2 = "182248";
const LINE = "28406E";
const CYAN = "00E5FF";
const VIOLET = "8B5CF6";
const GREEN = "34D399";
const AMBER = "FBBF24";
const TEXT = "F5F7FF";
const SUB = "A8B3D0";
const DIM = "6C7A9E";
const FONT = "微软雅黑";
const FONT_EN = "Arial";

function setSlideBg(slide) {
  slide.background = { color: BG };
  // 光晕装饰
  slide.addShape(pres.ShapeType.ellipse, { x: 10.7, y: -1.4, w: 4.6, h: 4.6, fill: { color: CYAN, transparency: 90 }, line: { type: "none" } });
  slide.addShape(pres.ShapeType.ellipse, { x: -1.6, y: 4.6, w: 4.2, h: 4.2, fill: { color: VIOLET, transparency: 92 }, line: { type: "none" } });
}

function addHeader(slide, kicker, title) {
  slide.addText(kicker, { x: 0.6, y: 0.35, w: 11, h: 0.35, fontSize: 11, fontFace: FONT_EN, bold: true, charSpacing: 3, color: CYAN, margin: 0 });
  slide.addText(title, { x: 0.55, y: 0.68, w: 12, h: 0.8, fontSize: 28, fontFace: FONT, bold: true, color: TEXT, margin: 0 });
}

function card(slide, x, y, w, h, title, body, accent = CYAN, titleSize = 15, bodySize = 11) {
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: CARD }, line: { color: LINE, width: 1 }, shadow: { color: "000000", blur: 12, offset: 3, angle: 90, opacity: 0.3 } });
  slide.addShape(pres.ShapeType.ellipse, { x: x + 0.18, y: y + 0.18, w: 0.16, h: 0.16, fill: { color: accent }, line: { type: "none" } });
  slide.addText(title, { x: x + 0.25, y: y + 0.45, w: w - 0.5, h: 0.4, fontSize: titleSize, fontFace: FONT, bold: true, color: TEXT, margin: 0 });
  slide.addText(body, { x: x + 0.25, y: y + 0.9, w: w - 0.5, h: h - 1.05, fontSize: bodySize, fontFace: FONT, color: SUB, margin: 0, valign: "top", lineSpacing: 12 });
}

function addFooter(slide, n) {
  slide.addText("A.T.R.I. · 人形机器人专项 · 小人形组", { x: 0.55, y: 7.08, w: 6, h: 0.3, fontSize: 9, fontFace: FONT_EN, color: DIM, margin: 0 });
  slide.addText(String(n).padStart(2, "0"), { x: 12.35, y: 7.08, w: 0.45, h: 0.3, fontSize: 10, fontFace: FONT_EN, bold: true, color: DIM, align: "right", margin: 0 });
}

let s = pres.addSlide();
setSlideBg(s);
s.addImage({ path: assets + "hero-robot.png", x: 0, y: 0, w: 13.3, h: 7.5 });
s.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: 13.3, h: 7.5, fill: { color: "05070D", transparency: 28 }, line: { type: "none" } });
s.addText("中国国际大学生创新大赛（2026）· 陕西赛区特色专项 · 人形机器人专项 · 小人形组", { x: 0.7, y: 0.5, w: 12, h: 0.4, fontSize: 12, fontFace: FONT, color: SUB, align: "center", margin: 0 });
s.addText("A.T.R.I.", { x: 0.6, y: 1.9, w: 12.1, h: 1.5, fontSize: 66, fontFace: FONT_EN, bold: true, color: "FFFFFF", align: "center", margin: 0, charSpacing: 5 });
s.addText("桌面自主人形智能", { x: 0.6, y: 3.45, w: 12.1, h: 0.7, fontSize: 28, fontFace: FONT, bold: true, color: CYAN, align: "center", margin: 0 });
s.addText("Autonomous Tabletop Robotic Intelligence", { x: 0.6, y: 4.2, w: 12.1, h: 0.45, fontSize: 13, fontFace: FONT_EN, italic: true, color: SUB, align: "center", margin: 0 });
s.addText("一台机器人，跑完五项任务", { x: 0.6, y: 4.9, w: 12.1, h: 0.6, fontSize: 20, fontFace: FONT, bold: true, color: "D9F8FF", align: "center", margin: 0 });
s.addText("评审遴选汇报 · 项目简称 A.T.R.I. · 西安交通大学", { x: 0.6, y: 6.2, w: 12.1, h: 0.5, fontSize: 13, fontFace: FONT, color: DIM, align: "center", margin: 0 });

// S2 价值主张
s = pres.addSlide(); setSlideBg(s); addFooter(s, 2);
s.addText("VALUE PROPOSITION", { x: 0.6, y: 0.9, w: 11, h: 0.35, fontSize: 12, fontFace: FONT_EN, bold: true, charSpacing: 3, color: CYAN, margin: 0 });
s.addText("我们不是做一台“会走路的机器人”，\n而是把五项人形机器人任务，压缩成一张可配置的任务卡。", { x: 0.8, y: 1.6, w: 11.7, h: 3.0, fontSize: 32, fontFace: FONT, bold: true, color: TEXT, align: "center", valign: "middle", margin: 0, lineSpacing: 20 });
["统一任务描述", "离线自主执行", "低成本可复现"].forEach((t, i) => {
  card(s, 1.2 + i * 3.6, 5.0, 3.1, 0.8, t, "", CYAN, 15, 10);
});

// S3 痛点
s = pres.addSlide(); setSlideBg(s); addHeader(s, "PROBLEM", "现在的人形机器人教育，贵、散、封闭"); addFooter(s, 3);
card(s, 0.7, 2.0, 3.8, 3.0, "贵", "全尺寸人形机器人体积大、价格高，本科教学难以大规模配置。", "F87171", 26, 14);
card(s, 4.75, 2.0, 3.8, 3.0, "散", "五大任务散落在不同平台，训练、演示和交接成本都很高。", "FBBF24", 26, 14);
card(s, 8.8, 2.0, 3.8, 3.0, "封闭", "成品竞赛套件上手快，但软件固定，二次开发与任务扩展困难。", "8B5CF6", 26, 14);
s.addText("所以，我们做了 A.T.R.I.", { x: 0.7, y: 5.6, w: 11.9, h: 0.7, fontSize: 20, fontFace: FONT, bold: true, color: "CFF7FF", align: "center", margin: 0 });

// S4 系统总览
s = pres.addSlide(); setSlideBg(s); addHeader(s, "SYSTEM OVERVIEW", "一张图看懂 A.T.R.I."); addFooter(s, 4);
const flows = [
  ["任务卡", "JSON 描述指令与参数", CYAN],
  ["大脑", "视觉 / 决策 / 离线语音", VIOLET],
  ["小脑", "步态 / 姿态 / 舵机", GREEN],
  ["机器人", "22 自由度双足平台", AMBER]
];
flows.forEach((f, i) => {
  const x = 0.75 + i * 3.05;
  s.addShape(pres.ShapeType.roundRect, { x, y: 2.15, w: 2.7, h: 2.4, rectRadius: 0.1, fill: { color: CARD2 }, line: { color: f[2], width: 1.25 } });
  s.addText(f[0], { x, y: 2.6, w: 2.7, h: 0.6, fontSize: 24, fontFace: FONT, bold: true, color: f[2], align: "center", margin: 0 });
  s.addText(f[1], { x: x + 0.15, y: 3.3, w: 2.4, h: 1.0, fontSize: 12, fontFace: FONT, color: SUB, align: "center", margin: 0 });
  if (i < flows.length - 1) s.addShape(pres.ShapeType.rightArrow, { x: x + 2.72, y: 2.95, w: 0.32, h: 0.7, fill: { color: "8B5CF6" }, line: { type: "none" } });
});
s.addText("全程本地处理 · 默认离线运行 · 断网后继续自主工作", { x: 0.75, y: 5.4, w: 11.8, h: 0.7, fontSize: 18, fontFace: FONT, bold: true, color: "CFF7FF", align: "center", margin: 0 });

// S5 核心创新
s = pres.addSlide(); setSlideBg(s); addHeader(s, "CORE INNOVATION", "核心技术链：不是堆模块，而是一条技术链"); addFooter(s, 5);
const chain = [
  ["01", "任务卡", "统一描述任务与参数", CYAN],
  ["02", "状态机", "多任务统一调度", VIOLET],
  ["03", "技能库", "动作/语音/视觉复用", GREEN],
  ["04", "感知闭环", "检测→调整→再检测→执行", AMBER]
];
chain.forEach((c, i) => {
  const x = 0.55 + i * 3.05;
  s.addShape(pres.ShapeType.roundRect, { x, y: 2.1, w: 2.8, h: 2.5, rectRadius: 0.1, fill: { color: CARD }, line: { color: c[3], width: 1.2 } });
  s.addText(c[0], { x, y: 2.35, w: 2.8, h: 0.5, fontSize: 20, fontFace: FONT_EN, bold: true, color: c[3], align: "center", margin: 0 });
  s.addText(c[1], { x, y: 2.95, w: 2.8, h: 0.6, fontSize: 22, fontFace: FONT, bold: true, color: TEXT, align: "center", margin: 0 });
  s.addText(c[2], { x: x + 0.2, y: 3.6, w: 2.4, h: 0.9, fontSize: 11.5, fontFace: FONT, color: SUB, align: "center", margin: 0 });
  if (i < chain.length - 1) s.addShape(pres.ShapeType.rightArrow, { x: x + 2.82, y: 3.0, w: 0.24, h: 0.6, fill: { color: "8B5CF6" }, line: { type: "none" } });
});
s.addText("新增任务 = 增加一张任务卡 + 一个技能模块，不需要重写整机逻辑。", { x: 0.55, y: 5.3, w: 12.2, h: 0.8, fontSize: 18, fontFace: FONT, bold: true, color: "D9F8FF", align: "center", margin: 0 });

// S6 五项任务
s = pres.addSlide(); setSlideBg(s); addHeader(s, "FIVE MISSIONS", "五项任务，一个平台"); addFooter(s, 6);
const missions = [
  ["01", "人脸识别", "检测 → 特征 → 匹配 → 播报", CYAN],
  ["02", "二维码循迹", "识别 → 解码 → 按路径行走", VIOLET],
  ["03", "物品搬运", "检测 → 对齐 → 抓取 → 释放", GREEN],
  ["04", "体育运动", "定位 → 调整朝向 → 踢球", AMBER],
  ["05", "娱乐休闲", "关键词 → 动作 → 语音 → 音乐", "F87171"]
];
missions.forEach((m, i) => {
  const x = 0.5 + i * 2.47;
  card(s, x, 2.0, 2.3, 3.0, m[0] + " " + m[1], m[2], m[3], 14, 11);
});
s.addText("同一套硬件与状态机，切换任务只需换一张任务卡。", { x: 0.5, y: 5.6, w: 12.3, h: 0.7, fontSize: 18, fontFace: FONT, bold: true, color: "CFF7FF", align: "center", margin: 0 });

// S7 全离线
s = pres.addSlide(); setSlideBg(s); addHeader(s, "OFFLINE BY DEFAULT", "默认离线，断网也能自主"); addFooter(s, 7);
s.addText("OFFLINE", { x: 0.75, y: 1.9, w: 4.5, h: 1.5, fontSize: 60, fontFace: FONT_EN, bold: true, color: CYAN, margin: 0 });
s.addText("拔掉网线，任务继续。", { x: 0.75, y: 3.4, w: 4.5, h: 0.7, fontSize: 22, fontFace: FONT, bold: true, color: "D9F8FF", margin: 0 });
card(s, 5.5, 1.9, 7.2, 1.5, "全部本地处理", "人脸、二维码、语音、状态机全部在板载计算单元运行。", CYAN, 16, 12);
card(s, 5.5, 3.55, 7.2, 1.5, "不怕现场断网", "现场关闭网络后，识别、决策、控制与交互继续执行。", GREEN, 16, 12);
card(s, 5.5, 5.2, 7.2, 1.5, "数据不出设备", "适合课堂、竞赛与实验室等敏感场景。", VIOLET, 16, 12);

// S8 硬件实力
s = pres.addSlide(); setSlideBg(s); addHeader(s, "HARDWARE", "22 个自由度，3 个关键数字"); addFooter(s, 8);
s.addImage({ path: assets + "hardware-exploded.png", x: 7.2, y: 1.7, w: 5.5, h: 5.2 });
const stats = [
  ["22", "DOF", "双腿 10 · 双臂 8 · 躯干 2 · 头部 2"],
  ["37.3", "cm", "桌面级紧凑尺寸，适合实验室与教室"],
  ["¥3600", "样机预算", "复用实验室设备，低成本可复现"]
];
stats.forEach((st, i) => {
  const y = 1.9 + i * 1.45;
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y, w: 6.0, h: 1.15, rectRadius: 0.08, fill: { color: CARD }, line: { color: LINE, width: 1 } });
  s.addText(st[0], { x: 0.9, y: y + 0.1, w: 2.5, h: 0.9, fontSize: 34, fontFace: FONT_EN, bold: true, color: CYAN, margin: 0 });
  s.addText(st[1], { x: 3.4, y: y + 0.3, w: 1.3, h: 0.5, fontSize: 14, fontFace: FONT, bold: true, color: "8BEFFF", margin: 0 });
  s.addText(st[2], { x: 4.6, y: y + 0.15, w: 2.0, h: 0.85, fontSize: 10.5, fontFace: FONT, color: SUB, margin: 0, valign: "middle" });
});

// S9 为什么选我们
s = pres.addSlide(); setSlideBg(s); addHeader(s, "WHY US", "为什么是我们"); addFooter(s, 9);
card(s, 0.7, 1.9, 3.8, 2.8, "低成本", "自组构型 + 实验室设备复用，样机预算约 ¥3600。", CYAN, 20, 13);
card(s, 4.75, 1.9, 3.8, 2.8, "一体化", "五项任务共享同一套软硬件，一机完成全部赛题。", VIOLET, 20, 13);
card(s, 8.8, 1.9, 3.8, 2.8, "可扩展", "任务卡化配置，课程、竞赛、二次开发都能复用。", GREEN, 20, 13);
s.addText("全尺寸人形 ➜ 教育双足 ➜ 成品套件  →  A.T.R.I.", { x: 0.7, y: 5.4, w: 11.9, h: 0.7, fontSize: 17, fontFace: FONT, bold: true, color: "CFF7FF", align: "center", margin: 0 });

// S10 团队
s = pres.addSlide(); setSlideBg(s); addHeader(s, "TEAM", "计算机 × 电子 × 自动化"); addFooter(s, 10);
s.addText("学科交叉，覆盖感知、控制、硬件与系统集成", { x: 0.7, y: 1.7, w: 11.9, h: 0.5, fontSize: 16, fontFace: FONT, bold: true, color: "B794FF", align: "center", margin: 0 });
const team = [
  ["何", "何浩睿", "项目负责人", "机械结构 · 双足步态 · 舵机配置"],
  ["周", "周柏宇", "项目统筹", "系统集成 · 报名答辩"],
  ["胡", "胡晟瑞", "视觉感知", "人脸识别 · 二维码 · 物体检测"],
  ["王", "王旭琪", "交互与仿真", "状态机 · 离线语音 · 仿真环境"],
  ["张", "张景昆", "自动化 · 新增", "运动控制 · 硬件支持"]
];
team.forEach((m, i) => {
  const x = 0.5 + i * 2.5;
  s.addShape(pres.ShapeType.roundRect, { x, y: 2.5, w: 2.3, h: 3.2, rectRadius: 0.1, fill: { color: CARD }, line: { color: LINE, width: 1 } });
  s.addShape(pres.ShapeType.ellipse, { x: x + 0.78, y: 2.8, w: 0.75, h: 0.75, fill: { color: "1B2450" }, line: { color: CYAN, width: 1.5 } });
  s.addText(m[0], { x: x + 0.78, y: 2.88, w: 0.75, h: 0.6, fontSize: 20, fontFace: FONT, bold: true, color: "FFFFFF", align: "center", margin: 0 });
  s.addText(m[1], { x, y: 3.75, w: 2.3, h: 0.5, fontSize: 16, fontFace: FONT, bold: true, color: TEXT, align: "center", margin: 0 });
  s.addText(m[2], { x, y: 4.3, w: 2.3, h: 0.4, fontSize: 11, fontFace: FONT, bold: true, color: CYAN, align: "center", margin: 0 });
  s.addText(m[3], { x: x + 0.15, y: 4.8, w: 2.0, h: 0.8, fontSize: 10, fontFace: FONT, color: SUB, align: "center", margin: 0 });
});
s.addText("指导老师：陈妍 · 李璐（技术方向把关 / 设备协调）", { x: 0.7, y: 6.2, w: 11.9, h: 0.5, fontSize: 14, fontFace: FONT, bold: true, color: TEXT, align: "center", margin: 0 });

// S11 路线
s = pres.addSlide(); setSlideBg(s); addHeader(s, "ROADMAP", "先验证，再投入"); addFooter(s, 11);
const phases = [
  ["报名与方案", "合规构型 + 五项任务路线", "0–100 元", CYAN],
  ["仿真 / 借机", "跑通五项任务最小闭环", "0–500 元", GREEN],
  ["自组样机", "22 DOF 样机逐项联调", "1500–3500 元", AMBER],
  ["省赛冲刺", "补强演示与训练数据", "按经费/赞助", VIOLET]
];
phases.forEach((p, i) => {
  const x = 0.6 + i * 3.1;
  s.addShape(pres.ShapeType.roundRect, { x, y: 2.2, w: 2.8, h: 3.0, rectRadius: 0.1, fill: { color: CARD }, line: { color: p[3], width: 1.2 } });
  s.addText(p[0], { x, y: 2.6, w: 2.8, h: 0.6, fontSize: 19, fontFace: FONT, bold: true, color: p[3], align: "center", margin: 0 });
  s.addText(p[1], { x: x + 0.15, y: 3.3, w: 2.5, h: 0.9, fontSize: 12, fontFace: FONT, color: SUB, align: "center", margin: 0 });
  s.addText(p[2], { x: x + 0.3, y: 4.3, w: 2.2, h: 0.5, fontSize: 12, fontFace: FONT, bold: true, color: "CFF7FF", align: "center", margin: 0 });
});
s.addText("同一套任务卡与接口贯穿全程，进展可平滑迁移、可留痕。", { x: 0.6, y: 5.8, w: 12.1, h: 0.7, fontSize: 17, fontFace: FONT, bold: true, color: "CFF7FF", align: "center", margin: 0 });

// S12 可信度
s = pres.addSlide(); setSlideBg(s); addHeader(s, "CREDIBILITY", "为什么我们说的不是空话"); addFooter(s, 12);
card(s, 0.7, 2.0, 3.8, 2.8, "仿真先行", "Webots / PyBullet 先验证步态与视觉任务，不烧硬件盲试。", CYAN, 18, 13);
card(s, 4.75, 2.0, 3.8, 2.8, "借机联调", "优先借用实验室双足平台，跑通最小闭环并录制证据。", GREEN, 18, 13);
card(s, 8.8, 2.0, 3.8, 2.8, "研发日志", "设计、代码、测试、BOM 同步留痕，材料可追溯。", VIOLET, 18, 13);
s.addText("“仿真 → 借机 → 样机”共用同一套接口，验证结果直接迁移。", { x: 0.7, y: 5.5, w: 11.9, h: 0.7, fontSize: 17, fontFace: FONT, bold: true, color: "CFF7FF", align: "center", margin: 0 });

// S13 愿景
s = pres.addSlide(); setSlideBg(s); addFooter(s, 13);
s.addImage({ path: assets + "lab-vision.png", x: 0, y: 0, w: 13.3, h: 7.5 });
s.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: 13.3, h: 7.5, fill: { color: "04060B", transparency: 25 }, line: { type: "none" } });
s.addText("VISION", { x: 0.6, y: 1.6, w: 11, h: 0.4, fontSize: 13, fontFace: FONT_EN, bold: true, charSpacing: 3, color: CYAN, align: "center", margin: 0 });
s.addText("让低成本桌面双足机器人，成为具身智能教育的公共基础设施。", { x: 0.9, y: 2.4, w: 11.5, h: 2.0, fontSize: 30, fontFace: FONT, bold: true, color: "FFFFFF", align: "center", valign: "middle", margin: 0 });
["可复现", "可扩展", "可负担"].forEach((t, i) => card(s, 1.5 + i * 3.5, 5.0, 2.9, 0.8, t, "", CYAN, 16, 10));

// S14 结尾
s = pres.addSlide(); setSlideBg(s); addFooter(s, 14);
s.addImage({ path: assets + "hero-robot.png", x: 0, y: 0, w: 13.3, h: 7.5 });
s.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: 13.3, h: 7.5, fill: { color: "04060B", transparency: 22 }, line: { type: "none" } });
s.addText("A.T.R.I.", { x: 0.6, y: 2.0, w: 12.1, h: 1.2, fontSize: 56, fontFace: FONT_EN, bold: true, color: "FFFFFF", align: "center", margin: 0 });
s.addText("一台机器人，一个统一任务链，让具身智能实验走进课堂与赛场。", { x: 0.8, y: 3.4, w: 11.7, h: 0.8, fontSize: 22, fontFace: FONT, bold: true, color: "D9F8FF", align: "center", margin: 0 });
s.addText("恳请各位专家给予支持与指导", { x: 0.6, y: 4.5, w: 12.1, h: 0.6, fontSize: 18, fontFace: FONT, color: TEXT, align: "center", margin: 0 });
s.addText("A.T.R.I. 项目组 · 西安交通大学\n项目负责人：何浩睿 ｜ 指导老师：陈妍 · 李璐", { x: 0.6, y: 5.6, w: 12.1, h: 0.8, fontSize: 14, fontFace: FONT, color: SUB, align: "center", margin: 0 });

pres.writeFile({ fileName: "A.T.R.I.-宣传PPT-交差版.pptx" }).then(f => console.log("WROTE", f)).catch(e => { console.error(e); process.exit(1); });