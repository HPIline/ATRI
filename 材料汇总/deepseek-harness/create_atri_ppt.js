// A.T.R.I. 评审遴选宣传 PPT 生成脚本
// 运行：NODE_PATH=... node create_atri_ppt.js
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5

// ---------- 主题 ----------
const BG = "0A0F1F";
const CARD = "111A33";
const CARD2 = "16213F";
const LINE = "223052";
const CYAN = "00E5FF";
const VIOLET = "8B5CF6";
const GREEN = "34D399";
const AMBER = "FBBF24";
const RED = "F87171";
const TEXT = "F5F7FF";
const SUB = "A8B3D0";
const DIM = "6C7A9E";
const WHITE = "FFFFFF";

const FONT = "微软雅黑";
const FONT_EN = "Arial";

function setSlide(pres, slide, bg = BG) {
  slide.background = { color: bg };
}

// 新鲜 shadow 对象，避免共享对象被 mutate
function cardShadow() {
  return { color: "000000", blur: 12, offset: 4, angle: 90, opacity: 0.35 };
}

function addHeader(slide, kicker, title, color = WHITE) {
  slide.addText(kicker, {
    x: 0.55, y: 0.32, w: 11.0, h: 0.32,
    fontSize: 11, fontFace: FONT_EN, bold: true, charSpacing: 2,
    color: CYAN, margin: 0
  });
  slide.addText(title, {
    x: 0.5, y: 0.62, w: 11.5, h: 0.85,
    fontSize: 30, fontFace: FONT, bold: true, color: color, margin: 0
  });
}

function addFooter(slide, idx) {
  slide.addText("A.T.R.I. · 人形机器人专项 · 小人形组", {
    x: 0.5, y: 7.05, w: 6.0, h: 0.3,
    fontSize: 9, fontFace: FONT_EN, color: DIM, margin: 0
  });
  slide.addText(String(idx).padStart(2, "0"), {
    x: 12.35, y: 7.05, w: 0.45, h: 0.3,
    fontSize: 10, fontFace: FONT_EN, bold: true, color: DIM, align: "right", margin: 0
  });
}

function addCard(slide, x, y, w, h, title, body, accent = CYAN, opts = {}) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.08,
    fill: { color: CARD, transparency: opts.fillTransparency || 0 },
    line: { color: LINE, width: 0.75 },
    shadow: cardShadow()
  });
  // 左上角小圆点作为视觉锚点（不是色条）
  slide.addShape(pres.ShapeType.ellipse, {
    x: x + 0.18, y: y + 0.18, w: 0.16, h: 0.16,
    fill: { color: accent }, line: { type: "none" }
  });
  slide.addText(title, {
    x: x + 0.2, y: y + 0.42, w: w - 0.4, h: 0.4,
    fontSize: opts.titleSize || 15, fontFace: FONT, bold: true, color: TEXT, margin: 0
  });
  slide.addText(body, {
    x: x + 0.2, y: y + 0.86, w: w - 0.4, h: h - 1.0,
    fontSize: opts.bodySize || 11.5, fontFace: FONT, color: SUB, margin: 0,
    valign: "top", lineSpacing: 12
  });
  if (opts.badge) {
    slide.addText(opts.badge, {
      x: x + w - 1.2, y: y + 0.18, w: 1.0, h: 0.34,
      fontSize: 10, fontFace: FONT, bold: true, color: accent, align: "right", margin: 0
    });
  }
}

function addNumberBadge(slide, x, y, d, num, color = CYAN) {
  slide.addShape(pres.ShapeType.ellipse, {
    x, y, w: d, h: d,
    fill: { color, transparency: 82 }, line: { color: color, width: 1.25 }
  });
  slide.addText(num, {
    x, y, w: d, h: d,
    fontSize: d * 0.36, fontFace: FONT_EN, bold: true, color: color, align: "center", valign: "middle", margin: 0
  });
}

// =============================
// S1 封面
// =============================
let s = pres.addSlide();
setSlide(pres, s);
// 背景装饰圆
s.addShape(pres.ShapeType.ellipse, { x: 10.6, y: -1.6, w: 5.2, h: 5.2, fill: { color: CYAN, transparency: 88 }, line: { type: "none" } });
s.addShape(pres.ShapeType.ellipse, { x: -1.8, y: 4.5, w: 4.4, h: 4.4, fill: { color: VIOLET, transparency: 90 }, line: { type: "none" } });
s.addShape(pres.ShapeType.ellipse, { x: 11.5, y: 3.2, w: 2.6, h: 2.6, fill: { color: GREEN, transparency: 90 }, line: { type: "none" } });

