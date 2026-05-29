import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"
COMMAND = TOOLS / "vela_codex_gpt_command.py"


def load_command_module():
    assert COMMAND.exists(), "vela_codex_gpt_command.py should exist"
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("vela_codex_gpt_command", COMMAND)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaCodexGptCommandTests(unittest.TestCase):
    def test_build_prompt_includes_context_and_forbids_engineering_noise(self):
        command = load_command_module()
        context = {
            "message": "地狱验尸一下 VELA 为什么不智能",
            "intent": "deep_analysis",
            "surface": "wechat_short_reply",
            "tool_policy": {"allow_market": False, "allow_codex": False},
        }

        prompt = command.build_codex_prompt(context)

        self.assertIn("地狱验尸一下 VELA 为什么不智能", prompt)
        self.assertIn("deep_analysis", prompt)
        self.assertIn("wechat_short_reply", prompt)
        self.assertIn("不要输出 token", prompt)
        self.assertIn("不要调用 shell", prompt)

    def test_main_prints_only_last_message_file_content(self):
        command = load_command_module()
        context = {"message": "你好 VELA", "intent": "normal_chat", "surface": "wechat_short_reply"}

        def fake_run(args, **kwargs):
            output_path = Path(args[args.index("-o") + 1])
            output_path.write_text("K，真实模型已接管。", encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stdout": "codex logs", "stderr": "tokens used"})()

        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with patch("sys.stdin", io.StringIO(json.dumps(context, ensure_ascii=False))):
                with patch("sys.stdout", stdout):
                    with patch("subprocess.run", side_effect=fake_run) as run:
                        code = command.main(["--timeout", "180", "--tmp-dir", tmp])

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().strip(), "K，真实模型已接管。")
        self.assertIn("--ephemeral", run.call_args.args[0])
        self.assertNotIn("codex logs", stdout.getvalue())
        self.assertNotIn("tokens used", stdout.getvalue().lower())

    def test_windows_cmd_codex_launcher_uses_cmd_exe(self):
        command = load_command_module()
        context = {"message": "你好 VELA", "intent": "normal_chat", "surface": "wechat_short_reply"}

        def fake_run(args, **kwargs):
            output_path = Path(args[args.index("-o") + 1])
            output_path.write_text("K，cmd 包装可调用。", encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with patch("shutil.which", return_value=r"C:\Users\Admin\AppData\Local\hermes\bin\codex.CMD"):
                with patch("sys.stdin", io.StringIO(json.dumps(context, ensure_ascii=False))):
                    with patch("sys.stdout", stdout):
                        with patch("subprocess.run", side_effect=fake_run) as run:
                            code = command.main(["--timeout", "180", "--tmp-dir", tmp])

        launch_args = run.call_args.args[0]
        self.assertEqual(code, 0)
        self.assertEqual(launch_args[:3], ["cmd", "/d", "/c"])
        self.assertIn("codex.CMD", launch_args[3])
        self.assertEqual(stdout.getvalue().strip(), "K，cmd 包装可调用。")


if __name__ == "__main__":
    unittest.main()
