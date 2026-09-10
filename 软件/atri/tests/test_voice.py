import unittest

from atri.voice import (
    KeywordRecognizer,
    MockKeywordRecognizer,
    MockTTS,
    MacOSTTS,
    TTS,
    VoiceError,
    VoiceService,
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
            return __import__("subprocess").CompletedProcess(cmd, 0)

        tts = MacOSTTS(is_darwin=True, runner=fake_run)
        tts.speak("你好，世界")
        self.assertEqual(commands[0][0], "say")
        self.assertIn("你好，世界", commands[0])

    def test_non_darwin_raises(self):
        tts = MacOSTTS(is_darwin=False)
        with self.assertRaises(VoiceError):
            tts.speak("你好")


class TestVoiceService(unittest.TestCase):
    def test_respond(self):
        rec = MockKeywordRecognizer(keywords=("跳舞",))
        tts = MockTTS()
        svc = VoiceService(recognizer=rec, tts=tts)
        out = svc.respond()
        self.assertEqual(out["keyword"], "跳舞")
        self.assertEqual(tts.spoken[-1], "跳舞")


if __name__ == "__main__":
    unittest.main()