// 小型机器人插画（形状构成）
const rx = 9.05, ry = 2.05;
s.addShape(pres.ShapeType.roundRect, { x: rx, y: ry, w: 1.55, h: 1.35, rectRadius: 0.2, fill: { color: "16213F" }, line: { color: CYAN, width: 1.5 } });
s.addShape(pres.ShapeType.roundRect, { x: rx, y: ry + 1.55, w: 1.55, h: 1.7, rectRadius: 0.12, fill: { color: "16213F" }, line: { color: LINE, width: 1 } });
s.addShape(pres.ShapeType.ellipse, { x: rx + 0.22, y: ry + 0.34, w: 0.36, h: 0.36, fill: { color: CYAN }, line: { type: "none" } });
s.addShape(pres.ShapeType.ellipse, { x: rx + 0.95, y: ry + 0.34, w: 0.36, h: 0.36, fill: { color: CYAN }, line: { type: "none" } });
s.addShape(pres.ShapeType.rect, { x: rx + 0.6, y: ry + 0.62, w: 0.36, h: 0.1, fill: { color: CYAN }, line: { type: "none" } });
// 天线
s.addShape(pres.ShapeType.line, { x: rx + 0.75, y: ry - 0.05, w: 0, h: 0.42, line: { color: CYAN, width: 1.5 } });
s.addShape(pres.ShapeType.ellipse, { x: rx + 0.65, y: ry - 0.18, w: 0.2, h: 0.2, fill: { color: CYAN }, line: { type: "none" } });
// 腿
s.addShape(pres.ShapeType.rect, { x: rx + 0.25, y: ry + 3.25, w: 0.32, h: 0.85, fill: { color: LINE }, line: { type: "none" } });
s.addShape(pres.ShapeType.rect, { x: rx + 0.95, y: ry + 3.25, w: 0.32, h: 0.85, fill: { color: LINE }, line: { type: "none" } });

s.addText("中国国际大学生创新大赛（2026）· 陕西赛区特色专项 · 人形机器人专项 · 小人形组", {
  x: 0.6, y: 0.55, w: 12.1, h: 0.4,
  fontSize: 12, fontFace: FONT, color: SUB, align: "center", margin: 0
});
s.addText("A.T.R.I.", {
  x: 0.6, y: 1.5, w: 12.1, h: 1.5,
  fontSize: 72, fontFace: FONT_EN, bold: true, color: WHITE, align: "center", margin: 0, charSpacing: 6
});
s.addText("桌面自主人形智能", {
  x: 0.6, y: 3.05, w: 12.1, h: 0.7,
  fontSize: 30, fontFace: FONT, bold: true, color: CYAN, align: "center", margin: 0
});
s.addText("Autonomous Tabletop Robotic Intelligence", {
  x: 0.6, y: 3.8, w: 12.1, h: 0.45,
  fontSize: 13, fontFace: FONT_EN, italic: true, color: SUB, align: "center", margin: 0
});
s.addText("一台机器人，离线完成人形机器人专项五项任务", {
  x: 0.6, y: 4.5, w: 12.1, h: 0.6,
  fontSize: 18, fontFace: FONT, color: TEXT, align: "center", margin: 0
});
s.addText("评审遴选汇报  |  项目简称：A.T.R.I.  |  西安交通大学", {
  x: 0.6, y: 5.8, w: 12.1, h: 0.5,
  fontSize: 13, fontFace: FONT, color: DIM, align: "center", margin: 0
});

// =============================
// S2 项目速览
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "ONE-LINE INTRO", "项目速览");
addFooter(s, 2);

s.addShape(pres.ShapeType.roundRect, {
  x: 0.55, y: 1.7, w: 12.2, h: 1.15, rectRadius: 0.1,
  fill: { color: CARD2 }, line: { color: CYAN, width: 1 }
});
s.addText("一台低成本桌面双足机器人，把五项比赛任务统一到同一套软硬件框架中，默认全离线自主运行。", {
  x: 0.85, y: 1.85, w: 11.6, h: 0.85,
  fontSize: 16, fontFace: FONT, bold: true, color: TEXT, margin: 0, valign: "middle", align: "center"
});

