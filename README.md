# A.T.R.I.

22 自由度桌面人形机器人。硬件在 `design/`，控制软件在 `软件/atri/`，仿真在 `webots/`。

核心代码只依赖 Python 3.14+ 标准库，没有硬件也能跑通任务卡 → 技能 → 舵机总线这条闭环。

```bash
cd 软件/atri
python3 run_demo.py --fast          # 5 张任务卡，无硬件
python3 -m unittest discover -s tests
```

主包 334 项测试，Webots 离线 40 项；CI 矩阵只有 `3.14`。

## 目录

- `软件/atri/`：任务卡、FSM、技能、感知与语音接口、动作库。主包零第三方依赖。
- `webots/`：22 DOF 世界、控制器、关节映射。绑定必须覆盖 22 个关节名，且至少有一个关节产生实际行程。
- `design/`：运动学、URDF、交接包、CAD（跑在独立的 `.venv-cad`）。
- `NOTICE`：第三方素材归属。主仓库 LICENSE 仍待选定。

## 软件契约

- 技能必须返回真实成败；感知失败就不下发实体动作，后续技能也不跑。
- `found` 只接受 `bool`。非 bool（包括字符串 `"False"`）一律判非法。
- 超时靠定时器线程置位 `abort_event`，而且只置位，不顺手做事。`home()` 只在主线程、execute 返回后做一次。长轨迹在帧边界协作中止，不能抢占阻塞调用。
- 关节限位统一在 `ServoBus.set_angle` 钳制，NaN / Inf 直接拒绝；子类只实现 `_write_angle`。
- Webots 退出码 0 要同时满足三件事：映射覆盖 22 个合法关节名、非空条目全部绑定、至少一个关节行程 > 1°。

## 两套质量数字

仓库里同时存在两层事实，用途不同，引用的时候别串口径。

| 层 | 数字 | 用在哪 | 状态 |
|---|---|---|---|
| 运动学 / URDF / 交接包 | 结构 1790 g、整机 3437 g、踝 1.630 N·m ≈ 连续额定 0.98 的 167% | `robot_model.json`、URDF、`gen_handoff`、单元测试钉死的快照 | 提交口径。本机无 CadQuery，本次不回灌 |
| CAD 现行几何 | 装配修正后结构 1404 g、整机 3050 g、踝 1.49 N·m（占峰值 1.47 的 102%）；髋/肩错轴新件后再 +86 g → 结构约 1490 g | `design/handoff/装配一致性修正记录.md`、CAD `out/report.md` | 未回灌到 URDF |

扭矩主判据是连续额定 0.98 N·m（12 V 变体推断，待实测）。峰值 1.47 N·m（堵转 × 50%）只作短时参考。CAD 侧写的「踝 102%」用的是峰值口径，不是官方额定。

30 min 任务的电池标称需求 ≥ 4.53 Ah；现选 2000 mAh 大约只够 13 min。

## CAD 现状

CAD 有自己的环境 `.venv-cad/`，CadQuery 2.5.2 钉死 Python 3.9.6，不随主包迁 3.14：

```bash
bash design/cad/build.sh --fast
```

- 电子件按稳定字段 `kind` 落座，不再用显示名匹配。
- 髋/肩轴距 19.6 mm 放不下两只 35 mm 机体，所以机体沿自身输出轴抽出 30–35 mm（`fit_stagger.py`），新件是 `cluster_horn_arm` + `cluster_outrigger`。不要拿「8–12 mm 端面净距」去改 stagger。
- `fitcheck.py` 是干涉判定原语，`interference.py` 是全机普查，两者分工不同。
- `parts.py` 只提供 `sanitize()`，不是构建入口。

## 合规

- `NOTICE` 加 `design/cad/vendor/LICENSE-Apache-2.0.txt`：vendor 下 10 个 SO-ARM100 文件与上游逐字节一致。
- vendor PDF 不可再分发，公开前决定是否移除。
- 主仓库 LICENSE 尚未选定。`NOTICE` 只声明第三方素材。

## 待办

- 用 CadQuery 重测后，把 CAD 现行质量回灌 `robot_model.json` / URDF / 交接包。
- 买一只 12 V STS3215，实测连续额定扭矩（现在的 0.98 是推断值）。
- CAD 干涉数值结论（本机无 CadQuery，未实跑）。
- 真机硬件在环。
- 选定主仓库 LICENSE。
