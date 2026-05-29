import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"
REPLY_ENGINE = TOOLS / "vela_reply_engine.py"


def load_reply_engine():
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("vela_reply_engine", REPLY_ENGINE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaReplyEngineTests(unittest.TestCase):
    def test_status_reports_real_gpt_disabled_without_secrets(self):
        engine = load_reply_engine()
        with patch.dict("os.environ", {}, clear=True):
            status = engine.reply_engine_status()

        self.assertFalse(status["real_gpt_enabled"])
        self.assertEqual(status["adapter"], "fallback")
        self.assertIn("DEEPSEEK_API_KEY", status["missing"])
        self.assertIn("VELA_OPENAI_API_KEY", status["missing"])
        self.assertNotIn("sk-", json.dumps(status).lower())

    def test_explicit_empty_env_does_not_read_real_environment(self):
        engine = load_reply_engine()
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-real-secret"}, clear=True):
            status = engine.reply_engine_status({})

        self.assertFalse(status["real_gpt_enabled"])
        self.assertEqual(status["adapter"], "fallback")

    def test_status_prefers_command_adapter_when_configured(self):
        engine = load_reply_engine()
        with patch.dict("os.environ", {"VELA_GPT_COMMAND": "python fake_gpt.py"}, clear=True):
            status = engine.reply_engine_status()
            adapter = engine.default_reply_adapter()

        self.assertTrue(status["real_gpt_enabled"])
        self.assertEqual(status["adapter"], "command")
        self.assertEqual(status["config_source"], "VELA_GPT_COMMAND")
        self.assertEqual(adapter.name, "command")

    def test_status_uses_openai_adapter_without_revealing_key(self):
        engine = load_reply_engine()
        with patch.dict("os.environ", {"VELA_OPENAI_API_KEY": "sk-test-secret"}, clear=True):
            status = engine.reply_engine_status()
            adapter = engine.default_reply_adapter()

        self.assertTrue(status["real_gpt_enabled"])
        self.assertEqual(status["adapter"], "openai_responses")
        self.assertEqual(status["config_source"], "VELA_OPENAI_API_KEY")
        self.assertEqual(adapter.name, "openai_responses")
        self.assertNotIn("sk-test-secret", json.dumps(status))

    def test_status_uses_deepseek_adapter_without_revealing_key(self):
        engine = load_reply_engine()
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-deepseek-secret"}, clear=True):
            status = engine.reply_engine_status()
            adapter = engine.default_reply_adapter()

        self.assertTrue(status["real_gpt_enabled"])
        self.assertEqual(status["adapter"], "deepseek_chat")
        self.assertEqual(status["config_source"], "DEEPSEEK_API_KEY")
        self.assertEqual(status["model"], "deepseek-v4-flash")
        self.assertEqual(status["thinking"], "disabled")
        self.assertEqual(adapter.name, "deepseek_chat")
        self.assertNotIn("sk-deepseek-secret", json.dumps(status))

    def test_blank_deepseek_key_does_not_shadow_openai(self):
        engine = load_reply_engine()
        status = engine.reply_engine_status(
            {
                "DEEPSEEK_API_KEY": "   ",
                "VELA_OPENAI_API_KEY": "sk-openai-secret",
                "VELA_OPENAI_MODEL": " gpt-test ",
            }
        )

        self.assertTrue(status["real_gpt_enabled"])
        self.assertEqual(status["adapter"], "openai_responses")
        self.assertEqual(status["config_source"], "VELA_OPENAI_API_KEY")
        self.assertEqual(status["model"], "gpt-test")

    def test_command_adapter_failure_logs_internally_and_falls_back(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(message="你好", intent="normal_chat")
        with tempfile.TemporaryDirectory() as tmp:
            adapter = engine.CommandReplyAdapter(
                "python -c \"import sys; sys.stderr.write('boom'); sys.exit(7)\"",
                log_dir=Path(tmp),
            )

            result = adapter.generate(context)
            logs = list(Path(tmp).glob("gpt-adapter-failures-*.jsonl"))
            row = json.loads(logs[0].read_text(encoding="utf-8").strip())

        self.assertEqual(result.adapter, "fallback")
        self.assertFalse(result.used_api)
        self.assertEqual(row["adapter"], "command")
        self.assertIn("returncode_7", row["reason"])
        self.assertNotIn("boom", json.dumps(row))

    def test_command_adapter_clamps_configured_timeout_to_foreground_budget(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(message="分析一下 VELA", intent="deep_analysis")
        with patch.dict("os.environ", {"VELA_GPT_TIMEOUT_SECONDS": "180"}, clear=True):
            with patch("subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "K，真实模型接管。"

                result = engine.CommandReplyAdapter("fake-gpt-command").generate(context)

        self.assertEqual(result.adapter, "command")
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_command_timeout_defaults_to_fast_foreground_budget(self):
        engine = load_reply_engine()

        self.assertEqual(engine.command_timeout_seconds({}), 12)

    def test_openai_adapter_failure_logs_internally_and_falls_back(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(message="你好", intent="normal_chat")
        with tempfile.TemporaryDirectory() as tmp:
            adapter = engine.OpenAIResponsesAdapter(
                api_key="sk-test-secret",
                model="gpt-test",
                log_dir=Path(tmp),
            )
            with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
                result = adapter.generate(context)
            logs = list(Path(tmp).glob("gpt-adapter-failures-*.jsonl"))
            row = json.loads(logs[0].read_text(encoding="utf-8").strip())

        self.assertEqual(result.adapter, "fallback")
        self.assertFalse(result.used_api)
        self.assertEqual(row["adapter"], "openai_responses")
        self.assertIn("TimeoutError", row["reason"])
        self.assertNotIn("sk-test-secret", json.dumps(row))

    def test_deepseek_adapter_posts_chat_completion_and_extracts_text(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(message="你好", intent="normal_chat")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "K, DeepSeek online."}}]}).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = engine.DeepSeekChatAdapter(
                api_key="sk-deepseek-secret",
                model="deepseek-v4-flash",
            ).generate(context)

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-deepseek-secret")
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["temperature"], 0.7)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertEqual(result.adapter, "deepseek_chat")
        self.assertTrue(result.used_api)
        self.assertIn("DeepSeek", result.text)

    def test_deepseek_prompt_uses_dialogue_brief_instead_of_raw_json(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(
            message="我现在有点乱",
            intent="normal_chat",
            recent_summary="project_assistant:AugSun 卡住",
            last_response="K，先稳住。",
            repeated_message=True,
            user_preferences=["少解释身份，多给判断"],
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "K，先停一下。"}}]}).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            engine.DeepSeekChatAdapter(api_key="sk-deepseek-secret", model="deepseek-v4-flash").generate(context)

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        system_text = payload["messages"][0]["content"]
        user_text = payload["messages"][1]["content"]
        self.assertIn("像微信里真正回话", system_text)
        self.assertIn("不要写括号动作", system_text)
        self.assertIn("用户原话：我现在有点乱", user_text)
        self.assertIn("最近上下文：project_assistant:AugSun 卡住", user_text)
        self.assertIn("上一句回复：K，先稳住。", user_text)
        self.assertIn("已重复发送：是", user_text)
        self.assertIn("风格校准：少解释身份，多给判断", user_text)
        self.assertNotIn("{", user_text)
        self.assertNotIn('"message"', user_text)

    def test_runtime_prompt_projects_voice_contract_without_source_names(self):
        engine = load_reply_engine()
        prompt = engine.dialogue_system_prompt()

        self.assertIn("关系姿态", prompt)
        self.assertIn("沉默规则", prompt)
        self.assertIn("有烟火气", prompt)
        self.assertIn("短句断刀", prompt)
        self.assertIn("低声收束", prompt)
        self.assertNotIn("巴拉莱卡", prompt)
        self.assertNotIn("叶文洁", prompt)
        self.assertNotIn("周迅", prompt)

    def test_dialogue_brief_includes_pressure_scenario(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(
            message="我有点累，但想继续",
            intent="normal_chat",
            pressure_scenario="用户疲惫",
        )

        brief = engine.build_dialogue_brief(context)

        self.assertIn("压力场景：用户疲惫", brief)

    def test_default_deepseek_adapter_accepts_base_url_and_runtime_knobs(self):
        engine = load_reply_engine()
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "sk-deepseek-secret",
                "VELA_DEEPSEEK_BASE_URL": "https://proxy.example/v1/",
                "VELA_DEEPSEEK_TIMEOUT_SECONDS": "999",
                "VELA_DEEPSEEK_THINKING": "enabled",
            },
            clear=True,
        ):
            adapter = engine.default_reply_adapter()

        self.assertEqual(adapter.name, "deepseek_chat")
        self.assertEqual(adapter.base_url, "https://proxy.example/v1/chat/completions")
        self.assertEqual(adapter.timeout, 45)
        self.assertEqual(adapter.thinking_mode, "enabled")
        self.assertEqual(engine.deepseek_thinking_mode({"VELA_DEEPSEEK_THINKING": "loud"}), "disabled")

    def test_deepseek_adapter_failure_logs_internally_and_falls_back(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(message="你好", intent="normal_chat")
        with tempfile.TemporaryDirectory() as tmp:
            adapter = engine.DeepSeekChatAdapter(
                api_key="sk-deepseek-secret",
                model="deepseek-v4-flash",
                log_dir=Path(tmp),
            )
            with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
                result = adapter.generate(context)
            logs = list(Path(tmp).glob("gpt-adapter-failures-*.jsonl"))
            row = json.loads(logs[0].read_text(encoding="utf-8").strip())

        self.assertEqual(result.adapter, "fallback")
        self.assertFalse(result.used_api)
        self.assertEqual(row["adapter"], "deepseek_chat")
        self.assertIn("TimeoutError", row["reason"])
        self.assertNotIn("sk-deepseek-secret", json.dumps(row))

    def test_context_payload_marks_wechat_short_reply_surface(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(message="你好", intent="normal_chat")

        payload = context.to_dict()

        self.assertEqual(payload["surface"], "wechat_short_reply")
        self.assertFalse(payload["tool_policy"]["allow_codex"])


if __name__ == "__main__":
    unittest.main()