addCard(s, 0.55, 3.3, 3.9, 2.6, "目标自由度", "22 个主动自由度：双腿各 5、双臂各 4、躯干 2、头部 2，满足小人形组检录要求。", CYAN, { titleSize: 18, badge: "22 DOF" });
addCard(s, 4.7, 3.3, 3.9, 2.6, "五项任务一体", "人脸识别、二维码循迹、物品搬运、体育、娱乐，用 JSON 任务卡统一调度。", VIOLET, { titleSize: 18, badge: "5 TASKS" });
addCard(s, 8.85, 3.3, 3.9, 2.6, "默认离线运行", "识别、解析、决策与动作执行全部本地完成，断网后仍可继续自主工作。", GREEN, { titleSize: 18, badge: "OFFLINE" });

// =============================
// S3 为什么做
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "WHY A.T.R.I.", "为什么做");
addFooter(s, 3);

addCard(s, 0.55, 1.7, 3.9, 2.7, "教育门槛高", "全尺寸人形机器人价格高、体积大，本科教学难以大规模配置和复现。", RED);
addCard(s, 4.7, 1.7, 3.9, 2.7, "竞赛整合难", "人脸、循迹、搬运、体育、娱乐散落在不同平台，训练与演示成本高。", AMBER);
addCard(s, 8.85, 1.7, 3.9, 2.7, "套件不开放", "成品竞赛套件上手快，但软件框架封闭，二次开发与任务扩展受限。", VIOLET);

s.addShape(pres.ShapeType.roundRect, {
  x: 0.55, y: 4.85, w: 12.2, h: 1.4, rectRadius: 0.12,
  fill: { color: CARD2 }, line: { color: CYAN, width: 1 }
});
s.addText("我们的回答：A.T.R.I. = 低成本自组构型  +  五任务统一调度  +  全离线本地推理  +  可二次开发", {
  x: 0.85, y: 4.85, w: 11.6, h: 1.4,
  fontSize: 15, fontFace: FONT, bold: true, color: TEXT, align: "center", valign: "middle", margin: 0
});

// =============================
// S4 赛道合规对照
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "RULE COMPLIANCE", "赛道合规对照");
addFooter(s, 4);

const compliance = [
  ["官方要求", "A.T.R.I. 设计", "状态"],
  ["身高 ≤ 60cm", "目标约 37.3cm", "达标"],
  ["体宽 / 厚 ≤ 30cm", "约 18.7cm × 10.6cm", "达标"],
  ["主动关节 ≥ 18", "22 自由度：腿5×2 / 臂4×2 / 躯干2 / 头2", "达标"],
  ["电源电压 ≥ 7.4V", "11.1V 3S 锂电池组", "达标"],
  ["IMU / 摄像头 / 麦克风 / 扬声器", "6轴IMU · 单目广角相机 · 环形麦克风 · 扬声器", "达标"],
  ["自主离线运行", "默认全离线，断网后继续自主工作", "达标"],
  ["赛道 2400 × 2400mm", "面向五个任务区整体设计", "达标"]
];
const tableRows = compliance.map((r, i) => r.map((cell, j) => {
  const opts = {
    text: cell,
    options: {
      fontSize: 12, fontFace: FONT,
      color: i === 0 ? CYAN : (j === 0 ? TEXT : (j === 1 ? TEXT : GREEN)),
      bold: i === 0 || j === 0, align: j === 2 ? "center" : (i === 0 ? "center" : "left"),
      valign: "middle", margin: [3, 6, 3, 6]
    }
  };
  if (i === 0) opts.options.fill = { color: "1A2544" };
  else opts.options.fill = { color: i % 2 ? CARD : CARD2 };
  return opts;
}));
s.addTable(tableRows, {
  x: 0.55, y: 1.7, w: 12.2,
  colW: [2.9, 6.2, 1.3],
  rowH: 0.52,
  border: { type: "solid", color: LINE, pt: 0.75 },
  autoPage: false,
  valign: "middle"
});
s.addText("* 目标尺寸与构型为当前方案设计值，具体型号与 BOM 在样机阶段逐项确认；所有硬性指标均按官方口径预留余量。", {
  x: 0.55, y: 6.45, w: 12.2, h: 0.5,
  fontSize: 10, fontFace: FONT, color: DIM, margin: 0
});

// =============================
// S5 硬件架构
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "HARDWARE", "硬件架构");
addFooter(s, 5);

