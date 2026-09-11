# 厂商 / 第三方参考件（vendor）

> 这里放**外部世界的一手几何与文档**，是 `standards.py` 中接口数据的证据基础。
> 配套工具：`design/cad/measure_vendor.py`、`probe_assembly.py`、`check_mate.py`、
> `render_vendor.py`、`read_vendor_pdf.py`（都走 `.venv-cad`）。

---

## 1. `feetech/` —— 飞特**官方**文档（最高证据级别）

| 文件 | 内容 | 来源 |
|---|---|---|
| `STS3215_7.4V_19kg_spec.pdf` | 飞特《产品规格书》STS3215 A/0，8 页，2020-04-10；**第 6 页＝外形尺寸图**（8-PA2.0 自攻、25T 输出齿、M3X6 机牙螺丝、Φ6 副轴、4.1 副轴伸出、45.23/24.73/35/36.5/3.4/29/32、5264/2.54 3P 端子） | `feetechrc.com` 产品页附件 |
| `STS3235_12V_30kg_spec.pdf` | 飞特《产品规格书》STS3235 A/0，8 页，2021-11-19；**同尺寸（45.22×24.72×35）铝壳钢齿版**：70.5±1 g、额定负载 10 kg·cm、堵转 30 kg·cm、工作电压 6–12V | `feetechrc.com` 产品页附件 |

抓取方式（**注意 `--max-time` 必须给足：首字节约 8 秒**）：

```bash
curl -sL --max-time 120 -o design/cad/vendor/feetech/STS3215_7.4V_19kg_spec.pdf \
  "https://www.feetechrc.com/Data/feetechrc/upload/file/20260622/6391772523943436695270694.pdf"
```

> ⚠️ `feetech.cn` 不通，但 **`feetechrc.com` 通**（只是慢）。
> 上一轮"官网不可达"的结论已更正，详见
> `design/handoff/STS3215-官方规格书核验.md` 第 1 节。

---

## 2. `so-arm100/` —— 开源整机参考（Apache-2.0）

来源：<https://github.com/TheRobotStudio/SO-ARM100>（★7426，LeRobot 生态标准机械臂，整机就用 STS3215）

| 文件 | 用途 |
|---|---|
| `STS3215_03a.step` | 舵机 B-rep 实体（**含从动舵盘**）；接口几何实测的唯一来源 |
| `sts3215_03a_v1.stl` / `sts3215_03a_no_horn_v1.stl` | 同一舵机的网格版（含/不含从动舵盘）；用于**顶点分布比对**判定哪块几何属于舵盘 |
| `Passive_Horn_01.step` | 从动舵盘：Φ20 盘 ×2.0 + Φ9 凸台 ×1.1 + **Φ7 中心通孔**（无 4 孔阵列） |
| `Motor1_holder.step` / `Motor_holder_SO101_Base.step` / `Motor_holder_SO101_Wrist.step` | 与舵机配合的打印支架；用于**孔位语义反查** |
| `SO100_Follower_Assembly.step` | SO-100 从动臂整机（7 MB，19 实体）；`check_mate.py` 的输入 |

**已从中实测出的事实**（复现见 `measure_vendor.py` / `check_mate.py`）：

| 项 | 实测 |
|---|---|
| 包络 | 45.40 × 24.80 × **39.60**（−19.40 ~ +20.20），**无安装耳** |
| 输出轴心 | (12.50, 0)：距 +X 端面 10.21、距 −X 端面 35.21、宽度居中 ±12.41 |
| 端面 4 孔阵列 | 两端面各 4×Φ2.50，方形 9.90×9.90（对角 = **Φ14.00**），深 2.5 / 2.1 |
| 输出端圆盘 / 副轴端圆盘 | Φ20.0，厚 2.5 / 2.1（**35 + 2.5 + 2.1 = 39.6** ✅ 与包络自洽） |
| 副轴 | Φ6.00 圆柱、无 D 切边；模型只建了 0.60 伸出（**官方图纸为 4.1，模型是仿真简化**） |
| 副轴中心孔 | Φ2.50，深 3.90（M2.5） |
| 壳体自攻孔 | 6 处 Φ1.5 轴向通孔（X=+4.20/−16.50/−20.30，Y=±10.25），壁厚 1.5 |
| 配合反查 | SO-ARM100 打印件孔与舵机 **Φ14 节圆 4 孔同轴命中 16 次**（横偏 0.00）→ 该阵列是对外安装接口 |

---

## 3. 复现命令

```bash
cd /Users/zhangjingkun/Projects/github/ATRI

# 接口几何（包络 / 圆柱面按轴分组 / 孔与轴判别）
.venv-cad/bin/python design/cad/measure_vendor.py design/cad/vendor/so-arm100/STS3215_03a.step

# 整机里"谁是谁"（按体积分组，找舵机实例与螺钉）
.venv-cad/bin/python design/cad/probe_assembly.py \
  design/cad/vendor/so-arm100/SO100_Follower_Assembly.step --min-volume 20

# 孔位语义反查（同轴孔对）
.venv-cad/bin/python design/cad/check_mate.py \
  design/cad/vendor/so-arm100/SO100_Follower_Assembly.step --target-volume 36217 --tol 0.4 --detail

# 目视核验（多视角 PNG，输出到 design/cad/out/vendor_render/，out/ 已 gitignore）
.venv-cad/bin/python design/cad/render_vendor.py design/cad/vendor/so-arm100/STS3215_03a.step

# 官方 PDF 逐页转图 + 抽文字
.venv-cad/bin/python design/cad/read_vendor_pdf.py \
  design/cad/vendor/feetech/STS3215_7.4V_19kg_spec.pdf --scale 2.2
```

---

## 4. 入库与依赖约定

- 这些文件**入 git**（单文件最大 7 MB < 50 MB 上限），因为验收标准要求
  "核验过程可复现（保留脚本与原始 STEP/STL）"。
- `.stl` 是二进制网格，只在做"含/不含舵盘"顶点比对时用；如体积敏感可只留 STEP。
- `design/cad/out/`（渲染图、PDF 页面 PNG）**不入 git**，均可由上述命令重新生成。
- 读 PDF 需要 `pypdf` + `pypdfium2`，已装入 `.venv-cad`：
  `.venv-cad/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ pypdf pypdfium2`
  （主仓库仍保持零第三方依赖）
