# 动作库 JSON 格式（Action Library）

用于把 Webots 标定得到的关键帧动作导出为统一 JSON，并由 `Cerebellum.play_action()` 导入回放。
Windows 仿真标定后只需按本规范导出，Mac/Windows 都能直接加载。

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| schema_version | string | 是 | 当前固定 `"1.0"` |
| action_id | string | 是 | 动作唯一 ID，如 `walk`、`kick` |
| name | string | 否 | 显示名 |
| description | string | 否 | 动作说明 |
| loop | bool | 否 | 是否循环播放，默认 false |
| frames | array | 是 | 关键帧数组，至少 1 帧 |
| meta | object | 否 | 来源/作者/时间等元信息 |

## 关键帧（frames[]）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| index | int | 否 | 帧序号，建议从 0 开始 |
| duration_s | number | 是 | 本帧持续时间，单位秒，必须 >0 |
| joints | object | 是 | 关节名 -> 角度（度），键必须来自 `atri/config.py` 的 22 DOF 关节名 |
| comment | string | 否 | 调试备注 |

## 示例

```json
{
  "schema_version": "1.0",
  "action_id": "kick",
  "name": "右脚踢球",
  "frames": [
    {
      "index": 0,
      "duration_s": 0.12,
      "joints": {"right_hip_pitch": 18.0, "right_knee_pitch": -8.0, "right_ankle_pitch": 5.0}
    },
    {
      "index": 1,
      "duration_s": 0.12,
      "joints": {"right_hip_pitch": 26.0, "right_knee_pitch": -18.0, "right_ankle_pitch": 10.0}
    }
  ],
  "meta": {"source": "webots-calibration"}
}
```

## 校验与执行

```bash
cd 软件/atri
python -m unittest tests.test_action_library -v
```

```python
from atri.action_library import load_action, validate_action
from atri.cerebellum import Cerebellum

action = load_action("action_library/examples/kick.json", strict=True)
cere = Cerebellum()
cere.play_action(action)
```