// 22 自由度分布
s.addText("22 自由度目标构型", { x: 0.55, y: 1.75, w: 6, h: 0.45, fontSize: 16, fontFace: FONT, bold: true, color: TEXT, margin: 0 });
const dofCards = [
  ["头部 2", "视觉巡视 · 人机示意", CYAN],
  ["躯干 2", "重心调整 · 上身姿态补偿", VIOLET],
  ["双臂 8", "肩2·肘1·夹爪1 × 2（桌面轻物抓取）", GREEN],
  ["双腿 10", "髋3·膝1·踝1 × 2（行走/踢球）", AMBER]
];
dofCards.forEach((d, i) => {
  const x = 0.55 + (i % 2) * 3.15;
  const y = 2.35 + Math.floor(i / 2) * 1.45;
  addCard(s, x, y, 3.0, 1.3, d[0], d[1], d[2], { titleSize: 14, bodySize: 10.5 });
});
s.addText("合计 22 DOF  ≥  官方要求 18 DOF", {
  x: 0.55, y: 5.35, w: 6.0, h: 0.6,
  fontSize: 16, fontFace: FONT, bold: true, color: CYAN, margin: 0
});

// 右侧：感知与供电
s.addText("感知与供电", { x: 7.0, y: 1.75, w: 5.7, h: 0.45, fontSize: 16, fontFace: FONT, bold: true, color: TEXT, margin: 0 });
addCard(s, 7.0, 2.35, 5.75, 1.45, "传感器组", "6 轴 IMU · 单目广角相机 · 环形麦克风 · 扬声器", CYAN, { titleSize: 14 });
addCard(s, 7.0, 3.95, 5.75, 1.45, "电源", "11.1V 3S 锂电池组，满足 ≥7.4V；大脑/小脑/舵机独立供电", GREEN, { titleSize: 14 });
s.addShape(pres.ShapeType.roundRect, {
  x: 7.0, y: 5.55, w: 5.75, h: 1.15, rectRadius: 0.1,
  fill: { color: CARD2 }, line: { color: LINE, width: 0.75 }
});
s.addText("说明：当前为方案级选型，具体舵机/控制板型号在样机阶段按扭矩、重量与供电需求确定。", {
  x: 7.2, y: 5.7, w: 5.35, h: 0.9,
  fontSize: 10.5, fontFace: FONT, color: SUB, margin: 0
});

// =============================
// S6 软件架构
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "SOFTWARE", "软件架构");
addFooter(s, 6);

// 大脑
s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 1.8, w: 5.0, h: 3.6, rectRadius: 0.1, fill: { color: CARD }, line: { color: CYAN, width: 1.25 } });
s.addText("大脑 · 边缘计算板", { x: 1.0, y: 2.05, w: 4.4, h: 0.5, fontSize: 18, fontFace: FONT, bold: true, color: CYAN, margin: 0 });
s.addText("视觉感知：人脸 / 二维码 / 物体 / 球体\n任务状态机：JSON 任务卡解析与调度\n离线语音：本地 TTS 与关键词应答\n高层指令下发：前进 / 转向 / 抓取序列", {
  x: 1.0, y: 2.65, w: 4.4, h: 2.5, fontFace: FONT, fontSize: 13, color: TEXT, margin: 0, lineSpacing: 16
});

// 小脑
s.addShape(pres.ShapeType.roundRect, { x: 6.5, y: 1.8, w: 5.0, h: 3.6, rectRadius: 0.1, fill: { color: CARD }, line: { color: GREEN, width: 1.25 } });
s.addText("小脑 · STM32 + IMU", { x: 6.8, y: 2.05, w: 4.4, h: 0.5, fontSize: 18, fontFace: FONT, bold: true, color: GREEN, margin: 0 });
s.addText("逆运动学（IK）解算\nZMP 步态生成\n姿态闭环与跌倒保护\n22 路总线舵机控制", {
  x: 6.8, y: 2.65, w: 4.4, h: 2.5, fontFace: FONT, fontSize: 13, color: TEXT, margin: 0, lineSpacing: 16
});

// 中间箭头
s.addShape(pres.ShapeType.rightArrow, { x: 5.85, y: 3.0, w: 0.55, h: 0.8, fill: { color: VIOLET }, line: { type: "none" } });
s.addText("高层指令", { x: 5.75, y: 3.85, w: 0.75, h: 0.4, fontSize: 9, fontFace: FONT, color: SUB, align: "center", margin: 0 });

s.addShape(pres.ShapeType.roundRect, {
  x: 0.7, y: 5.7, w: 10.8, h: 1.0, rectRadius: 0.1,
  fill: { color: CARD2 }, line: { color: LINE, width: 0.75 }
});
s.addText("同一套任务卡与接口贯穿仿真、借机、样机三阶段，模块可独立替换、逐步增加真实硬件。", {
  x: 1.0, y: 5.8, w: 10.2, h: 0.8,
  fontSize: 12.5, fontFace: FONT, color: SUB, align: "center", valign: "middle", margin: 0
});

