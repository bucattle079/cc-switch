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

    def test_deepseek_accepts_current_env_aliases_without_secret_leak(self):
        engine = load_reply_engine()
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "sk-deepseek-secret",
                "DEEPSEEK_MODEL": "deepseek-chat",
                "DEEPSEEK_BASE_URL": "https://proxy.example/v1",
            },
            clear=True,
        ):
            status = engine.reply_engine_status()
            adapter = engine.default_reply_adapter()

        self.assertEqual(status["adapter"], "deepseek_chat")
        self.assertEqual(status["model"], "deepseek-chat")
        self.assertEqual(adapter.name, "deepseek_chat")
        self.assertEqual(adapter.model, "deepseek-chat")
        self.assertEqual(adapter.base_url, "https://proxy.example/v1/chat/completions")
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

    def test_fallback_daily_info_is_not_generic_greeting(self):
        engine = load_reply_engine()
        adapter = engine.FallbackReplyAdapter()
        context = engine.ReplyContext(message="逻辑是什么呢", intent="daily_info")

        result = adapter.generate(context)

        self.assertIn("K", result.text)
        self.assertTrue(any(token in result.text for token in ["逻辑", "先看", "对象", "证据"]))
        self.assertNotIn("少菜单", result.text)
        self.assertNotIn("说目标", result.text)

    def test_fallback_project_reply_uses_strategic_memory_without_schema(self):
        engine = load_reply_engine()
        adapter = engine.FallbackReplyAdapter()
        context = engine.ReplyContext(
            message="继续 AugSun 项目",
            intent="project_assistant",
            strategic_memories=["战略候选（未确认，project_goal）：AugSun 长期目标是先跑通最小商业闭环"],
        )

        result = adapter.generate(context)

        self.assertIn("AugSun", result.text)
        self.assertIn("最小商业闭环", result.text)
        self.assertNotIn("project_goal", result.text)
        self.assertNotIn("战略候选", result.text)
        self.assertNotIn("未确认", result.text)

    def test_fallback_project_reply_does_not_invent_augsun_for_vela_project(self):
        engine = load_reply_engine()
        adapter = engine.FallbackReplyAdapter()
        context = engine.ReplyContext(message="继续 VELA 项目", intent="project_assistant")

        result = adapter.generate(context)

        self.assertNotIn("AugSun", result.text)
        self.assertIn("项目", result.text)

    def test_fallback_gratitude_stays_warm_not_pushy(self):
        engine = load_reply_engine()
        adapter = engine.FallbackReplyAdapter()
        context = engine.ReplyContext(message="谢谢你", intent="normal_chat")

        result = adapter.generate(context)

        self.assertIn("K", result.text)
        self.assertTrue(any(token in result.text for token in ["不用谢", "在", "交给我"]))
        self.assertNotIn("废话", result.text)
        self.assertNotIn("卡点", result.text)

    def test_pure_style_feedback_uses_style_feedback_not_misread_repair(self):
        engine = load_reply_engine()
        adapter = engine.FallbackReplyAdapter()
        context = engine.ReplyContext(
            message="你刚才太模板了",
            intent="style_feedback",
            response_mode="style_feedback",
        )

        result = adapter.generate(context)

        self.assertTrue(any(token in result.text for token in ["说人话", "先听懂", "真实意思", "结论", "重切"]))
        for internal in ["风格反馈候选", "行为偏好候选", "候选记录", "长期记忆", "已收进", "已校准"]:
            self.assertNotIn(internal, result.text)
        self.assertNotIn("你表达差", result.text)
        self.assertNotIn("我漏掉", result.text)

    def test_deep_analysis_variants_hide_raw_internal_layer_names(self):
        engine = load_reply_engine()
        variants = engine.FallbackReplyAdapter.DEEP_VARIANTS
        forbidden = ["router", "context", "reply engine", "fallback", "last_response", "adapter", "persona", "GPT"]

        self.assertGreaterEqual(len(variants), 3)
        for text in variants:
            with self.subTest(text=text):
                self.assertIn("K", text)
                self.assertTrue(any(token in text for token in ["根因", "验尸"]))
                self.assertTrue(any(token in text for token in ["修正路径", "下一步"]))
                for token in forbidden:
                    self.assertNotIn(token, text)

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
        self.assertEqual(result.source, "openai_failure:TimeoutError")
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

    def test_plain_greeting_dialogue_brief_does_not_inherit_codex_context(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(
            message="你好",
            intent="normal_chat",
            recent_summary="codex_task:/CODEX 修复状态",
            last_response="K，VELA · CODEX 产品判断摘要",
            user_preferences=["少菜单，多判断"],
        )

        brief = engine.build_dialogue_brief(context)

        self.assertIn("用户原话：你好", brief)
        self.assertIn("风格校准：少菜单，多判断", brief)
        self.assertNotIn("codex_task", brief.lower())
        self.assertNotIn("CODEX 产品判断摘要", brief)

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

    def test_dialogue_brief_includes_need_interpretation_and_strategic_memory(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(
            message="你太像机器人了",
            intent="style_feedback",
            need_interpretation="用户需要确认 VELA 能被反馈触动，而不是继续模板化。",
            response_mode="relationship_repair",
            human_tone_vector={
                "warmth_level": 4,
                "directness_level": 5,
                "strategic_depth": 2,
                "emotional_presence": 5,
                "clarification_need": 4,
                "memory_reference_need": 3,
            },
            persona_skeleton=["Meaning Decoder", "Witty Correction"],
            strategic_memories=["AugSun 长期目标是先跑通最小商业闭环。"],
        )

        brief = engine.build_dialogue_brief(context)

        self.assertIn("背面需求：用户需要确认 VELA 能被反馈触动", brief)
        self.assertIn("回应模式：relationship_repair", brief)
        self.assertIn("语气向量：warmth=4, directness=5, strategic_depth=2", brief)
        self.assertIn("人格骨架：Meaning Decoder / Witty Correction", brief)
        self.assertIn("长期记忆：AugSun 长期目标是先跑通最小商业闭环。", brief)
        self.assertNotIn("{", brief)
        self.assertNotIn("need_interpretation", brief)

    def test_dialogue_brief_includes_behavior_pack_fields(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(
            message="今天市场是不是能加仓",
            intent="market_brief",
            need_interpretation="用户想判断今天金融市场是否存在风险或机会，而不是看新闻列表。",
            response_mode="market_brief",
            persona_skeleton=["Evidence Gate", "Boundary Engine"],
            active_persona_capabilities=["Evidence Gate", "Boundary Engine"],
            detected_user_state="加仓前的风险焦虑",
            inferred_hidden_need="需要区分事实、推断和不确定后再判断仓位。",
            response_behavior_mode="market_brief",
            should_clarify=False,
            should_push_back=True,
            should_use_evidence_gate=True,
            should_reference_memory=False,
            tone_adjustment_reason="投资相关，先证据后判断，禁止空泛鼓励。",
        )

        brief = engine.build_dialogue_brief(context)

        self.assertIn("active_persona_capabilities：Evidence Gate / Boundary Engine", brief)
        self.assertIn("detected_user_state：加仓前的风险焦虑", brief)
        self.assertIn("inferred_hidden_need：需要区分事实、推断和不确定", brief)
        self.assertIn("response_behavior_mode：market_brief", brief)
        self.assertIn("should_clarify：否", brief)
        self.assertIn("should_push_back：是", brief)
        self.assertIn("should_use_evidence_gate：是", brief)
        self.assertIn("should_reference_memory：否", brief)
        self.assertIn("tone_adjustment_reason：投资相关", brief)
        self.assertNotIn("{", brief)

    def test_runtime_prompt_projects_five_capabilities_without_source_personas(self):
        engine = load_reply_engine()

        prompt = engine.dialogue_system_prompt()

        for capability in [
            "Evidence Gate",
            "Meaning Decoder",
            "Identity Core",
            "Boundary Engine",
            "Witty Correction",
        ]:
            self.assertIn(capability, prompt)

        forbidden = [
            "Dana Scully",
            "Scully",
            "Louise Banks",
            "草薙素子",
            "Jane Eyre",
            "Elizabeth Bennet",
            "X-Files",
            "Arrival",
            "Ghost in the Shell",
            "Pride and Prejudice",
        ]
        for token in forbidden:
            self.assertNotIn(token, prompt)

    def test_dialogue_prompt_and_brief_are_not_character_roleplay(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(
            message="你没懂我",
            intent="style_feedback",
            need_interpretation="用户需要 VELA 承认理解偏差并快速重切问题。",
            response_mode="relationship_repair",
        )

        system_prompt = engine.dialogue_system_prompt()
        brief = engine.build_dialogue_brief(context)
        combined = system_prompt + "\n" + brief

        self.assertIn("mechanism_only", combined)
        self.assertIn("relationship_repair", combined)
        self.assertNotIn("叶文洁", combined)
        self.assertNotIn("三体", combined)
        self.assertNotIn("我是叶文洁", combined)
        self.assertNotIn("请扮演", combined)
        self.assertNotIn("三体原文", combined)
        self.assertNotIn("原著台词：", combined)

    def test_deep_analysis_brief_protects_user_from_blame_shift(self):
        engine = load_reply_engine()
        context = engine.ReplyContext(
            message="地狱验尸一下 VELA 为什么不智能",
            intent="deep_analysis",
            need_interpretation="用户需要根因、风险和最短修正路径，并判断是否值得沉淀为经验。",
        )

        brief = engine.build_dialogue_brief(context)

        self.assertIn("不要把系统问题简单归咎于用户", brief)
        self.assertIn("不要声称长期记忆为空", brief)
        self.assertIn("行为修正路径", brief)

    def test_persona_profile_distills_companion_core_traits(self):
        engine = load_reply_engine()
        profile = engine.VELA_PERSONA_PROFILE

        for token in ["长期主义", "保护", "稳定忠诚", "执行压迫感", "锋利幽默"]:
            self.assertIn(token, profile)

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

    def test_default_deepseek_adapter_uses_foreground_lane_budgets(self):
        engine = load_reply_engine()
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "sk-deepseek-secret",
                "VELA_DEEPSEEK_TIMEOUT_SECONDS": "45",
            },
            clear=True,
        ):
            fast = engine.default_reply_adapter(foreground_lane="fast")
            deep = engine.default_reply_adapter(foreground_lane="deep")

        self.assertEqual(fast.name, "deepseek_chat")
        self.assertLessEqual(fast.timeout, 2)
        self.assertEqual(deep.name, "deepseek_chat")
        self.assertLessEqual(deep.timeout, 8)

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
        self.assertEqual(result.source, "deepseek_failure:TimeoutError")
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
