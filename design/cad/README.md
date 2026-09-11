# CAD 层

用 OpenCASCADE（CadQuery）出可制造的 B-rep / STEP / STL。运动学与质量的提交口径仍在 `design/robot_model.json`，两套数字不要混引，见仓库根 README。

```
design/
├── robot_model.json      运动学 / 包络 / 提交口径质量（1790 / 3437 g）
├── components.json       外部元件参数；电子件必须带稳定 kind
├── placements.json       22 舵机 + 10 电子件落座（gen_placements.py 生成）
└── cad/
    ├── standards.py      舵机 / 轴承 / 紧固件 / FDM 容差
    ├── kit.py            接口标准 + servo_frame()（舵机姿态唯一真值）
    ├── skeleton.py       现行零件（笼 / 叉 / 管 / 框架 / 簇臂…）
    ├── assembly.py       整机装配；按 kind 落座电子件，失败即报错
    ├── fitcheck.py       干涉判定原语（装配 / 体检 / 钟点共用）
    ├── fit_stagger.py    髋/肩机体沿轴抽出量（权威表，禁止手写）
    ├── audit_assembly.py 穿模 / 连通性 / 关节轴对齐
    ├── interference.py   全机干涉普查（与 fitcheck 分工：普查 vs 原语）
    ├── build.sh          一键：零件 → 装配 → 体检
    ├── build_all.py      只出零件 STEP/STL
    ├── parts.py          只提供 sanitize()，不是构建入口
    └── out/              STEP/STL/报告（gitignore，可复现）
```

## 环境

CadQuery 装在独立 `.venv-cad/`，别污染主包的零依赖约束。

已验证的组合是 Python 3.9.6 / `cadquery==2.5.2` / `cadquery-ocp 7.7.2`，这套不随主包迁 3.14。主包 CI 只跑 3.14；CAD 要迁 3.14，得升到 `cadquery ≥ 2.8`（`cadquery-ocp` 要求 `>=3.11,<3.15`）。

```bash
cd <repo>
if .venv-cad/bin/python -c "import cadquery, OCP" 2>/dev/null; then
  echo "已就绪"
else
  python3 -m venv .venv-cad
  .venv-cad/bin/pip install -r design/cad/requirements.txt
fi
```

环境必须建在仓库内。`.venv-cad/` 已 gitignore，判断它在不在要看文件系统，不能只看 `git status`。

## 入口

```bash
# 推荐：零件 → 装配 → 体检（改参数反复跑加 --fast）
bash design/cad/build.sh --fast

# 髋/肩错轴量（关节原点不动，只平移机体）
.venv-cad/bin/python design/cad/fit_stagger.py

# 全机干涉普查
.venv-cad/bin/python design/cad/interference.py --all

# 标准件参数状态
.venv-cad/bin/python design/cad/build.py --standards
```

`build.py --all` 和 `parts.py` 里的 `servo_yoke` 三件套是早期入口，现行零件在 `skeleton.py`；`sanitize()` 仍从 `parts.py` 引用，文件不能删。

配合的校验脚本在仓库根的 `design/check_fit.py`，不在 `cad/` 下。

## 髋 / 肩错轴

轴距 19.6 mm 只够「输出轴 + 薄支架」，不够两只沿轴 35 mm 的无耳机体共面。

关节轴位置不动，机体沿自身输出轴抽出：hip_roll / shoulder_pitch +35 mm，hip_pitch +30 mm（`fit_stagger.py` 写入 `JOINT_SCHEME.stagger`）。新件是 `cluster_horn_arm`（锁上一级舵盘）加 `cluster_outrigger`（副轴第二支点）；承力臂目标 6061-T6，PETG 几何仅占位。

Gemini 给的 8–12 mm 是端面净距（盘厚 + 螺钉头 + 臂厚），不是机体 stagger。只错 8–12 mm 清不掉互咬，所以禁止用 8–12 回改 stagger。

## 质量

这里不再抄总表，只说两层口径各自指向哪。

- 提交口径（URDF / `robot_model.json` / 交接包 / 测试钉死）：结构 1790 g、整机 3437 g。踝 1.630 N·m ≈ 连续额定 0.98 的 167%。
- CAD 现行几何（未回灌）：装配修正后结构 1404 g、整机 3050 g；错轴新件后再 +86 g → 结构约 1490 g。过程见 `design/handoff/装配一致性修正记录.md`。

扭矩主判据是连续额定 0.98 N·m。用堵转 × 50% = 1.47 算出的「踝 102%」是峰值口径。

减重路径 A/B/C 见 `robot_model.json` 的 `reduction_paths`（按 0.98 主判据，三条均未达标）。

## 约定

1. 单位 mm；参数来自 `standards.py`，`unknown` 状态拦截构建。
2. 电子件用 `kind`（compute / battery / mcu / …）匹配，`id`/`name` 只给人看。
3. `cluster_fit` 阈值全部 `provisional`，不得覆盖已标定的通孔 2.7 / 过盈 −0.03 / 同轴 0.05 / 过孔 8.0。