// =============================
// S7 五项任务
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "FIVE MISSIONS", "五项任务实现路线");
addFooter(s, 7);

const tasks = [
  ["人脸识别", "检测 → 特征 → 匹配 → TTS 播报", CYAN],
  ["二维码循迹", "识别 → 透视矫正 → JSON → 状态机", GREEN],
  ["物品搬运", "检测 → 对齐 → 抓取 → 平移 → 释放", AMBER],
  ["体育运动", "球体定位 → 调整朝向 → 踢球", RED],
  ["娱乐休闲", "关键词 → 动作 → 语音 → 音乐", VIOLET]
];
const cardW = 2.35;
const gap = 0.16;
const startX = 0.45;
tasks.forEach((t, i) => {
  const x = startX + i * (cardW + gap);
  addCard(s, x, 1.85, cardW, 3.3, t[0], t[1], t[2], { titleSize: 15, bodySize: 11 });
  addNumberBadge(s, x + cardW - 0.55, 2.1, 0.38, String(i + 1), t[2]);
});
s.addShape(pres.ShapeType.roundRect, {
  x: 0.45, y: 5.5, w: 12.3, h: 1.05, rectRadius: 0.1,
  fill: { color: CARD2 }, line: { color: CYAN, width: 1 }
});
s.addText("五项任务共享同一套硬件与状态机，通过 JSON 任务卡即可切换，无需更换机器人。", {
  x: 0.75, y: 5.6, w: 11.7, h: 0.85,
  fontSize: 14, fontFace: FONT, bold: true, color: TEXT, align: "center", valign: "middle", margin: 0
});

// =============================
// S8 核心技术链
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "CORE TECH CHAIN", "核心技术链");
addFooter(s, 8);

const chain = [
  ["JSON 任务卡", "统一描述任务指令与参数", CYAN],
  ["状态机调度", "待机→进入→执行→反馈", GREEN],
  ["技能库", "动作/语音/视觉技能模块复用", AMBER],
  ["感知反馈闭环", "检测误差→调整→再次检测→执行", RED],
  ["本地推理", "全程离线，断网继续运行", VIOLET]
];
const flowX = [0.55, 3.1, 5.65, 8.2, 10.75];
flowX.forEach((x, i) => {
  addCard(s, x, 2.0, 2.25, 2.0, chain[i][0], chain[i][1], chain[i][2], { titleSize: 13, bodySize: 10.5 });
  if (i < chain.length - 1) {
    s.addShape(pres.ShapeType.rightArrow, { x: x + 2.28, y: 2.72, w: 0.46, h: 0.5, fill: { color: DIM }, line: { type: "none" } });
  }
});
s.addShape(pres.ShapeType.roundRect, {
  x: 0.55, y: 4.55, w: 12.2, h: 1.9, rectRadius: 0.12,
  fill: { color: CARD2 }, line: { color: CYAN, width: 1 }
});
s.addText("创新点不是“把模块堆在一起”", {
  x: 0.85, y: 4.8, w: 11.6, h: 0.5,
  fontSize: 18, fontFace: FONT, bold: true, color: CYAN, margin: 0
});
s.addText("而是让“任务描述 → 决策调度 → 技能执行 → 感知反馈”形成一条可在低算力、离线环境下运行的技术链；新增任务只需增加任务卡和技能模块，不必重写整机逻辑。", {
  x: 0.85, y: 5.35, w: 11.6, h: 1.0,
  fontSize: 13, fontFace: FONT, color: TEXT, margin: 0, lineSpacing: 14
});

// =============================
// S9 优势一：全离线
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "ADVANTAGE 01", "核心优势一：全离线本地推理");
addFooter(s, 9);

s.addShape(pres.ShapeType.roundRect, { x: 0.55, y: 1.8, w: 12.2, h: 1.1, rectRadius: 0.1, fill: { color: CARD2 }, line: { color: GREEN, width: 1 } });
s.addText("“拔掉网线，任务继续。”", {
  x: 0.85, y: 2.0, w: 11.6, h: 0.7,
  fontSize: 24, fontFace: FONT, bold: true, color: GREEN, align: "center", valign: "middle", margin: 0
});

