# 二维码指令示例

这些 PNG 由 `atri/qrgen.py` 生成，内嵌 JSON 指令，可供 Windows 仿真/视觉联调直接打印或显示测试。

| 文件 | 内嵌 JSON |
|---|---|
| `qr_walk_steps3.png` | `{"action":"walk","steps":3}` |
| `qr_turn_deg30.png` | `{"action":"turn","deg":30}` |
| `qr_dance_bars2.png` | `{"action":"dance","bars":2}` |

生成方式：

```bash
cd software/atri
PYTHONPATH=. python3 -m atri.qrgen --action walk --steps 3 --output qr_samples/qr_walk_steps3.png
```