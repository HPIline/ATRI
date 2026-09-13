# docs

归档与赛题材料，不参与 CI。日常开发走仓库根的 `software/atri`、`webots`、`design`、`ppt`。

```
docs/
├── research/项目文档/   综述、技术方案、BOM、17DOF 核查、答辩 PPT 文案 v4、口径对照
├── process/            开发机说明（Linux / ARM 优先）、研发日志、骨架重构评估组会汇报
│   └── sim/            仿真迭代日志（第 1–3 轮，2026-09-12：碰撞回路 / 探针证伪 / 落位修正）
└── contest/            必须提交的参赛附件
```

A 路线铝夹层图纸/BOM/验证：`design/v2/`（出图 `PYTHONPATH=design python3 -m v2.generate`）。

`design/v2/` 是当前 main 的 A 路线机构（20 DOF、无 hip_yaw）；`software/atri/` 与默认 `webots/worlds/atri_v2.wbt` 已按 20 DOF 适配。旧 `design/cad/`、`design/atri.urdf`、`webots/worlds/atri_22dof.wbt` 仍是冻结的现机 22 DOF 线。`docs/process/` 为历史日志，不回改。
