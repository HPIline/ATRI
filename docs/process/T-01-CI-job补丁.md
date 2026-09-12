# T-01 CI job（待有 `workflow` 权限时应用）

> 生成：2026-09-12　维护：T-01 人脸识别做实那一支
> 状态：**尚未应用**。原因见下。

## 为什么没直接提交

推送时 GitHub 拒绝：

```
! [remote rejected] main -> main (refusing to allow an OAuth App to create or
  update workflow `.github/workflows/ci.yml` without `workflow` scope)
```

当前推送用的凭据**没有 `workflow` 权限**，无法创建或修改 `.github/workflows/` 下的任何文件。
这不是网络问题，重试无效。

仓库历史上出现过同一条限制：卷 1 记的「CI 工作流加了两遍——第一次 token 缺 workflow 权限，
移除后重新加回」。本次沿用同一处置：**先把 CI 改动摘出仓库，其余照常提交。**

## 怎么应用（任选其一）

**A. 给凭据补 `workflow` 权限**（推荐）
把用于推送的 token / OAuth App 权限加上 `workflow` scope，然后：
```bash
# 把下面的 YAML 块贴回 .github/workflows/ci.yml 的 webots-controller 之前
git add .github/workflows/ci.yml && git commit -m "ci(face): T-01 人脸模块 job" && git push
```

**B. 在 GitHub 网页上手动加**
打开 `.github/workflows/ci.yml` → Edit → 把下面的块插到 `webots-controller:` 之前 → Commit。

## 待插入的 YAML（插在 `webots-controller:` 之前）

```yaml
  # 人脸识别（T-01）：单独一个 job。
  #
  # 为什么单独：要装 opencv-contrib（约 55 MB）与 37 MB 模型，主 test job 保持
  # "不装任何第三方依赖"才有意义，混在一起就测不准了。
  #
  # 分三层验证，逐层加依赖：
  #   ① 只装 numpy：几何对齐 / 人脸库 / 技能行为（不碰 cv2、不碰模型）
  #   ② 装 opencv-contrib：全部人脸单测（含检测/识别管线逻辑）
  #   ③ 拉真模型（带 sha256 校验）后跑真模型烟雾测试 —— 证明模型真能加载并出 128 维特征
  #
  # Python 版本：与主 job 一致，统一 3.14（2026-09-13 实测通过）。
  # numpy **不 pin <2**：numpy 1.x 没有 3.14 的 wheel。实测 3.14.7 + numpy 2.5.3 +
  # opencv-contrib-python 4.11.0.86 可用，人脸/二维码全部测试与评测数字均逐项一致。
  face-module:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.14"]

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install numpy only
        run: python -m pip install --upgrade pip && pip install numpy

      - name: Face logic tests (no OpenCV, no models)
        working-directory: software/atri
        run: python -m unittest discover -s tests -p "test_face_db.py" -v

      - name: Install pinned OpenCV contrib
        run: pip install "opencv-contrib-python==4.11.0.86"

      - name: All face unit tests
        working-directory: software/atri
        run: python -m unittest discover -s tests -p "test_face*.py" -v

      - name: Fetch models with sha256 verification
        run: python software/atri/tools/fetch_models.py

      - name: Real-model smoke test
        working-directory: software/atri
        run: python -m unittest tests.test_face_models -v

```

## 插完之后的 CI 会做什么

| 步骤 | 验证什么 |
|---|---|
| 只装 numpy → 跑 `test_face_db.py` | 几何对齐 / 人脸库读写与拒识 / schema 校验（不碰 cv2、不碰模型） |
| 装 `opencv-contrib-python==4.11.0.86` → 跑 `test_face*.py` | 全部 51 项人脸单测，含检测/识别管线逻辑 |
| `python software/atri/tools/fetch_models.py` | **带 sha256 校验**地拉取两个官方 ONNX 模型 |
| 跑 `tests.test_face_models` | 真模型能加载、能出 128 维归一化特征——证明不是只有假对象在自娱自乐 |

**为什么单独一个 job**：要装 opencv-contrib（约 55 MB）与 37 MB 模型。
主 `test` job 保持"不装任何第三方依赖"才有意义，混在一起就测不准了。

**✅ Python 版本口径（2026-09-13 已统一）**：本 job 与主 job 一样用 `3.14`。

原先担心 3.14 上装不了 numpy（`numpy<2` 没有 3.14 的 wheel），故本 job 曾用 3.9/3.11。
本机装上 **Python 3.14.7** 后实测：**不要 pin `numpy<2`**，直接装 `numpy`（实测 2.5.3）
配合 `opencv-contrib-python==4.11.0.86` 即可 —— 人脸 + 二维码全部测试通过
（**579 项、0 跳过**），两份评测数字与 3.9.6 下逐项一致。

解释器来源与校验和：`.python/VERSION.txt`（python-build-standalone 预编译包，装在仓库内、
不动系统，因此不需要管理员权限也不影响其它工程）。

## 附：不加这个 job 会怎样

人脸相关测试在零依赖环境里会**自动 skip（38 项）**，主 job 仍然全绿 —— 也就是说，
**不应用这个 job，CI 不会变红，但那 51 项人脸测试实际上没有被任何 CI 覆盖。**
这是一个"静默不覆盖"的风险，建议尽快应用。