addCard(s, 0.55, 3.2, 3.9, 2.4, "全部本地处理", "人脸识别、二维码解析、语音播报与任务状态机均在板载计算单元运行。", GREEN);
addCard(s, 4.7, 3.2, 3.9, 2.4, "不怕现场断网", "演示时关闭网络后，识别、决策、控制与交互继续按原流程运行。", CYAN);
addCard(s, 8.85, 3.2, 3.9, 2.4, "隐私与数据安全", "任务数据不出设备，适合课堂、竞赛与实验室等敏感场景。", VIOLET);

// =============================
// S10 优势二：低成本一体化
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "ADVANTAGE 02", "核心优势二：低成本一体化方案");
addFooter(s, 10);

const comps = [
  ["全尺寸人形", "体积大、价格高", "不适合本科教学大规模配置", RED],
  ["教育双足", "功能偏向单一场景", "多任务统一编排不足", AMBER],
  ["成品竞赛套件", "上手快、硬件完整", "软件封闭、扩展需自改", VIOLET],
  ["A.T.R.I.", "低成本自组 + 五任务统一 + 全离线", "面向课程/竞赛/二次开发复用", GREEN]
];
comps.forEach((c, i) => {
  const y = 1.7 + i * 1.12;
  const isUs = i === 3;
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.55, y, w: 12.2, h: 0.95, rectRadius: 0.08,
    fill: { color: isUs ? "12283C" : CARD },
    line: { color: isUs ? GREEN : LINE, width: isUs ? 1.5 : 0.75 }
  });
  s.addText(c[0], { x: 0.8, y, w: 2.3, h: 0.95, fontSize: 14, fontFace: FONT, bold: true, color: isUs ? GREEN : TEXT, valign: "middle", margin: 0 });
  s.addText(c[1], { x: 3.2, y, w: 4.5, h: 0.95, fontSize: 12, fontFace: FONT, color: TEXT, valign: "middle", margin: 0 });
  s.addText(c[2], { x: 7.9, y, w: 4.6, h: 0.95, fontSize: 11.5, fontFace: FONT, color: SUB, valign: "middle", margin: 0 });
});
s.addText("样机预算约 ¥3600，边缘计算板与 STM32 可复用实验室现有设备，进一步降低进入门槛。", {
  x: 0.55, y: 6.4, w: 12.2, h: 0.5,
  fontSize: 12, fontFace: FONT, color: CYAN, margin: 0
});

// =============================
// S11 一句话创新
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "INNOVATION", "一句话创新");
addFooter(s, 11);

s.addShape(pres.ShapeType.roundRect, { x: 0.55, y: 1.75, w: 12.2, h: 2.4, rectRadius: 0.15, fill: { color: CARD2 }, line: { color: VIOLET, width: 1.25 } });
s.addText("用统一任务卡描述，让一台小型双足机器人在有限算力与断网条件下，自主完成多任务。", {
  x: 0.85, y: 2.0, w: 11.6, h: 1.9,
  fontSize: 24, fontFace: FONT, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0
});

const pillars = [
  ["JSON 任务卡", "任务与参数配置化，可动态修改", CYAN],
  ["FSM 状态机", "多任务统一调度，流程可追踪", GREEN],
  ["感知-运动闭环", "视觉反馈驱动对齐与执行", AMBER]
];
pillars.forEach((p, i) => {
  addCard(s, 0.55 + i * 4.15, 4.45, 3.9, 1.9, p[0], p[1], p[2], { titleSize: 15, bodySize: 11.5 });
});

// =============================
// S12 项目规划
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "ROADMAP", "项目规划");
addFooter(s, 12);

const phases = [
  ["阶段 0", "报名与方案设计", "完成合规构型与五项任务路线；提交企划书与 PPT 材料", CYAN],
  ["阶段 1", "仿真 + 借机验证", "Webots/PyBullet 仿真，借用平台跑通五项任务最小闭环", GREEN],
  ["阶段 2", "自组样机", "晋级后按 BOM 组装 22 自由度样机，逐项联调与留痕", AMBER],
  ["阶段 3", "省赛冲刺", "按评分细则补强演示，完善训练数据、视频与研发日志", RED]
];
phases.forEach((ph, i) => {
  const y = 1.7 + i * 1.18;
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.55, y, w: 12.2, h: 1.0, rectRadius: 0.08,
    fill: { color: CARD }, line: { color: ph[3], width: 1 }
  });
  s.addText(ph[0] + "  " + ph[1], { x: 0.8, y, w: 3.4, h: 1.0, fontSize: 15, fontFace: FONT, bold: true, color: ph[3], valign: "middle", margin: 0 });
  s.addText(ph[2], { x: 4.3, y, w: 8.1, h: 1.0, fontSize: 12.5, fontFace: FONT, color: TEXT, valign: "middle", margin: 0 });
});
s.addText("预算采用阶梯解锁：报名 0–100 元 → 校赛 0–500 元 → 样机 1500–3500 元 → 冲刺按经费/赞助追加", {
  x: 0.55, y: 6.55, w: 12.2, h: 0.45,
  fontSize: 12, fontFace: FONT, color: SUB, margin: 0
});

