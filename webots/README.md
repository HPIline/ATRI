# Webots 仿真（Windows + RTX 4060）

本目录包含 A.T.R.I. 的 Webots 控制器。控制器复用 `软件/atri` 的
`Brain + Cerebellum + TaskCard`，只把 `ServoBus` 替换为 Webots 电机，
并用 `robot.step()` 推进仿真时间。

## 文件

```
webots/
├── README.md
└── controllers/
    └── atri_controller/
        ├── atri_controller.py        # 控制器入口
        ├── joint_mapping.json         # ATRI 关节名 -> Webots 电机名（默认同名）
        └── joint_mapping_nao.json     # 内置 Nao 机器人的参考映射
```

## 在 Windows 上跑起来

1. 安装 Webots（R2023b 或更新）和 Python 3.10/3.11。
2. 克隆仓库并进入：
   ```powershell
   git clone https://github.com/HPIline/ATRI.git
   cd ATRI
   ```
3. 打开 Webots，新建世界，拖入一个机器人：
   - 首选：后续我们会加入自建 ATRI 22 DOF PROTO 模型；
   - 临时验证：可使用内置 **Nao**（`File > Open Sample World` 搜索 Nao），
     然后把 `joint_mapping_nao.json` 的内容覆盖到 `joint_mapping.json`。
4. 在 Webots 场景树里选中机器人，将 `controller` 字段改为 `<extern>`，
   然后按 Webots 提示启动外部控制器（或在 Webots 里直接指向本目录）。
5. 看到控制器打印 `已绑定: ...` 并顺序执行五张任务卡即成功。

## 注意

- Webots 的 Python 解释器版本要与你的命令行 Python 一致（Webots 设置里有
  `Python command` 选项）。
- 控制器通过 `sys.path` 指向 `软件/atri`，不需要 `pip install`。
- 执行任务时控制器会用 `robot.step()` 推进仿真，不要在 `Cerebellum` 里再调用
  `time.sleep`；本仓库的 `Cerebellum` 已支持注入 `sleeper`。
- 若某些电机名不存在，控制器会跳过并在控制台提示，不会崩。
