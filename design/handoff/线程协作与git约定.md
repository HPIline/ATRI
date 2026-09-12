# 线程协作与 git 约定（多模型并行）

> 2026-09-11 立。适用：DSV4.1F（主控/集成）· Grok 4.6 · Gemini（网页版）· 以及后续任何并行会话。
> 起因：多会话同时改一个仓库，最大的风险不是"写得不对"，而是**互相覆盖**与**版本发散**
> （本项目已实际发生过两次：并发提交把我新建的脚本一起提交、standards.py 被覆盖）。

---

## 1. 三条硬规则

1. **单一提交者**：一轮之内只有**主控会话（DSV4.1F）**执行 `git commit` / `git push`。
   子代理只做两件事：改自己领地的文件、写自己的报告。**不 commit、不 push、不 rebase。**
   理由：`git add -A` 会扫走别人的改动；并发 `commit` 会撞 `index.lock`。
2. **文件领地（disjoint）**：每个线程一份"只写"清单，见第 4 节。
   发现别人动了自己的领地 → **停手并报告**，由主控裁决，禁止自行 force push 或覆盖。
3. **成果三处留痕**（这就是"用 git 跨线程沟通"的落地方式）：
   - ① **报告文件** `design/handoff/线程报告-<线程名>.md`：人可读，**必须含命令与输出**；
   - ② **提交信息前缀** `[线程名] ...`：可检索 —— `git log --oneline --grep='\[真机总线\]'`；
   - ③ **可复现产物**（体检报告、审计输出等）一并入库，供其他线程 `git show` 读取。

## 2. 轮次节奏（本地 commit，统一 push）

```
① 开工前：主控打**基线快照** commit（本轮第一条）→ 给所有线程一个干净的 diff 基线
② 轮内：各线程并行干活；子代理**只改文件 + 写报告**
③ 线程收工：主控逐线程验收（跑测试/体检）→ **分线程提交**（`[线程] …`）
④ 全轮验收通过：`git push` **一次**（不中途推、不零碎推）
⑤ 若发现冲突：以主控版本为基线，让冲突方**重放 patch**；禁止历史改写
```

**为什么统一 push**：远端历史干净、评审一次看完、避免"每个子任务一次 push"造成的版本噪声与 CI 反复触发。
本地 commit 次数不受限（本来就该细），**只有 push 需要合并成一次**。

## 3. 怎么读别人的成果（跨线程沟通的实际操作）

```bash
git log --oneline --grep='\[真机总线\]'          # 按线程名找提交
git show <sha> --stat                            # 看这次改了哪些文件
git diff <base_sha>..HEAD -- software/atri/          # 只看某条线的净变化
cat design/handoff/线程报告-<线程名>.md          # 人可读报告（命令 + 输出）
```

**约定**：报告里"结论"必须能追到"命令 + 输出"；只写"已完成"不算交付。

## 4. 本轮文件领地（只写清单）

> ⛔ **2026-09-12 作废**：下表点名的 `opencode-go/kimi-k2.7-code` 等路由**本机不存在**
> （实际注册的是 `kimi-k3`），且用户已决定**只用 `opencode-go-v41/deepseek-v4.1-flash`
> 与 `xbcl/grok-4.6` 两条路由**。现行分工与领地表见 `分工重整-两模型制.md`（第 4 节）。
> 本表仅作历史留档，**不要再照此招募线程**。

| 线程 | 模型（已作废） | 只写 |
|---|---|---|
| 真机总线驱动 | `xbcl/grok-4.6` | `software/atri/atri/bus_sts3215.py`、`software/atri/tests/test_bus_sts3215.py`、`design/handoff/线程报告-真机总线.md` |
| 扫掠自碰撞 | `opencode-go/kimi-k2.7-code` | `design/cad/sweep_check.py`、`design/cad/out/sweep_report.md`、`design/handoff/线程报告-扫掠校核.md` |
| 工具可达性 | `opencode-go/minimax-m3` | `design/cad/tool_access.py`、`design/cad/out/tool_access_report.md`、`design/handoff/线程报告-工具可达.md` |
| 参考件配合反查 | `opencode-go/deepseek-v4-flash` | `design/cad/reference_fits.py`、`design/handoff/线程报告-参考件配合.md` |
| 过期口径清扫 | `opencode-go/glm-5.3-flash` | `design/handoff/线程报告-过期口径清扫.md`（**只报告，不改文件**） |
| 舵机座让位 | `opencode-go/deepseek-v4-pro` | `design/cad/skeleton.py`（仅让位切口）、`design/handoff/线程报告-舵机座让位.md` |
| 主控/集成 | `opencode-go-v41/deepseek-v4.1-flash` | 其余全部；**唯一 commit 者** |

## 5. 通用红线（所有线程）

- **不改**：别人领地的文件、`design/cad/standards.py` 里已验证的官方数值、
  `ppt/**`、`webots/**`、`software/atri/atri/skills/**`、`task_cards/**`。
- **不手改生成物**：`design/placements.json`、`design/cad/out/**`（可重建）。
- 主包 `software/atri/atri/` 核心保持**标准库可跑**；第三方依赖只进 `requirements.txt` 且惰性导入。
- 中文回复；报告给**命令 + 输出**；找不到就写"未找到"，**禁止编造数字**。
- 每项做完先自检（`python3 -m unittest discover -s tests`、`.venv-cad/bin/python -m compileall` 等），
  不合格不许收工。
