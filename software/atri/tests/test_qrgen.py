import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import atri.qrgen as qrgen_module
from atri.config import MAX_BARS, MAX_STEPS, MAX_TURN_DEG
from atri.qrgen import QRCodeGenerator, QRGeneratorError, build_qr_payload, parse_param_value


class FakeQRImage:
    def __init__(self, payload):
        self.payload = payload

    def save(self, path, **kwargs):
        self.saved_path = str(path)
        Path(path).write_bytes(b"fake-qr")


class FakeQRCode:
    def __init__(self):
        self.last_payload = None

    def make(self, payload, **kwargs):
        self.last_payload = payload
        return FakeQRImage(payload)


class RecordingGenerator:
    """替代 QRCodeGenerator 记录 CLI 传入的动作与参数。"""

    def __init__(self):
        self.calls = []

    def generate(self, action, output_path, **params):
        self.calls.append((action, str(output_path), params))
        Path(output_path).write_bytes(b"fake-qr")
        return str(output_path)


class TestBuildPayload(unittest.TestCase):
    def test_build_payload(self):
        payload = build_qr_payload("walk", steps=3, remark="test")
        data = json.loads(payload)
        self.assertEqual(data["action"], "walk")
        self.assertEqual(data["steps"], 3)
        self.assertEqual(data["remark"], "test")

    def test_parse_param_value_casts_numbers(self):
        self.assertEqual(parse_param_value("3"), 3)
        self.assertEqual(parse_param_value("1.5"), 1.5)
        self.assertEqual(parse_param_value("abc"), "abc")
        self.assertEqual(parse_param_value("nan"), "nan")


class TestQRCodeGenerator(unittest.TestCase):
    def test_generate_with_fake_qrcode(self):
        fake = FakeQRCode()
        gen = QRCodeGenerator(qrcode_module=fake)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cmd.png"
            result = gen.generate("walk", out, steps=2)
            self.assertEqual(Path(result), out)
            self.assertTrue(out.exists())
            self.assertEqual(json.loads(fake.last_payload)["action"], "walk")
            self.assertEqual(json.loads(fake.last_payload)["steps"], 2)

    def test_unknown_action_rejected(self):
        gen = QRCodeGenerator(qrcode_module=FakeQRCode())
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(QRGeneratorError):
                gen.generate("fly", Path(tmp) / "x.png")

    def test_missing_qrcode_raises(self):
        """qrcode 缺失时必须报可读错误——**与环境无关**地模拟"缺依赖"。

        ⚠️ 2026-09-12 修：原写法用 `sys.modules.pop("qrcode")` 隐藏模块，但**包真装在
        site-packages 里时，下一次 import 会重新从磁盘导入**，于是这条测试在
        "环境里恰好装了 qrcode"时假失败（本机 09:23 被装上 qrcode 8.2 后即触发）。
        正确做法是往 `sys.modules` 里塞 `None`：Python 见到 None 会直接抛 ImportError，
        与磁盘上有没有这个包无关。
        """
        gen = QRCodeGenerator(qrcode_module=None)
        import sys
        saved = sys.modules.get("qrcode", "__ABSENT__")
        sys.modules["qrcode"] = None
        try:
            with self.assertRaises(QRGeneratorError):
                gen.generate("walk", Path("/tmp/x.png"))
        finally:
            if saved == "__ABSENT__":
                sys.modules.pop("qrcode", None)
            else:
                sys.modules["qrcode"] = saved

    def test_default_actions_removed(self):
        self.assertFalse(hasattr(qrgen_module, "DEFAULT_ACTIONS"))


