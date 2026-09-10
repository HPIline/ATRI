"""二维码 JSON 指令生成器。

生成“内嵌 JSON 指令”的二维码图片，供 Webots 仿真、Windows 视觉联调和后续测试使用。
默认依赖 qrcode 库（可选）：
    pip install "qrcode[pil]"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_ACTIONS = {"walk", "turn", "kick", "carry", "dance", "grasp", "release"}


class QRGeneratorError(RuntimeError):
    pass


def build_qr_payload(action: str, **params: Any) -> str:
    """构造二维码内嵌 JSON 指令字符串。"""
    payload = {"action": action, **params}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class QRCodeGenerator:
    def __init__(self, qrcode_module: Any = None) -> None:
        """qrcode_module 仅供测试注入 fake；正常使用传 None 自动 import qrcode。"""
        self._qrcode = qrcode_module

    def _get_qrcode(self) -> Any:
        if self._qrcode is None:
            try:
                import qrcode  # type: ignore
            except ImportError as exc:
                raise QRGeneratorError(
                    "未安装 qrcode：请执行 pip install 'qrcode[pil]' 后重试"
                ) from exc
            self._qrcode = qrcode
        return self._qrcode

    def generate(
        self,
        action: str,
        output_path: str | Path,
        **params: Any,
    ) -> str:
        """生成二维码图片并保存到 output_path，返回保存路径。"""
        payload = build_qr_payload(action, **params)
        qr = self._get_qrcode()
        img = qr.make(payload)
        img.save(str(output_path))
        return str(output_path)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成内嵌 JSON 指令的二维码")
    parser.add_argument("--action", required=True, help="指令动作，如 walk/turn/kick")
    parser.add_argument("--output", "-o", required=True, help="输出图片路径，如 qr_walk.png")
    parser.add_argument("--json", dest="raw_json", help="直接传入完整 JSON 指令字符串（与 --action 二选一）")
    parser.add_argument("--param", "-p", action="append", default=[], help="附加参数 key=value，可多次")
    parser.add_argument("--steps", type=int, help="快捷参数：行走步数")
    parser.add_argument("--deg", type=int, help="快捷参数：转向角度")
    parser.add_argument("--bars", type=int, help="快捷参数：舞蹈小节数")
    args = parser.parse_args(argv)

    if args.raw_json:
        try:
            data = json.loads(args.raw_json)
            action = str(data.get("action", ""))
            params = {k: v for k, v in data.items() if k != "action"}
        except json.JSONDecodeError as exc:
            print(f"错误：JSON 解析失败 {exc}", file=sys.stderr)
            return 2
    else:
        action = args.action
        params: Dict[str, Any] = {}
        for item in args.param:
            if "=" not in item:
                print(f"错误：--param 需要 key=value 格式：{item}", file=sys.stderr)
                return 2
            key, value = item.split("=", 1)
            params[key] = value

    if not action:
        print("错误：action 不能为空", file=sys.stderr)
        return 2

    for key, value in (("steps", args.steps), ("deg", args.deg), ("bars", args.bars)):
        if value is not None:
            params[key] = value

    gen = QRCodeGenerator()
    try:
        path = gen.generate(action, args.output, **params)
    except QRGeneratorError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    print(f"二维码已生成: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
