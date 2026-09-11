import subprocess
import sys
import unittest

from atri.voice import (
    MacOSTTS,
    MockKeywordRecognizer,
    MockTTS,
    TTS,
    VoiceError,
    VoiceService,
    build_tts,
)


class TestMockKeywordRecognizer(unittest.TestCase):
    def test_default_keyword(self):
        rec = MockKeywordRecognizer()
        self.assertEqual(rec.recognize(), "跳舞")

    def test_custom_keywords(self):
        rec = MockKeywordRecognizer(keywords=("前进", "停止"), default="前进")
        self.assertEqual(rec.recognize(audio=b"ignored"), "前进")

    def test_next_keyword_cycle(self):
        rec = MockKeywordRecognizer(keywords=("前进", "跳舞"))
        self.assertEqual(rec.next_keyword, "前进")
        self.assertEqual(rec.next_keyword, "跳舞")
        self.assertEqual(rec.next_keyword, "前进")


class TestMockTTS(unittest.TestCase):
    def test_speak_records(self):
        tts = MockTTS()
        tts.speak("你好")
        self.assertEqual(tts.spoken, ["你好"])


class TestMacOSTTS(unittest.TestCase):
    def test_speak_uses_say_command(self):
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        tts = MacOSTTS(is_darwin=True, runner=fake_run)
        tts.speak("你好，世界")
        self.assertEqual(commands[0][0], "say")
        self.assertIn("你好，世界", commands[0])

    def test_non_darwin_raises(self):
        tts = MacOSTTS(is_darwin=False)
        with self.assertRaises(VoiceError):
            tts.speak("你好")

    def test_failed_say_raises(self):
        def failing_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1)

        tts = MacOSTTS(is_darwin=True, runner=failing_run)
        with self.assertRaises(VoiceError) as ctx:
            tts.speak("你好")
        self.assertIn("1", str(ctx.exception))


class TestBuildTTS(unittest.TestCase):
    def test_darwin_uses_macos_tts(self):
        tts = build_tts("darwin")
        self.assertIsInstance(tts, MacOSTTS)
        self.assertTrue(tts.is_darwin)

    def test_other_platform_falls_back_to_mock(self):
        for platform in ("linux", "win32"):
            self.assertIsInstance(build_tts(platform), MockTTS)

    def test_default_platform_returns_tts(self):
        tts = build_tts()
        self.assertIsInstance(tts, TTS)
        self.assertIsInstance(tts, (MockTTS, MacOSTTS))
        self.assertEqual(build_tts(sys.platform).name, tts.name)


class TestVoiceService(unittest.TestCase):
    def test_respond(self):
        rec = MockKeywordRecognizer(keywords=("跳舞",))
        tts = MockTTS()
        svc = VoiceService(recognizer=rec, tts=tts)
        out = svc.respond()
        self.assertEqual(out["keyword"], "跳舞")
        self.assertEqual(tts.spoken[-1], "跳舞")

    def test_bad_template_falls_back(self):
        rec = MockKeywordRecognizer(keywords=("跳舞",))
        tts = MockTTS()
        svc = VoiceService(recognizer=rec, tts=tts)
        out = svc.respond(reply_template="{unknown}")
        self.assertEqual(out["keyword"], "跳舞")
        self.assertEqual(out["reply"], "跳舞")
        self.assertEqual(tts.spoken[-1], "跳舞")


if __name__ == "__main__":
    unittest.main()