class TestQRGenValidation(unittest.TestCase):
    """生成端必须复用技能侧同一套区间校验，不能生成跑不通的指令二维码。"""

    def setUp(self):
        self.gen = QRCodeGenerator(qrcode_module=FakeQRCode())

    def _generate(self, action, **params):
        with tempfile.TemporaryDirectory() as tmp:
            return self.gen.generate(action, Path(tmp) / "cmd.png", **params)

    def test_valid_params_accepted(self):
        self._generate("walk", steps=3)
        self._generate("turn", deg=90)
        self._generate("dance", bars=2)

    def test_walk_steps_over_limit_rejected(self):
        with self.assertRaises(QRGeneratorError):
            self._generate("walk", steps=MAX_STEPS + 1)

    def test_walk_steps_non_positive_rejected(self):
        for steps in (0, -1):
            with self.subTest(steps=steps):
                with self.assertRaises(QRGeneratorError):
                    self._generate("walk", steps=steps)

    def test_walk_steps_non_integer_rejected(self):
        with self.assertRaises(QRGeneratorError):
            self._generate("walk", steps="3")

    def test_turn_deg_over_limit_rejected(self):
        with self.assertRaises(QRGeneratorError):
            self._generate("turn", deg=MAX_TURN_DEG + 1.0)

    def test_turn_deg_nan_rejected(self):
        with self.assertRaises(QRGeneratorError):
            self._generate("turn", deg=float("nan"))

    def test_dance_bars_over_limit_rejected(self):
        with self.assertRaises(QRGeneratorError):
            self._generate("dance", bars=MAX_BARS + 1)


class TestQRGenCLIValidation(unittest.TestCase):
    def _run(self, argv):
        with tempfile.TemporaryDirectory() as tmp:
            return qrgen_module.main(argv + ["-o", str(Path(tmp) / "out.png")])

    def test_json_nan_rejected(self):
        self.assertEqual(
            self._run(["--json", '{"action":"walk","steps":NaN}']), 2
        )

    def test_json_infinity_rejected(self):
        self.assertEqual(
            self._run(["--json", '{"action":"walk","steps":Infinity}']), 2
        )

    def test_invalid_steps_exit_nonzero(self):
        self.assertEqual(self._run(["--action", "walk", "--steps", "999"]), 2)

    def test_invalid_turn_deg_exit_nonzero(self):
        self.assertEqual(self._run(["--action", "turn", "--deg", "9999"]), 2)


class TestQRGenCLI(unittest.TestCase):
    def test_json_only_is_accepted(self):
        gen = RecordingGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            with mock.patch("atri.qrgen.QRCodeGenerator", return_value=gen):
                code = qrgen_module.main(
                    ["--json", '{"action":"walk","steps":2}', "-o", str(out)]
                )
            self.assertEqual(code, 0)
            self.assertEqual(gen.calls[0][0], "walk")
            self.assertEqual(gen.calls[0][2], {"steps": 2})

    def test_action_only_is_accepted(self):
        gen = RecordingGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            with mock.patch("atri.qrgen.QRCodeGenerator", return_value=gen):
                code = qrgen_module.main(["--action", "turn", "-o", str(out), "--deg", "30"])
            self.assertEqual(code, 0)
            self.assertEqual(gen.calls[0][0], "turn")
            self.assertEqual(gen.calls[0][2], {"deg": 30})

    def test_action_and_json_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            with self.assertRaises(SystemExit) as ctx:
                qrgen_module.main(
                    ["--action", "walk", "--json", '{"action":"walk"}', "-o", str(out)]
                )
            self.assertEqual(ctx.exception.code, 2)

    def test_one_of_action_or_json_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            with self.assertRaises(SystemExit) as ctx:
                qrgen_module.main(["-o", str(out)])
            self.assertEqual(ctx.exception.code, 2)

    def test_param_values_are_cast(self):
        gen = RecordingGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            with mock.patch("atri.qrgen.QRCodeGenerator", return_value=gen):
                code = qrgen_module.main(
                    [
                        "--action",
                        "walk",
                        "-o",
                        str(out),
                        "--param",
                        "steps=3",
                        "--param",
                        "ratio=1.5",
                        "--param",
                        "name=abc",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(gen.calls[0][2], {"steps": 3, "ratio": 1.5, "name": "abc"})

    def test_generator_error_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            code = qrgen_module.main(["--action", "fly", "-o", str(out)])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