// =============================
// S13 下一步行动
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "NEXT STEPS", "下一步行动计划");
addFooter(s, 13);

addCard(s, 0.55, 1.8, 3.9, 3.4, "① 仿真先行", "Webots / PyBullet 搭建双足与视觉任务环境，先验证步态、感知和任务流程。", CYAN, { titleSize: 17 });
addCard(s, 4.7, 1.8, 3.9, 3.4, "② 借机联调", "优先借用实验室/指导老师的双足机器人，跑通五项任务最小闭环并录制证据。", GREEN, { titleSize: 17 });
addCard(s, 8.85, 1.8, 3.9, 3.4, "③ 自组样机", "晋级后按 22 自由度构型与 BOM 自组样机，逐项完成步态、感知与任务联调。", AMBER, { titleSize: 17 });

s.addShape(pres.ShapeType.roundRect, {
  x: 0.55, y: 5.55, w: 12.2, h: 1.0, rectRadius: 0.1,
  fill: { color: CARD2 }, line: { color: CYAN, width: 1 }
});
s.addText("三步共用同一套任务卡与接口，保证“仿真 → 借机 → 样机”进展可平滑迁移、可留痕。", {
  x: 0.85, y: 5.65, w: 11.6, h: 0.8,
  fontSize: 14, fontFace: FONT, bold: true, color: TEXT, align: "center", valign: "middle", margin: 0
});

// =============================
// S14 团队与技术储备
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "TEAM", "团队与技术储备");
addFooter(s, 14);

s.addShape(pres.ShapeType.roundRect, { x: 0.55, y: 1.7, w: 12.2, h: 0.85, rectRadius: 0.08, fill: { color: CARD2 }, line: { color: VIOLET, width: 1 } });
s.addText("学科交叉：计算机 / 电子 / 自动化 —— 覆盖感知、控制、硬件与系统集成", {
  x: 0.85, y: 1.8, w: 11.6, h: 0.65,
  fontSize: 15, fontFace: FONT, bold: true, color: VIOLET, align: "center", valign: "middle", margin: 0
});

const team = [
  ["何浩睿", "项目负责人", "机械结构 · 双足步态 · 舵机配置", CYAN],
  ["周柏宇", "项目统筹", "系统集成 · 报名答辩", GREEN],
  ["胡晟瑞", "视觉感知", "人脸识别 · 二维码 · 物体检测", AMBER],
  ["王旭琪", "交互与仿真", "状态机 · 离线语音 · 仿真环境", RED],
  ["张景昆", "自动化专业·新增", "运动控制 · 硬件支持", VIOLET]
];
team.forEach((m, i) => {
  const y = 2.75 + i * 0.62;
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.55, y, w: 12.2, h: 0.5, rectRadius: 0.06,
    fill: { color: i % 2 ? CARD : CARD2 }, line: { color: LINE, width: 0.5 }
  });
  s.addText(m[0], { x: 0.75, y, w: 2.0, h: 0.5, fontSize: 12.5, fontFace: FONT, bold: true, color: m[3], valign: "middle", margin: 0 });
  s.addText(m[1], { x: 2.8, y, w: 3.0, h: 0.5, fontSize: 11.5, fontFace: FONT, color: TEXT, valign: "middle", margin: 0 });
  s.addText(m[2], { x: 5.9, y, w: 6.5, h: 0.5, fontSize: 11, fontFace: FONT, color: SUB, valign: "middle", margin: 0 });
});
s.addText("指导老师：陈妍 · 李璐（技术方向把关 / 设备协调）", {
  x: 0.55, y: 6.15, w: 12.2, h: 0.5,
  fontSize: 13, fontFace: FONT, bold: true, color: TEXT, margin: 0
});

// =============================
// S15 风险与应对
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "RISK", "风险与应对");
addFooter(s, 15);

