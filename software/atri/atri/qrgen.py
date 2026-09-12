"""二维码 JSON 指令生成器。

生成“内嵌 JSON 指令”的二维码图片，供 Webots 仿真、Windows 视觉联调和后续测试使用。
默认依赖 qrcode 库（可选）：
    pip install "qrcode[pil]"
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .config import MAX_BARS, MAX_STEPS, MAX_TURN_DEG, VALID_ACTIONS
from .skills.base import as_finite_float, as_int_in_range


class QRGeneratorError(RuntimeError):
    pass


def _reject_constant(value: str) -> Any:
    """json.loads 的 parse_constant 钩子：拒绝 JSON 标准之外的 NaN/Infinity。"""
    raise QRGeneratorError(f"JSON 不允许常量 {value}（NaN/Infinity）")


def validate_params(action: str, params: Dict[str, Any]) -> None:
    """生成前按技能侧同一口径校验参数，非法指令直接报错，不留到运行时。

    复用 `config` 的 MAX_STEPS/MAX_BARS/MAX_TURN_DEG/VALID_ACTIONS，与
    `skills/qr.py` 的执行期校验同源，避免生成端放过跑不通的二维码。
    """
    if not isinstance(action, str) or action not in VALID_ACTIONS:
        raise QRGeneratorError(f"未知动作 {action!r}，可选: {sorted(VALID_ACTIONS)}")
    if action == "walk":
        if as_int_in_range(params.get("steps", 3), 1, MAX_STEPS) is None:
            raise QRGeneratorError(
                f"walk.steps 非法: {params.get('steps')!r}（应为 1..{MAX_STEPS} 整数）"
            )
    elif action == "turn":
        deg = as_finite_float(params.get("deg", 30.0))
        if deg is None or abs(deg) > MAX_TURN_DEG:
            raise QRGeneratorError(
                f"turn.deg 非法: {params.get('deg')!r}"
                f"（应为 ±{MAX_TURN_DEG:g} 内的有限数值）"
            )
    elif action == "dance":
        if as_int_in_range(params.get("bars", 2), 1, MAX_BARS) is None:
            raise QRGeneratorError(
                f"dance.bars 非法: {params.get('bars')!r}（应为 1..{MAX_BARS} 整数）"
            )


def build_qr_payload(action: str, **params: Any) -> str:
    """构造二维码内嵌 JSON 指令字符串。"""
    payload = {"action": action, **params}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_param_value(value: str) -> Any:
    """把 CLI 的 key=value 值转成 int/float；转不动或非有限值时保留字符串。"""
    for cast in (int, float):
        try:
            number = cast(value)
        except ValueError:
            continue
        if isinstance(number, float) and not math.isfinite(number):
            break
        return number
    return value


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
        validate_params(action, params)
        payload = build_qr_payload(action, **params)
        return self.write_payload(payload, output_path)

    def write_payload(self, payload: str, output_path: str | Path) -> str:
        """把已经校验过的 JSON 字符串写成二维码图。"""
        qr = self._get_qrcode()
        img = qr.make(payload)
        img.save(str(output_path))
        return str(output_path)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成内嵌 JSON 指令的二维码")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--action", help="指令动作，如 walk/turn/kick")
    source.add_argument("--json", dest="raw_json", help="直接传入完整 JSON 指令字符串（与 --action 二选一）")
    parser.add_argument("--output", "-o", required=True, help="输出图片路径，如 qr_walk.png")
    parser.add_argument("--param", "-p", action="append", default=[], help="附加参数 key=value，可多次")
    parser.add_argument("--steps", type=int, help="快捷参数：行走步数")
    parser.add_argument("--deg", type=int, help="快捷参数：转向角度")
    parser.add_argument("--bars", type=int, help="快捷参数：舞蹈小节数")
    args = parser.parse_args(argv)

    if args.raw_json:
        try:
            data = json.loads(args.raw_json, parse_constant=_reject_constant)
        except (json.JSONDecodeError, QRGeneratorError) as exc:
            print(f"错误：JSON 解析失败 {exc}", file=sys.stderr)
            return 2
        if not isinstance(data, dict):
            print("错误：--json 必须是 JSON 对象", file=sys.stderr)
            return 2
        if "path" in data:
            from .skills.qr import parse_qr_payload
            steps, err = parse_qr_payload(data)
            if err:
                print(f"错误：{err}", file=sys.stderr)
                return 2
            assert steps is not None
            for item in steps:
                validate_params(str(item.get("action", "")), {k: v for k, v in item.items() if k != "action"})
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            gen = QRCodeGenerator()
            try:
                path = gen.write_payload(payload, args.output)
            except QRGeneratorError as exc:
                print(f"错误：{exc}", file=sys.stderr)
                return 2
            print(f"二维码已生成: {path}")
            return 0
        action = str(data.get("action", ""))
        params: Dict[str, Any] = {k: v for k, v in data.items() if k != "action"}
    else:
        action = args.action
        params = {}
        for item in args.param:
            if "=" not in item:
                print(f"错误：--param 需要 key=value 格式：{item}", file=sys.stderr)
                return 2
            key, value = item.split("=", 1)
            params[key] = parse_param_value(value)

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
