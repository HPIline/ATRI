import subprocess
import sys
import unittest
from unittest import mock

from atri.voice import (
    LinuxTTS,
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


def _boom_runner(*_args, **_kwargs):
    raise AssertionError("TTS runner should not be invoked")


class TestLinuxTTS(unittest.TestCase):
    def test_force_mock_via_env(self):
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        tts = LinuxTTS(
            runner=fake_run,
            looks=["piper", "espeak-ng"],
            env={"ATRI_TTS": "mock"},
        )
        self.assertEqual(tts.engine, "mock")
        tts.speak("你好")
        self.assertEqual(tts.spoken, ["你好"])
        self.assertEqual(commands, [])
        self.assertIsInstance(
            build_tts("linux", looks=["piper"], env={"ATRI_TTS": "mock"}),
            MockTTS,
        )

    def test_force_piper_command_line(self):
        commands = []
        inputs = []

        def fake_run(cmd, **kwargs):
            commands.append(list(cmd))
            inputs.append(kwargs.get("input"))
            return subprocess.CompletedProcess(cmd, 0)

        tts = LinuxTTS(
            runner=fake_run,
            looks=[],
            env={"ATRI_TTS": "piper", "ATRI_PIPER_MODEL": "en_US-lessac-medium.onnx"},
        )
        self.assertEqual(tts.engine, "piper")
        self.assertNotEqual(tts.name, MockTTS.name)
        tts.speak("hello")
        self.assertEqual(commands[0][0], "piper")
        self.assertIn("--model", commands[0])
        self.assertIn("en_US-lessac-medium.onnx", commands[0])
        self.assertEqual(inputs[0], "hello")
        built = build_tts("linux", runner=fake_run, env={"ATRI_TTS": "piper"})
        self.assertIsInstance(built, LinuxTTS)
        self.assertEqual(built.engine, "piper")

    def test_path_only_espeak_ng(self):
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        tts = LinuxTTS(runner=fake_run, looks=["espeak-ng"], env={})
        self.assertEqual(tts.engine, "espeak-ng")
        tts.speak("你好")
        self.assertEqual(commands[0][0], "espeak-ng")
        self.assertIn("你好", commands[0])
        built = build_tts("linux", runner=fake_run, looks=["espeak-ng"], env={})
        self.assertIsInstance(built, LinuxTTS)
        self.assertEqual(built.engine, "espeak-ng")

    def test_no_engine_falls_back_to_mock(self):
        tts = LinuxTTS(runner=_boom_runner, looks=[], env={})
        self.assertIn(tts.engine, (None, "mock"))
        tts.speak("静默")
        self.assertEqual(tts.spoken, ["静默"])
        self.assertIsInstance(build_tts("linux", looks=[], env={}), MockTTS)

    def test_invalid_atri_tts_falls_back(self):
        tts = LinuxTTS(
            runner=_boom_runner,
            looks=["piper", "espeak-ng"],
            env={"ATRI_TTS": "not-a-real-engine"},
        )
        self.assertEqual(tts.engine, "mock")
        tts.speak("回退")
        self.assertEqual(tts.spoken, ["回退"])
        self.assertIsInstance(
            build_tts(
                "linux",
                looks=["piper"],
                env={"ATRI_TTS": "not-a-real-engine"},
            ),
            MockTTS,
        )

    def test_probe_order_prefers_piper(self):
        tts = LinuxTTS(
            runner=_boom_runner,
            looks=["spd-say", "espeak", "espeak-ng", "piper"],
            env={},
        )
        self.assertEqual(tts.engine, "piper")

    def test_which_injection(self):
        def fake_which(name):
            return "/usr/bin/espeak" if name == "espeak" else None

        tts = LinuxTTS(runner=_boom_runner, which=fake_which, env={})
        self.assertEqual(tts.engine, "espeak")

    def test_failed_engine_raises(self):
        def failing_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1)

        tts = LinuxTTS(engine="espeak-ng", runner=failing_run, looks=["espeak-ng"])
        with self.assertRaises(VoiceError) as ctx:
            tts.speak("你好")
        self.assertIn("1", str(ctx.exception))


class TestBuildTTS(unittest.TestCase):
    def test_darwin_uses_macos_tts(self):
        tts = build_tts("darwin")
        self.assertIsInstance(tts, MacOSTTS)
        self.assertTrue(tts.is_darwin)

    def test_other_platform_falls_back_to_mock(self):
        self.assertIsInstance(build_tts("win32"), MockTTS)

    def test_linux_with_engine_returns_linux_tts(self):
        tts = build_tts("linux", looks=["spd-say"], env={})
        self.assertIsInstance(tts, LinuxTTS)
        self.assertEqual(tts.engine, "spd-say")

    def test_default_platform_returns_tts(self):
        tts = build_tts()
        self.assertIsInstance(tts, TTS)
        self.assertIsInstance(tts, (MockTTS, MacOSTTS, LinuxTTS))
        self.assertEqual(build_tts(sys.platform).name, tts.name)

    def test_default_follows_sys_platform_linux(self):
        with mock.patch.object(sys, "platform", "linux"):
            tts = build_tts(looks=["espeak-ng"], env={})
            self.assertIsInstance(tts, LinuxTTS)
            self.assertEqual(tts.engine, "espeak-ng")
            self.assertIsInstance(build_tts(looks=[], env={}), MockTTS)


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