addCard(s, 0.55, 1.75, 3.9, 3.0, "样机尚未到位", "仿真先行 + 借用平台联调；不阻塞算法验证与任务闭环。", AMBER, { titleSize: 16 });
addCard(s, 4.7, 1.75, 3.9, 3.0, "双足步态稳定性", "ZMP 步态 + 姿态闭环 + 躯干 2 自由度余量；分模块逐步调参。", CYAN, { titleSize: 16 });
addCard(s, 8.85, 1.75, 3.9, 3.0, "经费与周期有限", "阶梯解锁预算：0 → 1500 → 3500 → 6000 档；复用实验室设备降本。", GREEN, { titleSize: 16 });

s.addShape(pres.ShapeType.roundRect, {
  x: 0.55, y: 5.1, w: 12.2, h: 1.2, rectRadius: 0.1,
  fill: { color: CARD2 }, line: { color: LINE, width: 0.75 }
});
s.addText("原则：不把“规划”说成“已完成”，所有阶段用同一套接口与研发日志留痕，确保材料可追溯。", {
  x: 0.85, y: 5.25, w: 11.6, h: 0.9,
  fontSize: 13, fontFace: FONT, color: TEXT, align: "center", valign: "middle", margin: 0
});

// =============================
// S16 愿景
// =============================
s = pres.addSlide();
setSlide(pres, s);
addHeader(s, "VISION", "项目愿景");
addFooter(s, 16);

s.addShape(pres.ShapeType.roundRect, { x: 0.55, y: 1.8, w: 12.2, h: 1.6, rectRadius: 0.15, fill: { color: CARD2 }, line: { color: CYAN, width: 1.25 } });
s.addText("让低成本桌面双足机器人，成为具身智能教育的公共基础设施。", {
  x: 0.85, y: 2.0, w: 11.6, h: 1.2,
  fontSize: 24, fontFace: FONT, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0
});

const values = [
  ["可复现", "同一套任务卡/接口，课程与竞赛可复用", CYAN],
  ["可扩展", "新增任务无需重写整机，配置化扩展", GREEN],
  ["可负担", "低成本自组 + 实验室设备复用", AMBER]
];
values.forEach((v, i) => {
  addCard(s, 0.55 + i * 4.15, 3.8, 3.9, 2.0, v[0], v[1], v[2], { titleSize: 16, bodySize: 11.5 });
});

s.addText("研发链路：仿真 → 借用平台 → 自组样机 → 课程/竞赛落地", {
  x: 0.55, y: 6.25, w: 12.2, h: 0.5,
  fontSize: 13, fontFace: FONT, bold: true, color: CYAN, align: "center", margin: 0
});

// =============================
// S17 结尾
// =============================
s = pres.addSlide();
setSlide(pres, s);
s.addShape(pres.ShapeType.ellipse, { x: 10.7, y: -1.3, w: 4.6, h: 4.6, fill: { color: VIOLET, transparency: 91 }, line: { type: "none" } });
s.addShape(pres.ShapeType.ellipse, { x: -1.5, y: 4.7, w: 4.0, h: 4.0, fill: { color: CYAN, transparency: 92 }, line: { type: "none" } });

s.addText("A.T.R.I.", {
  x: 0.6, y: 1.9, w: 12.1, h: 1.1,
  fontSize: 60, fontFace: FONT_EN, bold: true, color: WHITE, align: "center", margin: 0
});
s.addText("一台机器人，一个统一任务链，让具身智能实验走进课堂与赛场。", {
  x: 0.6, y: 3.2, w: 12.1, h: 0.7,
  fontSize: 20, fontFace: FONT, bold: true, color: CYAN, align: "center", margin: 0
});
s.addText("恳请各位专家给予支持与指导", {
  x: 0.6, y: 4.1, w: 12.1, h: 0.6,
  fontSize: 16, fontFace: FONT, color: TEXT, align: "center", margin: 0
});
s.addText("A.T.R.I. 项目组 · 西安交通大学\n项目负责人：何浩睿  |  指导老师：陈妍 · 李璐", {
  x: 0.6, y: 5.4, w: 12.1, h: 0.9,
  fontSize: 13, fontFace: FONT, color: SUB, align: "center", margin: 0, lineSpacing: 16
});

// ---------- 输出 ----------
const outPath = "/Users/hpi/Documents/deepseek harness/搞机器人/A.T.R.I.-宣传PPT-评审遴选版.pptx";
pres.writeFile({ fileName: outPath }).then((fn) => {
  console.log("WROTE:", fn);
}).catch((err) => {
  console.error("ERR:", err);
  process.exit(1);
});