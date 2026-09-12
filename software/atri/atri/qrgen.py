"""二维码 JSON 指令生成器（含**路径**）。

生成内嵌 JSON 指令的二维码图片，供 Webots 仿真、Windows 视觉联调和现场打印使用。
默认依赖 qrcode 库（可选）：``pip install "qrcode[pil]"``

两种 payload：

**路径（赛题要的形态：按指示路径行走）**
```json
{"schema":"atri.path.v1","path":[{"action":"walk","steps":3},{"action":"turn","deg":90}]}
```
命令行： ``--path '[{"action":"walk","steps":3},{"action":"turn","deg":90}]'``

**单条指令（旧格式，继续可用）**
```json
{"action":"walk","steps":3}
```

## 校验与容量

- 参数校验复用 :func:`atri.path_plan.validate_segment`，与**执行端同一套边界**，
  生成得出但跑不通的二维码不该被造出来；
- 容量不足（路径太长）时转成明确的中文错误提示；
- 生成后回报**二维码版本 / 模块数 / 像素尺寸**——路径越长码越密，
  直接关系到现场扫不扫得动（实测见 ``software/atri/tools/qr_eval.py`` 出的报告）。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .path_plan import PATH_SCHEMA, Path, PathError, build_path, validate_segment

# 纠错级别：越高越耐污损/反光，但同样内容需要更多模块（码更密、更难扫）。
# 这是**鲁棒性与可读性的主要旋钮**，实测对照见 tools/qr_eval.py。
ECC_LEVELS = ("L", "M", "Q", "H")
DEFAULT_ECC = "M"  # noqa: E501  (qrcode 默认值，保持一致)


class QRGeneratorError(RuntimeError):
    pass


def _reject_constant(value: str) -> Any:
    """json.loads 的 parse_constant 钩子：拒绝 JSON 标准之外的 NaN/Infinity。"""
    raise QRGeneratorError(f"JSON 不允许常量 {value}（NaN/Infinity）")


def validate_params(action: str, params: Dict[str, Any]) -> None:
    """生成前按**执行端同一口径**校验参数，非法指令直接报错，不留到运行时。

    真正的实现在 :func:`atri.path_plan.validate_segment`（唯一口径），
    这里只做异常类型转换，保持本模块对外仍抛 :class:`QRGeneratorError`。
    """
    try:
        validate_segment(action, params)
    except PathError as exc:
        raise QRGeneratorError(str(exc)) from exc


def build_qr_payload(action: str, **params: Any) -> str:
    """构造单条指令的 payload 字符串（旧格式，保留）。"""
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


def resolve_ecc(qrcode_module: Any, name: str) -> Any:
    """把 ``L/M/Q/H`` 转成 qrcode 模块里的常量。不认识的级别直接报错。"""
    name = str(name).upper()
    if name not in ECC_LEVELS:
        raise QRGeneratorError(f"未知纠错级别 {name!r}，可选: {list(ECC_LEVELS)}")
    constants = getattr(qrcode_module, "constants", None)
    attr = f"ERROR_CORRECT_{name}"
    if constants is not None and hasattr(constants, attr):
        return getattr(constants, attr)
    # 注入的 fake qrcode 没有 constants：返回名字本身，由 fake 自行忽略
    return name


class QRCodeGenerator:
    def __init__(
        self,
        qrcode_module: Any = None,
        error_correction: str = DEFAULT_ECC,
        box_size: int = 10,
        border: int = 4,
    ) -> None:
        """qrcode_module 仅供测试注入 fake；正常使用传 None 自动 import qrcode。"""
        self._qrcode = qrcode_module
        self.error_correction = str(error_correction).upper()
        self.box_size = int(box_size)
        self.border = int(border)
        self.last_info: Dict[str, Any] = {}

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

    # ────────────────── 生成 ──────────────────

    def generate_payload(self, payload: str, output_path: str | Path) -> str:
        """把任意 payload 字符串编码成二维码图片。"""
        qr = self._get_qrcode()
        kwargs: Dict[str, Any] = {
            "box_size": self.box_size,
            "border": self.border,
            "error_correction": resolve_ecc(qr, self.error_correction),
        }
        try:
            img = qr.make(payload, **kwargs)
        except QRGeneratorError:
            raise
        except Exception as exc:
            name = type(exc).__name__
            text = str(exc).lower()
            if "overflow" in name.lower() or "too long" in text or "data" in text and "capacity" in text:
                raise QRGeneratorError(
                    f"内容太长，放不进二维码：payload {len(payload.encode('utf-8'))} 字节"
                    f" / 纠错 {self.error_correction}。"
                    "缩短路径（减少段数或步数），或降低纠错级别后重试。"
                ) from exc
            raise QRGeneratorError(f"生成二维码失败：{name}: {exc}") from exc
        img.save(str(output_path))
        self.last_info = self._describe(payload, img)
        return str(output_path)

    def write_payload(self, payload: str, output_path: str | Path) -> str:
        """把**已经校验过**的 JSON 字符串写成二维码图（保留的旧接口名）。"""
        return self.generate_payload(payload, output_path)

    def generate(
        self,
        action: str,
        output_path: str | Path,
        **params: Any,
    ) -> str:
        """生成**单条指令**二维码（旧接口，保留）。"""
        validate_params(action, params)
        return self.generate_payload(build_qr_payload(action, **params), output_path)

    def generate_path(
        self,
        segments: Sequence[Dict[str, Any]],
        output_path: str | Path,
        schema: str = PATH_SCHEMA,
    ) -> str:
        """生成**路径**二维码。段数组先过校验（与执行端同源）。"""
        try:
            path: Path = build_path(segments, schema=schema)
        except PathError as exc:
            raise QRGeneratorError(f"路径非法：{exc}") from exc
        return self.generate_payload(path.to_json(), output_path)

    # ────────────────── 容量信息 ──────────────────

    def _describe(self, payload: str, img: Any) -> Dict[str, Any]:
        """从生成的图片反推二维码版本与模块数：路径越长码越密，直接影响可扫性。"""
        info: Dict[str, Any] = {
            "payload_bytes": len(payload.encode("utf-8")),
            "error_correction": self.error_correction,
            "box_size": self.box_size,
            "border": self.border,
        }
        size = getattr(img, "size", None)
        if isinstance(size, (tuple, list)) and len(size) == 2 and self.box_size > 0:
            modules = size[0] / self.box_size - 2 * self.border
            version = (modules - 17) / 4
            info.update({
                "image_px": [int(size[0]), int(size[1])],
                "modules": int(round(modules)),
                "version": int(round(version)),
            })
        return info


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成内嵌 JSON 指令的二维码（支持路径）")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--action", help="单条指令动作，如 walk/turn/dance")
    source.add_argument(
        "--path", dest="raw_path", help='路径段数组 JSON，如 \'[{"action":"walk","steps":3}]\''
    )
    source.add_argument("--json", dest="raw_json", help="完整 payload JSON（新旧格式都可）")
    parser.add_argument("--output", "-o", required=True, help="输出图片路径，如 qr_path.png")
    parser.add_argument("--param", "-p", action="append", default=[], help="附加参数 key=value，可多次")
    parser.add_argument("--steps", type=int, help="快捷参数：行走步数")
    parser.add_argument("--deg", type=int, help="快捷参数：转向角度")
    parser.add_argument("--bars", type=int, help="快捷参数：舞蹈小节数")
    parser.add_argument("--ecc", default=DEFAULT_ECC, choices=list(ECC_LEVELS), help="纠错级别（默认 M）")
    parser.add_argument("--box-size", type=int, default=10, help="每模块像素数（默认 10）")
    args = parser.parse_args(argv)

    gen = QRCodeGenerator(error_correction=args.ecc, box_size=args.box_size)

    try:
        if args.raw_path is not None:
            try:
                segments = json.loads(args.raw_path, parse_constant=_reject_constant)
            except (json.JSONDecodeError, QRGeneratorError) as exc:
                print(f"错误：--path 不是合法 JSON：{exc}", file=sys.stderr)
                return 2
            if not isinstance(segments, list):
                print('错误：--path 必须是段数组，如 \'[{"action":"walk","steps":3}]\'', file=sys.stderr)
                return 2
            path = gen.generate_path(segments, args.output)

        elif args.raw_json is not None:
            try:
                data = json.loads(args.raw_json, parse_constant=_reject_constant)
            except (json.JSONDecodeError, QRGeneratorError) as exc:
                print(f"错误：JSON 解析失败 {exc}", file=sys.stderr)
                return 2
            if not isinstance(data, dict):
                print("错误：--json 必须是 JSON 对象", file=sys.stderr)
                return 2
            if "path" in data:
                path = gen.generate_path(
                    data["path"], args.output, schema=str(data.get("schema", PATH_SCHEMA))
                )
            else:
                action = str(data.get("action", ""))
                params = {k: v for k, v in data.items() if k != "action"}
                if not action:
                    print("错误：action 不能为空", file=sys.stderr)
                    return 2
                path = gen.generate(action, args.output, **params)

        else:
            action = args.action
            params: Dict[str, Any] = {}
            for item in args.param:
                if "=" not in item:
                    print(f"错误：--param 需要 key=value 格式：{item}", file=sys.stderr)
                    return 2
                key, value = item.split("=", 1)
                params[key] = parse_param_value(value)
            for key, value in (("steps", args.steps), ("deg", args.deg), ("bars", args.bars)):
                if value is not None:
                    params[key] = value
            path = gen.generate(action, args.output, **params)

    except QRGeneratorError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    # 注入的替身（测试）可能没有 last_info：拿不到就不印容量行，不影响退出码
    info = getattr(gen, "last_info", None) or {}
    print(f"二维码已生成: {path}")
    if info:
        print(
            f"  payload {info.get('payload_bytes')} 字节 | 纠错 {info.get('error_correction')}"
            f" | 版本 {info.get('version')} | {info.get('modules')} 模块"
            f" | {info.get('image_px')} px"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
