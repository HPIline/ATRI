# 现机 22 DOF 备份（不是当前方案）

本目录是 ATRI **旧 22 DOF 打印件方案**的整包备份：CAD、URDF、L1 模型、旧 Webots 世界、旧方案文档。

**当前入口是仓库根的 20 DOF A 路线**（`design/v2/`、`software/atri/`、`webots/worlds/atri_v2.wbt`）。不要把这里的 22 轴、`hip_yaw`、407×268×160 mm、81 件 PETG 数字写进 README / 计划书 / 答辩。

| 备份 | 路径 |
|---|---|
| 旧 CadQuery 骨架 | `design/cad/` |
| 旧 URDF / L1 模型 | `design/atri.urdf`、`design/robot_model.json` |
| 旧 Webots 世界 | `webots/worlds/atri_22dof.wbt` |
| 从根 README 剪下的旧方案正文 | `README-appendix.md` |
| 旧调研/对比文 | `docs/research/` |

脚本若还要跑，工作树根仍是仓库根；生成器已把 `REPO` 指回仓库根。产物写在本备份树内。
