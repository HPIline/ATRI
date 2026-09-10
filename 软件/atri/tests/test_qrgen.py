import json
import tempfile
import unittest
from pathlib import Path

from atri.qrgen import QRCodeGenerator, QRGeneratorError, build_qr_payload


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


class TestBuildPayload(unittest.TestCase):
    def test_build_payload(self):
        payload = build_qr_payload("walk", steps=3, remark="test")
        data = json.loads(payload)
        self.assertEqual(data["action"], "walk")
        self.assertEqual(data["steps"], 3)
        self.assertEqual(data["remark"], "test")


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

    def test_missing_qrcode_raises(self):
        gen = QRCodeGenerator(qrcode_module=None)
        # Force import failure by temporarily hiding qrcode in sys.modules if present.
        import sys
        saved = sys.modules.pop("qrcode", None)
        try:
            with self.assertRaises(QRGeneratorError):
                gen.generate("walk", Path("/tmp/x.png"))
        finally:
            if saved is not None:
                sys.modules["qrcode"] = saved


if __name__ == "__main__":
    unittest.main()
