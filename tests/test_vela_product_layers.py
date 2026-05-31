import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"
PRODUCT = TOOLS / "vela_product_layers.py"
REPLY_ENGINE = TOOLS / "vela_reply_engine.py"


def load_product_module():
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("vela_product_layers", PRODUCT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_module(path: Path, name: str):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaProductLayerTests(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict("os.environ", {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_layered_response_exposes_fallback_adapter_status(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response("你好", intent="normal_chat", log_dir=Path(tmp))

        self.assertEqual(result.reply_adapter, "fallback")
        self.assertFalse(result.real_gpt_enabled)

    def test_normal_project_and_deep_can_use_real_gpt_adapter(self):
        product = load_product_module()
        reply_engine = load_module(REPLY_ENGINE, "vela_reply_engine")

        class FakeGPTAdapter(reply_engine.ReplyAdapter):
            name = "openai_responses"

            def generate(self, context):
                return reply_engine.ReplyEngineResult(
                    text=f"K，GPT 接管：{context.intent} / {context.surface}",
                    source="fake",
                    used_api=True,
                    adapter=self.name,
                )

        with tempfile.TemporaryDirectory() as tmp:
            normal = product.run_layered_response(
                "你好",
                intent="normal_chat",
                log_dir=Path(tmp),
                reply_adapter=FakeGPTAdapter(),
            )
            project = product.run_layered_response(
                "继续 AugSun 项目",
                intent="project_assistant",
                log_dir=Path(tmp),
                reply_adapter=FakeGPTAdapter(),
            )
            deep = product.run_layered_response(
                "地狱验尸一下 VELA 为什么不智能",
                intent="deep_analysis",
                log_dir=Path(tmp),
                reply_adapter=FakeGPTAdapter(),
            )

        self.assertTrue(normal.real_gpt_enabled)
        self.assertTrue(project.real_gpt_enabled)
        self.assertTrue(deep.real_gpt_enabled)
        self.assertIn("GPT 接管：normal_chat", normal.text)
        self.assertIn("GPT 接管：project_assistant", project.text)
        self.assertIn("GPT 接管：deep_analysis", deep.text)

    def test_deepseek_adapter_is_reported_as_real_gpt(self):
        product = load_product_module()
        reply_engine = load_module(REPLY_ENGINE, "vela_reply_engine")

        class FakeDeepSeekAdapter(reply_engine.ReplyAdapter):
            name = "deepseek_chat"

            def generate(self, context):
                return reply_engine.ReplyEngineResult(
                    text="K, DeepSeek online.",
                    source="fake",
                    used_api=True,
                    adapter=self.name,
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response(
                "hello",
                intent="normal_chat",
                log_dir=Path(tmp),
                reply_adapter=FakeDeepSeekAdapter(),
            )

        self.assertEqual(result.reply_adapter, "deepseek_chat")
        self.assertTrue(result.real_gpt_enabled)

    def test_non_codex_lanes_select_deepseek_without_weather_api(self):
        product = load_product_module()
        env = {"DEEPSEEK_API_KEY": "sk-test-secret"}

        for intent in [
            "normal_chat",
            "daily_info",
            "weather_query",
            "market_brief",
            "market_refresh",
            "freshness_status",
            "world_brief",
            "project_assistant",
            "deep_analysis",
        ]:
            with self.subTest(intent=intent):
                selection = product.select_model_and_tools(intent, env=env)
                self.assertEqual(selection.model_adapter, "deepseek_chat")
                self.assertFalse(selection.allow_codex)

        weather = product.select_model_and_tools("weather_query", env=env)
        self.assertFalse(weather.allow_retrieval)
        self.assertIn("no external weather API", weather.reason)

        codex = product.select_model_and_tools("codex_task", env=env)
        self.assertEqual(codex.model_adapter, "codex_bridge")
        self.assertTrue(codex.allow_codex)

    def test_weather_uses_reply_engine_context_not_weather_api(self):
        product = load_product_module()
        reply_engine = load_module(REPLY_ENGINE, "vela_reply_engine")
        captured = {}

        class FakeDeepSeekAdapter(reply_engine.ReplyAdapter):
            name = "deepseek_chat"

            def generate(self, context):
                captured["context"] = context
                return reply_engine.ReplyEngineResult(
                    text="K，天气不接外部 API。我按风险判断：带伞，给行程留余量。",
                    source="fake",
                    used_api=True,
                    adapter=self.name,
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response(
                "明天晋江天气",
                intent="weather_query",
                log_dir=Path(tmp),
                supporting_context="天气不调用外部 API；不要编实时温度。",
                reply_adapter=FakeDeepSeekAdapter(),
            )

        self.assertEqual(result.reply_adapter, "deepseek_chat")
        self.assertTrue(result.real_gpt_enabled)
        self.assertFalse(result.used_retrieval)
        self.assertIn("外部 API", captured["context"].supporting_context)
        self.assertIn("天气不接外部 API", result.text)
        self.assertNotIn("weather_query", result.text)

    def test_normal_chat_uses_reply_engine_not_static_market_codex_menu(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response("你好", intent="normal_chat", log_dir=Path(tmp))

        self.assertEqual(result.intent, "normal_chat")
        self.assertFalse(result.used_codex)
        self.assertFalse(result.used_retrieval)
        self.assertIn("K", result.text)
        self.assertNotIn("要看盘，说 A股、美股或韩国", result.text)
        self.assertNotIn("要动 Codex，用 /CODEX", result.text)
        self.assertNotIn("Market & World Briefing", result.text)

    def test_normal_chat_guard_blocks_codex_status_leak(self):
        product = load_product_module()

        cleaned = product.guard_layered_output(
            "K，Codex 那边收工了。结论就一句话：项目已标记完成。",
            intent="normal_chat",
            used_codex=False,
            used_retrieval=False,
        )

        self.assertIn("K", cleaned)
        self.assertNotIn("Codex", cleaned)
        self.assertNotIn("项目已标记完成", cleaned)

    def test_normal_chat_guard_allows_codex_as_tool_boundary(self):
        product = load_product_module()

        cleaned = product.guard_layered_output(
            "K，AugSun 这条线不断。先判产品方向，再派 Codex 做手上的活。",
            intent="normal_chat",
            used_codex=False,
            used_retrieval=False,
        )

        self.assertIn("AugSun", cleaned)
        self.assertIn("Codex", cleaned)

    def test_repeated_normal_chat_rotates_away_from_last_response(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            first = product.run_layered_response("你好 VELA", intent="normal_chat", log_dir=Path(tmp))
            second = product.run_layered_response("你好 VELA", intent="normal_chat", log_dir=Path(tmp))

        self.assertNotEqual(first.text, second.text)
        self.assertIn("K", second.text)
        self.assertNotIn("要看盘，说 A股、美股或韩国", second.text)

    def test_adjacent_greetings_do_not_copy_same_sentence(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            first = product.run_layered_response("你好", intent="normal_chat", log_dir=Path(tmp))
            second = product.run_layered_response("你好 VELA", intent="normal_chat", log_dir=Path(tmp))

        self.assertNotEqual(first.text, second.text)
        self.assertIn("K", first.text)
        self.assertIn("K", second.text)
        self.assertLess(len(first.text), 160)
        self.assertLess(len(second.text), 160)

    def test_style_feedback_changes_next_normal_reply(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            product.run_layered_response("你刚才太像机器人了", intent="memory_related", log_dir=Path(tmp))
            next_reply = product.run_layered_response("你好", intent="normal_chat", log_dir=Path(tmp))

        self.assertIn("K", next_reply.text)
        self.assertTrue(any(token in next_reply.text for token in ["少菜单", "直接给判断", "机械味", "不像提示牌"]))
        self.assertNotIn("要看盘，说 A股、美股或韩国", next_reply.text)

    def test_continue_uses_recent_context_instead_of_menu(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            product.run_layered_response("继续 AugSun 项目，下一步怎么推", intent="project_assistant", log_dir=Path(tmp))
            reply = product.run_layered_response("继续", intent="normal_chat", log_dir=Path(tmp))

        self.assertIn("K", reply.text)
        self.assertTrue(any(token in reply.text for token in ["AugSun", "项目", "上一刀", "上一轮"]))
        self.assertNotIn("要看盘，说 A股、美股或韩国", reply.text)

    def test_persona_profile_distills_required_traits_without_source_names(self):
        reply_engine = load_module(REPLY_ENGINE, "vela_reply_engine")
        profile = reply_engine.VELA_PERSONA_PROFILE

        self.assertIn("长期主义", profile)
        self.assertIn("保护性理性", profile)
        self.assertIn("生活感", profile)
        self.assertNotIn("叶文洁", profile)
        self.assertNotIn("毛利兰", profile)

    def test_context_builder_reads_last_response_and_tool_policy(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            product.record_interaction(
                message="你好 VELA",
                intent="normal_chat",
                response_text="上一条 VELA 回复",
                used_codex=False,
                used_retrieval=False,
                log_dir=Path(tmp),
            )
            context = product.build_reply_context(
                "你好 VELA",
                intent="normal_chat",
                log_dir=Path(tmp),
            )

        self.assertEqual(context.last_response, "上一条 VELA 回复")
        self.assertTrue(context.repeated_message)
        self.assertFalse(context.tool_policy.allow_market)
        self.assertFalse(context.tool_policy.allow_codex)

    def test_reply_context_marks_pressure_scenario_for_fatigue_and_chaos(self):
        product = load_product_module()

        tired = product.build_reply_context("我有点累，但今天还想继续", intent="normal_chat")
        chaotic = product.build_reply_context("VELA，我现在有点乱", intent="normal_chat")
        style = product.build_reply_context("你刚才还是像机器", intent="memory_related")

        self.assertEqual(tired.pressure_scenario, "用户疲惫")
        self.assertEqual(chaotic.pressure_scenario, "含糊求助")
        self.assertEqual(style.pressure_scenario, "机械纠偏")

    def test_need_interpretation_maps_surface_intent_to_hidden_need(self):
        product = load_product_module()

        self.assertIn(
            "被反馈触动",
            product.interpret_user_need("你太像机器人了", "style_feedback"),
        )
        self.assertIn(
            "无缝接续项目",
            product.interpret_user_need("CODEX/", "codex_task"),
        )
        self.assertIn(
            "风险或机会",
            product.interpret_user_need("今天的资讯", "market_brief"),
        )
        self.assertIn(
            "根因",
            product.interpret_user_need("地狱验尸一下 VELA 为什么不智能", "deep_analysis"),
        )

    def test_humanization_interpretation_maps_relationship_repair(self):
        product = load_product_module()

        interpretation = product.interpret_need("你没懂我", "style_feedback")

        self.assertEqual(interpretation.response_mode, "relationship_repair")
        self.assertIn("偏差", interpretation.implied_need)
        self.assertTrue(interpretation.should_clarify)
        self.assertGreaterEqual(interpretation.human_tone_vector.emotional_presence, 4)
        self.assertGreaterEqual(interpretation.human_tone_vector.directness_level, 4)

    def test_humanization_interpretation_maps_quiet_support(self):
        product = load_product_module()

        interpretation = product.interpret_need("脑子发懵", "normal_chat")

        self.assertEqual(interpretation.response_mode, "quiet_support")
        self.assertIn("低负担", interpretation.preferred_reply_shape)
        self.assertLessEqual(interpretation.human_tone_vector.strategic_depth, 2)
        self.assertGreaterEqual(interpretation.human_tone_vector.warmth_level, 4)

    def test_humanization_interpretation_maps_project_operator(self):
        product = load_product_module()

        interpretation = product.interpret_need("继续 AugSun 项目", "project_assistant")

        self.assertEqual(interpretation.response_mode, "project_operator")
        self.assertIn("目标", interpretation.literal_need)
        self.assertGreaterEqual(interpretation.human_tone_vector.strategic_depth, 4)

    def test_humanization_layer_does_not_pollute_hard_tool_lanes(self):
        product = load_product_module()

        market = product.interpret_need("今天的资讯", "market_brief")
        weather = product.interpret_need("明天晋江天气", "weather_query")
        codex = product.interpret_need("CODEX/", "codex_task")

        self.assertEqual(market.response_mode, "market_brief")
        self.assertEqual(weather.response_mode, "daily_companion")
        self.assertEqual(codex.response_mode, "project_operator")
        self.assertFalse(market.should_clarify)
        self.assertFalse(weather.should_clarify)

    def test_humanization_distillation_contract_is_mechanism_only(self):
        product = load_product_module()

        prompt = product.humanization_distillation_prompt()

        self.assertIn("mechanism_only", prompt)
        self.assertIn("daily_companion", prompt)
        self.assertIn("relationship_repair", prompt)
        self.assertNotIn("叶文洁", prompt)
        self.assertNotIn("三体", prompt)
        self.assertNotIn("扮演", prompt)
        self.assertNotIn("台词", prompt)

    def test_persona_skeleton_distills_five_capabilities_without_source_quotes(self):
        product = load_product_module()

        rules = product.persona_skeleton_rules()
        text = "\n".join(rules)

        for capability in [
            "Evidence Gate",
            "Meaning Decoder",
            "Identity Core",
            "Boundary Engine",
            "Witty Correction",
        ]:
            self.assertIn(capability, text)

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
            self.assertNotIn(token, text)

    def test_persona_skeleton_signals_follow_need_shape(self):
        product = load_product_module()

        repair = product.interpret_need("你没懂我", "style_feedback")
        weather = product.interpret_need("明天晋江天气", "weather_query")
        project = product.interpret_need("广告烧钱有点上头，继续冲吗", "project_assistant")

        self.assertIn("Meaning Decoder", repair.persona_skeleton)
        self.assertIn("Witty Correction", repair.persona_skeleton)
        self.assertIn("Evidence Gate", weather.persona_skeleton)
        self.assertIn("Boundary Engine", weather.persona_skeleton)
        self.assertIn("Boundary Engine", project.persona_skeleton)
        self.assertIn("Identity Core", project.persona_skeleton)

    def test_context_builder_reads_need_interpretation_and_strategic_memory(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            product.record_strategic_memory(
                "AugSun 长期目标是先跑通最小商业闭环。",
                memory_type="project_goal",
                confirmed_by_user=True,
                log_dir=Path(tmp),
            )

            context = product.build_reply_context(
                "继续 AugSun 项目",
                intent="project_assistant",
                log_dir=Path(tmp),
            )

        self.assertIn("项目", context.need_interpretation)
        self.assertEqual(context.response_mode, "project_operator")
        self.assertEqual(context.human_tone_vector["strategic_depth"], 5)
        self.assertIn("AugSun 长期目标", context.strategic_memories[0])
        self.assertIn("need_interpretation", context.to_dict())
        self.assertIn("response_mode", context.to_dict())
        self.assertIn("human_tone_vector", context.to_dict())
        self.assertIn("persona_skeleton", context.to_dict())
        self.assertIn("Boundary Engine", context.persona_skeleton)
        self.assertIn("strategic_memories", context.to_dict())

    def test_relationship_repair_reply_is_not_ordinary_apology(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response("你没懂我", intent="style_feedback", log_dir=Path(tmp))

            row = json.loads(next(Path(tmp).glob("memory-candidates-*.jsonl")).read_text(encoding="utf-8").strip())

        self.assertIn("K", result.text)
        self.assertIn("偏", result.text)
        self.assertTrue(any(token in result.text for token in ["重切", "补一句", "漏掉"]))
        self.assertNotIn("抱歉", result.text)
        self.assertEqual(row["classification"], "relationship_repair")
        self.assertEqual(row["response_mode"], "relationship_repair")
        self.assertFalse(row["confirmed"])

    def test_quiet_support_reply_is_short_and_low_burden(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response("脑子发懵", intent="normal_chat", log_dir=Path(tmp))

        self.assertIn("K", result.text)
        self.assertLess(len(result.text), 90)
        self.assertTrue(any(token in result.text for token in ["停", "一口气", "一个点", "不用整理"]))
        self.assertNotIn("菜单", result.text)
        self.assertFalse(result.memory_candidate)

    def test_fallback_reply_adapter_has_natural_variants(self):
        reply_engine = load_module(REPLY_ENGINE, "vela_reply_engine")
        adapter = reply_engine.FallbackReplyAdapter()
        variants = adapter.NORMAL_VARIANTS

        self.assertGreaterEqual(len(variants), 3)
        self.assertLessEqual(len(variants), 8)
        self.assertTrue(any("不" in item and "菜单" in item for item in variants))
        self.assertTrue(any("噪音" in item or "混乱" in item for item in variants))

    def test_calibrated_feedback_variants_show_change_without_self_certifying(self):
        reply_engine = load_module(REPLY_ENGINE, "vela_reply_engine")
        variants = (
            reply_engine.FallbackReplyAdapter.CALIBRATED_NORMAL_VARIANTS
            + reply_engine.FallbackReplyAdapter.CALIBRATED_CONTINUE_VARIANTS
        )

        for text in variants:
            self.assertNotIn("机械味已压下去", text)
            self.assertNotIn("收到上一个校准", text)
            self.assertNotIn("这次不像提示牌", text)
            self.assertNotIn("我已校准", text)
            self.assertNotIn("已校准", text)

    def test_persona_renderer_keeps_facts_and_applies_vela_voice(self):
        product = load_product_module()

        packet = product.AnalysisPacket(
            intent="project_assistant",
            facts=["当前目标：把 VELA 从聊天壳子升级为战略参谋"],
            judgment="先收束 router、persona、guardrail、learning loop 四个接口。",
            risks=["不要把 Codex 当普通聊天大脑"],
            next_actions=["先补验收测试，再接入薄管线"],
            confidence="medium",
        )

        reply = product.render_vela_persona(packet)

        self.assertIn("当前目标：把 VELA 从聊天壳子升级为战略参谋", reply)
        self.assertIn("判断：先收束 router、persona、guardrail、learning loop 四个接口。", reply)
        self.assertIn("下一步：先补验收测试，再接入薄管线", reply)
        self.assertIn("别把好运气请来当部门主管", reply)
        self.assertNotIn("debug", reply.lower())

    def test_guardrail_removes_engineering_noise_before_wechat(self):
        product = load_product_module()

        text = product.guard_wechat_output(
            "debug raw payload at C:\\Users\\Admin\\Desktop\\CC-WECHAT\\x.json\nnot implemented"
        )

        self.assertNotIn("debug", text.lower())
        self.assertNotIn("raw payload", text.lower())
        self.assertNotIn("C:\\", text)
        self.assertNotIn("not implemented", text.lower())
        self.assertNotIn("内部诊断", text)
        self.assertIn("K", text)

    def test_codex_summary_hides_runtime_metadata_before_wechat(self):
        product = load_product_module()

        result = product.run_layered_response(
            "Codex 状态查询",
            intent="codex_task",
            codex_summary=(
                "VELA · CODEX 最近完成 项目: VELA GPT 接入 "
                "工作区: C:\\Users\\Admin\\Desktop\\CC-WECHAT "
                "完成: 05-25 20:52 最后结论 目标已标记完成。"
                "用量 `106,285 tokens`，耗时约 `8 分 38 秒`。"
                "sandbox danger-full-access | approval never | model gpt-5 "
                "截图已生成。 文本备份已保存。"
            ),
        )
        text = result.text

        self.assertIn("目标已标记完成", text)
        self.assertIn("截图已生成", text)
        self.assertNotIn("token", text.lower())
        self.assertNotIn("sandbox", text.lower())
        self.assertNotIn("approval", text.lower())
        self.assertNotIn("gpt-5", text.lower())
        self.assertNotIn("C:\\", text)

    def test_codex_summary_hides_markdown_links_to_local_paths(self):
        product = load_product_module()

        result = product.run_layered_response(
            "Codex 状态查询",
            intent="codex_task",
            codex_summary=(
                "主要改动落在 [tools/vela_router.py](C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py)、"
                "[tools/vela_reply_engine.py](C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_reply_engine.py)。"
            ),
        )
        text = result.text

        self.assertIn("tools/vela_router.py", text)
        self.assertNotIn("C:/Users", text)
        self.assertNotIn("Desktop/CC-WECHAT", text)
        self.assertNotIn("](", text)

    def test_reply_quality_record_is_structured_jsonl(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = product.record_reply_quality(
                conversation_type="market_brief",
                user_goal="判断A股、美股、韩国风险",
                response_text="短判断",
                used_cache=True,
                used_retrieval=False,
                used_codex=False,
                quality_flags=["clear_conclusion"],
                issues=[],
                log_dir=Path(tmp),
            )

            row = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(row["conversation_type"], "market_brief")
        self.assertEqual(row["response_length"], "short")
        self.assertTrue(row["used_cache"])
        self.assertFalse(row["used_codex"])
        self.assertIn("clear_conclusion", row["quality_flags"])

    def test_memory_candidate_requires_safety_classification(self):
        product = load_product_module()

        candidate = product.build_memory_candidate("记住：以后市场分析默认先看A股、美股、韩国")

        self.assertEqual(candidate["level"], "Preference Candidate")
        self.assertEqual(candidate["classification"], "market_focus")
        self.assertFalse(candidate["sensitive"])
        self.assertIn("A股", candidate["summary"])

    def test_product_constants_preserve_market_weights_and_confirmed_schedule(self):
        product = load_product_module()

        self.assertEqual(product.MARKET_WEIGHTS["A股"], 35)
        self.assertEqual(product.MARKET_WEIGHTS["美股"], 30)
        self.assertEqual(product.CONFIRMED_CACHE_SLOTS, ["09:00", "12:30", "17:00"])
        self.assertNotIn("10:00", product.CONFIRMED_CACHE_SLOTS)
        self.assertNotIn("13:00", product.CONFIRMED_CACHE_SLOTS)
        self.assertNotIn("16:00", product.CONFIRMED_CACHE_SLOTS)

    def test_style_feedback_candidate_is_persisted_without_confirming_memory(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = product.record_memory_candidate(
                "你刚才太像机器人了",
                log_dir=Path(tmp),
            )

            row = json.loads(candidate_path.read_text(encoding="utf-8").strip())

        self.assertEqual(row["level"], "Preference Candidate")
        self.assertEqual(row["classification"], "style_feedback")
        self.assertFalse(row["confirmed"])
        self.assertFalse(row["sensitive"])
        self.assertIn("机器人", row["summary"])
        self.assertIn("被反馈触动", row["need_interpretation"])

    def test_layered_pipeline_records_quality_and_hides_engineering_noise(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response(
                "继续 AugSun 项目，下一步怎么推",
                intent="project_assistant",
                log_dir=Path(tmp),
            )

            quality_rows = list(Path(tmp).glob("reply-quality-*.jsonl"))
            row = json.loads(quality_rows[0].read_text(encoding="utf-8").strip())

        self.assertEqual(result.intent, "project_assistant")
        self.assertFalse(result.used_codex)
        self.assertFalse(result.used_retrieval)
        self.assertIn("判断：", result.text)
        self.assertIn("下一步：", result.text)
        self.assertNotIn("raw payload", result.text.lower())
        self.assertEqual(row["intent"], "project_assistant")
        self.assertFalse(row["used_codex"])
        self.assertFalse(row["used_retrieval"])
        self.assertIn("need_interpretation", row)
        self.assertNotIn("need_interpretation", result.text)
        self.assertNotIn("背面需求", result.text)

    def test_deep_analysis_surfaces_experience_memory_judgement(self):
        product = load_product_module()

        result = product.run_layered_response(
            "地狱验尸一下 VELA 为什么不智能",
            intent="deep_analysis",
        )

        self.assertIn("经验沉淀判断", result.text)
        self.assertIn("最短修正路径", result.text)

    def test_session_notes_are_persisted_locally(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = product.record_session_note(
                "你好 VELA",
                "normal_chat",
                "短回复",
                log_dir=Path(tmp),
            )
            product.run_layered_response("你好 VELA", intent="normal_chat", log_dir=Path(tmp))

            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            session_files = list(Path(tmp).glob("session-notes-*.jsonl"))

        self.assertEqual(rows[0]["level"], "Session Notes")
        self.assertEqual(rows[0]["intent"], "normal_chat")
        self.assertTrue(rows[0]["persistent"])
        self.assertTrue(session_files)

    def test_confirmed_preferences_require_user_confirmation(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                product.record_confirmed_preference(
                    "以后市场分析默认先看 A股 / 美股 / 韩国",
                    confirmed_by_user=False,
                    log_dir=Path(tmp),
                )

            path = product.record_confirmed_preference(
                "以后市场分析默认先看 A股 / 美股 / 韩国",
                confirmed_by_user=True,
                log_dir=Path(tmp),
            )
            row = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(row["level"], "Confirmed User Preference")
        self.assertTrue(row["confirmed"])

    def test_strategic_memory_requires_confirmation_and_explicit_type(self):
        product = load_product_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = product.record_strategic_memory(
                "VELA 长期方向是战略参谋，不是客服。",
                memory_type="persona_direction",
                confirmed_by_user=True,
                log_dir=Path(tmp),
            )
            row = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(row["level"], "Strategic Memory")
        self.assertEqual(row["memory_type"], "persona_direction")
        self.assertTrue(row["confirmed"])

    def test_intent_guardrail_blocks_wrong_tool_surface(self):
        product = load_product_module()

        cleaned = product.guard_layered_output(
            "Market & World Briefing\nraw payload",
            intent="normal_chat",
            used_codex=False,
            used_retrieval=True,
        )

        self.assertNotIn("Market & World Briefing", cleaned)
        self.assertNotIn("raw payload", cleaned.lower())
        self.assertIn("不需要市场扫描", cleaned)

    def test_intent_guardrail_rewrites_robotic_menu_reply(self):
        product = load_product_module()

        cleaned = product.guard_layered_output(
            "在。今天先校准，不拉资讯。要看盘，说 A股、美股或韩国；要动 Codex，用 /CODEX。",
            intent="normal_chat",
            used_codex=False,
            used_retrieval=False,
        )

        self.assertNotIn("要看盘，说 A股、美股或韩国", cleaned)
        self.assertNotIn("要动 Codex，用 /CODEX", cleaned)
        self.assertIn("菜单", cleaned)

    def test_dialogue_guardrail_removes_performance_markers(self):
        product = load_product_module()

        cleaned = product.guard_layered_output(
            "（淡淡扫一眼）作为 VELA，我将首先分析你的问题。其次，我们可以开始。",
            intent="normal_chat",
            used_codex=False,
            used_retrieval=False,
        )

        self.assertIn("K", cleaned)
        self.assertNotIn("淡淡扫一眼", cleaned)
        self.assertNotIn("作为 VELA", cleaned)
        self.assertNotIn("我将", cleaned)
        self.assertNotIn("首先", cleaned)
        self.assertNotIn("其次", cleaned)

    def test_layered_quality_log_records_voice_guardrail_issues(self):
        product = load_product_module()
        reply_engine = load_module(REPLY_ENGINE, "vela_reply_engine")

        class StageyAdapter(reply_engine.ReplyAdapter):
            name = "deepseek_chat"

            def generate(self, context):
                return reply_engine.ReplyEngineResult(
                    text="（轻轻一笑）作为 VELA，我将首先给你一个完整方案。",
                    source="fake",
                    used_api=True,
                    adapter=self.name,
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response(
                "我有点乱",
                intent="normal_chat",
                log_dir=Path(tmp),
                reply_adapter=StageyAdapter(),
            )
            quality_path = next(Path(tmp).glob("reply-quality-*.jsonl"))
            quality_row = json.loads(quality_path.read_text(encoding="utf-8"))

        self.assertNotIn("轻轻一笑", result.text)
        self.assertNotIn("作为 VELA", result.text)
        self.assertIn("stage_direction", quality_row["issues"])
        self.assertIn("forbidden_phrase:作为 VELA", quality_row["issues"])


if __name__ == "__main__":
    unittest.main()
