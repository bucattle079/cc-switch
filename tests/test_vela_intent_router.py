import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"
ROUTER = TOOLS / "vela_router.py"
MARKET = TOOLS / "vela_market_briefing.py"
PRODUCT = TOOLS / "vela_product_layers.py"


def load_module(path: Path, name: str):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaIntentRouterTests(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict("os.environ", {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_hello_vela_is_normal_chat_not_market(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("你好 VELA")

        self.assertEqual(intent.name, "normal_chat")
        self.assertFalse(intent.market_allowed)
        self.assertFalse(intent.codex_allowed)
        reply = router.reply_for("你好 VELA")
        self.assertNotIn("要看盘，说 A股、美股或韩国", reply)
        self.assertNotIn("Market & World Briefing", reply)

    def test_plain_vela_is_interaction_opening(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("VELA")

        self.assertEqual(intent.name, "normal_chat")
        reply = router.reply_for("VELA")
        self.assertNotIn("要看盘，说 A股、美股或韩国", reply)
        self.assertLess(len(reply), 120)

    def test_a_share_question_routes_to_market_brief(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("今天A股怎么看")

        self.assertEqual(intent.name, "market_brief")
        self.assertTrue(intent.market_allowed)
        self.assertIn("china_a", intent.focus_tags)

    def test_general_market_question_routes_to_market_brief(self):
        router = load_module(ROUTER, "vela_router")

        for text in ["今天的市场如何", "市场如何"]:
            intent = router.classify_intent(text)

            self.assertEqual(intent.name, "market_brief", text)
            self.assertTrue(intent.market_allowed)

    def test_weather_query_routes_to_weather_lane_not_chat(self):
        router = load_module(ROUTER, "vela_router")

        for text in ["明天晋江天气", "今天纽约冷吗"]:
            intent = router.classify_intent(text)

            self.assertEqual(intent.name, "weather_query", text)
            self.assertIn("weather", intent.focus_tags)
            self.assertFalse(intent.codex_allowed)
            self.assertFalse(intent.market_allowed)

        decision = router.route_decision("明天晋江天气")
        self.assertEqual(decision.intent, "weather_query")
        self.assertFalse(decision.needs_retrieval)
        self.assertFalse(decision.needs_codex)

    def test_weather_reply_uses_local_boundary_adapter_without_weather_api(self):
        router = load_module(ROUTER, "vela_router")

        with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K model weather")) as run:
            reply = router.reply_for("明天晋江天气")

        self.assertEqual(reply, "K model weather")
        self.assertEqual(run.call_args.kwargs["intent"], "weather_query")
        self.assertIn("实时源：未接入", run.call_args.kwargs["supporting_context"])
        self.assertIn("不编实时温度", run.call_args.kwargs["supporting_context"])
        self.assertIsInstance(run.call_args.kwargs["reply_adapter"], router.FallbackReplyAdapter)

    def test_now_weather_can_use_deepseek_current_info_lane(self):
        router = load_module(ROUTER, "vela_router")

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test-secret"}, clear=True):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K model current weather")) as run:
                reply = router.reply_for("现在纽约冷吗")

        self.assertEqual(reply, "K model current weather")
        self.assertEqual(run.call_args.kwargs["intent"], "weather_query")
        self.assertIn("实时源：未接入", run.call_args.kwargs["supporting_context"])
        self.assertIsNone(run.call_args.kwargs["reply_adapter"])

    def test_market_reply_uses_local_boundary_adapter_with_cache_context(self):
        router = load_module(ROUTER, "vela_router")

        with patch.object(router, "render_cached_market_reply", return_value="缓存市场判断"):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K model market")) as run:
                reply = router.reply_for("今天的资讯")

        self.assertEqual(reply, "K model market")
        self.assertEqual(run.call_args.kwargs["intent"], "market_brief")
        self.assertIn("缓存市场判断", run.call_args.kwargs["supporting_context"])
        self.assertIsInstance(run.call_args.kwargs["reply_adapter"], router.FallbackReplyAdapter)

    def test_deepseek_env_does_not_take_over_hard_status_entry_lanes(self):
        router = load_module(ROUTER, "vela_router")

        cases = [
            ("明天晋江天气", "weather_query"),
            ("今天的资讯", "market_brief"),
            ("这是实时的吗", "freshness_status"),
            ("刷新最新市场资讯", "market_refresh"),
        ]

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test-secret"}, clear=True):
            with tempfile.TemporaryDirectory() as tmp:
                with patch.object(router, "MARKET_REFRESH_DIR", Path(tmp)):
                    with patch.object(router.subprocess, "Popen") as popen:
                        popen.return_value.pid = 12345
                        with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K local boundary")) as run:
                            for message, expected_intent in cases:
                                with self.subTest(message):
                                    reply = router.reply_for(message)
                                    self.assertEqual(reply, "K local boundary")
                                    self.assertEqual(run.call_args.kwargs["intent"], expected_intent)
                                    self.assertIsInstance(run.call_args.kwargs["reply_adapter"], router.FallbackReplyAdapter)

    def test_deepseek_env_does_not_take_over_style_feedback_lane(self):
        router = load_module(ROUTER, "vela_router")

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test-secret"}, clear=True):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K，少菜单，多判断。")) as run:
                reply = router.reply_for("你太像机器人了")

        self.assertEqual(reply, "K，少菜单，多判断。")
        self.assertEqual(run.call_args.kwargs["intent"], "style_feedback")
        self.assertIsInstance(run.call_args.kwargs["reply_adapter"], router.FallbackReplyAdapter)

    def test_weather_reply_is_weather_surface_not_menu(self):
        router = load_module(ROUTER, "vela_router")

        reply = router.reply_for("明天晋江天气")

        self.assertIn("晋江", reply)
        self.assertIn("天气", reply)
        self.assertIn("实时源：未接入", reply)
        self.assertNotIn("DeepSeek", reply)
        self.assertNotIn("real_time_source_available", reply)
        self.assertNotIn("Market & World Briefing", reply)
        self.assertNotIn("CODEX", reply)
        self.assertNotIn("weather_query", reply)
        self.assertNotIn("debug", reply.lower())

    def test_weather_reply_uses_natural_boundary_for_real_trip_question(self):
        router = load_module(ROUTER, "vela_router")

        reply = router.render_weather_reply("明天晋江会不会下雨，能不能出门")

        self.assertIn("K，晋江", reply)
        self.assertIn("实时源：未接入", reply)
        self.assertIn("不编实时温度", reply)
        self.assertIn("下一步：", reply)
        self.assertNotIn("天气线", reply)
        self.assertNotIn("模型仅生成", reply)
        self.assertNotIn("weather_query", reply)
        self.assertNotIn("晋江会不会下雨", reply)

    def test_weather_location_extraction_handles_trip_actions(self):
        router = load_module(ROUTER, "vela_router")

        self.assertEqual(router.weather_location_from_text("明天晋江会不会下雨，能不能出门"), "晋江")
        self.assertEqual(router.weather_location_from_text("今天纽约冷吗，出门要不要加外套"), "纽约")
        self.assertEqual(router.weather_location_from_text("明天晋江要见客户，天气不准也给我出门风险"), "晋江")

    def test_daily_info_routes_to_deepseek_dialogue_lane(self):
        router = load_module(ROUTER, "vela_router")

        for text in ["解释一下这个概念", "帮我总结这段", "这是什么意思"]:
            intent = router.classify_intent(text)

            self.assertEqual(intent.name, "daily_info", text)
            self.assertFalse(intent.codex_allowed)
            self.assertFalse(intent.market_allowed)

    def test_now_general_information_routes_to_daily_info_not_market(self):
        router = load_module(ROUTER, "vela_router")

        for text in [
            "现在特斯拉有什么新闻",
            "现在DeepSeek有什么新消息",
            "现在这个政策发生了什么",
            "现在这个政策怎么样",
            "现在帮我查这个政策",
            "现在帮我搜一下OpenAI",
            "现在帮我搜一下OpenAI消息",
            "现在小米汽车有什么公告",
            "现在ChatGPT有什么更新",
            "现在政策有没有新公告",
            "现在查一下DeepSeek动态",
        ]:
            with self.subTest(text):
                intent = router.classify_intent(text)

                self.assertEqual(intent.name, "daily_info", text)
                self.assertIn("current_info", intent.focus_tags)
                self.assertFalse(intent.market_allowed)
                self.assertFalse(intent.codex_allowed)

    def test_current_general_information_synonyms_route_to_daily_info_not_freshness(self):
        router = load_module(ROUTER, "vela_router")

        for text in [
            "最新小米汽车有什么公告",
            "目前小米汽车有什么公告",
            "当前小米汽车有什么公告",
            "实时小米汽车有什么公告",
            "最新政策有没有新公告",
        ]:
            with self.subTest(text):
                intent = router.classify_intent(text)

                self.assertEqual(intent.name, "daily_info", text)
                self.assertIn("current_info", intent.focus_tags)
                self.assertFalse(intent.market_allowed)
                self.assertFalse(intent.codex_allowed)

    def test_now_world_event_information_routes_to_world_brief_not_market(self):
        router = load_module(ROUTER, "vela_router")

        for text in ["现在日本地震新闻", "现在中东冲突有什么新消息"]:
            with self.subTest(text):
                intent = router.classify_intent(text)

                self.assertEqual(intent.name, "world_brief", text)
                self.assertFalse(intent.market_allowed)

    def test_current_world_event_synonyms_route_to_world_brief_not_market(self):
        router = load_module(ROUTER, "vela_router")

        for text in ["最新日本地震新闻", "目前中东冲突有什么新消息"]:
            with self.subTest(text):
                intent = router.classify_intent(text)

                self.assertEqual(intent.name, "world_brief", text)
                self.assertIn("current_info", intent.focus_tags)
                self.assertFalse(intent.market_allowed)

    def test_natural_market_time_phrases_route_to_market_brief(self):
        router = load_module(ROUTER, "vela_router")

        for text in ["今天早上市场怎么看", "午盘怎么看", "收盘后帮我整理一下"]:
            intent = router.classify_intent(text)
            self.assertEqual(intent.name, "market_brief", text)
            self.assertTrue(intent.market_allowed)

    def test_us_and_korea_question_focuses_cross_market_risk(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("美股和韩国市场有什么风险")

        self.assertEqual(intent.name, "market_brief")
        for tag in ["us_equities", "korea", "usd", "us_10y", "semiconductors"]:
            self.assertIn(tag, intent.focus_tags)

    def test_codex_only_enters_codex_bridge_on_codex_intent(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("/CODEX")

        self.assertEqual(intent.name, "codex_task")
        self.assertTrue(intent.codex_allowed)
        self.assertFalse(intent.market_allowed)

    def test_codex_slash_without_leading_slash_enters_codex_bridge(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("CODEX/")

        self.assertEqual(intent.name, "codex_task")
        self.assertTrue(intent.codex_allowed)
        self.assertFalse(intent.market_allowed)

    def test_today_news_is_market_risk_need_not_generic_chat(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("今天的资讯")

        self.assertEqual(intent.name, "market_brief")
        self.assertTrue(intent.market_allowed)
        self.assertFalse(intent.codex_allowed)

    def test_market_impulse_reply_brakes_without_dumping_full_brief(self):
        router = load_module(ROUTER, "vela_router")

        reply = router.render_cached_market_reply("我今天有点上头，想直接满仓冲进去")

        self.assertLess(len(reply), 520)
        self.assertIn("不是实时直播", reply)
        self.assertTrue(any(token in reply for token in ["满仓", "仓位", "刹车", "先别冲"]))
        self.assertNotIn("VELA 市场简报", reply)
        self.assertNotIn("关键风险\n1.", reply)

    def test_plain_market_news_is_compact_not_full_report(self):
        router = load_module(ROUTER, "vela_router")

        reply = router.render_cached_market_reply("今天的资讯给我，但不要英文生肉新闻")

        self.assertLess(len(reply), 900)
        self.assertIn("不是实时直播", reply)
        self.assertIn("60秒判断", reply)
        self.assertIn("下一观察点", reply)
        self.assertNotIn("VELA 市场简报", reply)
        self.assertNotIn("A股\n- 上证", reply)
        self.assertNotIn("关键风险\n1.", reply)
        self.assertNotIn("Market & World Briefing", reply)
        self.assertNotIn("Samsung", reply)
        self.assertNotIn("Nvidia", reply)

    def test_current_a_share_market_uses_live_snapshot_not_cache_dump(self):
        router = load_module(ROUTER, "vela_router")
        live = SimpleNamespace(
            ok=True,
            as_of="2026-06-01 19:15 北京时间",
            source="新浪财经行情快照",
            lines=[
                "上证指数 4057.74（-10.83，-0.27%）",
                "深证成指 15340.36（-234.78，-1.51%）",
                "创业板指 3950.94（-87.01，-2.15%）",
            ],
            source_status="实时源：已接入",
            note="",
            error="",
        )

        with patch.object(router, "fetch_live_market_snapshot", return_value=live):
            reply = router.render_cached_market_reply("今天的A股市场如何")

        self.assertLess(len(reply), 520)
        self.assertIn("实时源：已接入", reply)
        self.assertIn("上证指数", reply)
        self.assertIn("判断：", reply)
        self.assertIn("下一步：", reply)
        self.assertNotIn("以下基于最近缓存", reply)
        self.assertNotIn("VELA 市场简报", reply)
        self.assertNotIn("状态边界：", reply)
        self.assertNotIn("关键风险\n1.", reply)

        with patch.object(router, "fetch_live_market_snapshot", return_value=live):
            market_info_reply = router.render_cached_market_reply("现在的市场资讯")
        self.assertIn("实时源：已接入", market_info_reply)
        self.assertNotIn("以下基于最近缓存", market_info_reply)

    def test_current_market_reply_preserves_wechat_line_breaks(self):
        router = load_module(ROUTER, "vela_router")
        live = SimpleNamespace(
            ok=True,
            as_of="2026-06-01 19:15 北京时间",
            source="新浪财经行情快照",
            lines=[
                "上证指数 4057.74（-10.83，-0.27%）",
                "深证成指 15340.36（-234.78，-1.51%）",
            ],
            source_status="实时源：已接入",
            note="",
            error="",
        )

        with patch.object(router, "fetch_live_market_snapshot", return_value=live):
            reply = router.reply_for("今天的A股市场如何")

        self.assertIn("\nA股快照：\n", reply)
        self.assertIn("\n- 上证指数", reply)
        self.assertIn("\n判断：", reply)
        self.assertIn("\n下一步：", reply)

    def test_current_market_live_failure_is_compact_cache_degrade(self):
        router = load_module(ROUTER, "vela_router")
        live = SimpleNamespace(
            ok=False,
            as_of="",
            source="新浪财经行情快照",
            lines=[],
            source_status="实时源：暂不可用",
            note="",
            error="timeout",
        )

        with patch.object(router, "fetch_live_market_snapshot", return_value=live):
            reply = router.render_cached_market_reply("今天的A股市场如何")

        self.assertLess(len(reply), 620)
        self.assertIn("实时源：暂不可用", reply)
        self.assertIn("缓存降级", reply)
        self.assertIn("判断：", reply)
        self.assertIn("下一步：", reply)
        self.assertNotIn("以下基于最近缓存", reply)
        self.assertNotIn("VELA 市场简报", reply)
        self.assertNotIn("状态边界：", reply)

    def test_current_foreign_market_does_not_use_a_share_snapshot(self):
        router = load_module(ROUTER, "vela_router")

        for prompt in ["现在美股市场如何", "现在美股资讯"]:
            with self.subTest(prompt):
                reply = router.render_cached_market_reply(prompt)

                self.assertIn("实时源：暂不可用", reply)
                self.assertIn("缓存降级", reply)
                self.assertIn("外盘实时源未接通", reply)
                self.assertNotIn("A股快照", reply)
                self.assertNotIn("上证指数", reply)

    def test_current_market_news_uses_current_lane_not_cache_summary(self):
        router = load_module(ROUTER, "vela_router")
        live = SimpleNamespace(
            ok=True,
            as_of="2026-06-01 19:15 北京时间",
            source="新浪财经行情快照",
            lines=[
                "上证指数 4057.74（-10.83，-0.27%）",
                "深证成指 15340.36（-234.78，-1.51%）",
            ],
            source_status="实时源：已接入",
            note="",
            error="",
        )

        with patch.object(router, "fetch_live_market_snapshot", return_value=live):
            reply = router.render_cached_market_reply("当前市场新闻")

        self.assertIn("实时源：已接入", reply)
        self.assertIn("A股快照", reply)
        self.assertNotIn("不是实时直播；实时源：未接入", reply)
        self.assertNotIn("60秒判断", reply)

    def test_current_global_market_does_not_use_a_share_snapshot(self):
        router = load_module(ROUTER, "vela_router")

        for prompt in ["现在全球市场资讯", "现在世界市场有什么重要新闻"]:
            with self.subTest(prompt):
                reply = router.render_cached_market_reply(prompt)

                self.assertIn("实时源：暂不可用", reply)
                self.assertIn("缓存降级", reply)
                self.assertIn("外盘实时源未接通", reply)
                self.assertIn("全球", reply)
                self.assertNotIn("A股仍", reply)
                self.assertNotIn("A股快照", reply)
                self.assertNotIn("上证指数", reply)

    def test_expanded_market_news_can_return_full_report(self):
        router = load_module(ROUTER, "vela_router")

        reply = router.render_cached_market_reply("今天的资讯展开全部来源")

        self.assertIn("VELA 市场简报", reply)
        self.assertIn("关键风险", reply)

    def test_market_lane_records_interaction_session_and_hidden_need(self):
        router = load_module(ROUTER, "vela_router")

        with patch.object(router, "render_cached_market_reply", return_value="K，缓存市场判断。"):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K，模型市场判断。")) as run:
                reply = router.reply_for("今天的资讯")

        self.assertEqual(reply, "K，模型市场判断。")
        self.assertEqual(run.call_args.kwargs["intent"], "market_brief")
        self.assertIn("缓存市场判断", run.call_args.kwargs["supporting_context"])

    def test_project_discussion_routes_to_project_assistant(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("AugSun 项目下一步怎么拆")

        self.assertEqual(intent.name, "project_assistant")

    def test_codex_status_question_routes_to_codex_task_without_market(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("Codex 现在执行到哪里了")

        self.assertEqual(intent.name, "codex_task")
        self.assertTrue(intent.codex_allowed)
        self.assertFalse(intent.market_allowed)

    def test_codex_bridge_preserves_original_user_request_for_learning(self):
        router = load_module(ROUTER, "vela_router")
        user_text = "Codex 状态，别把 Git 日志整段贴给我"

        with patch.object(
            router.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="Codex 摘要：路由干净。", stderr=""),
        ):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K，Codex 摘要。")) as run:
                reply = router.reply_for(user_text)

        self.assertEqual(reply, "K，Codex 摘要。")
        self.assertEqual(run.call_args.args[0], user_text)
        self.assertEqual(run.call_args.kwargs["intent"], "codex_task")
        self.assertIn("Codex 摘要", run.call_args.kwargs["codex_summary"])

    def test_world_brief_routes_without_market_or_codex(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("世界军政和地缘要闻给我一版")

        self.assertEqual(intent.name, "world_brief")
        self.assertIn("geopolitics", intent.focus_tags)
        self.assertFalse(intent.market_allowed)
        self.assertFalse(intent.codex_allowed)

    def test_memory_related_routes_to_learning_loop(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("记住：以后市场分析默认先看A股、美股、韩国")

        self.assertEqual(intent.name, "memory_related")
        self.assertIn("memory", intent.focus_tags)
        self.assertFalse(intent.codex_allowed)

    def test_style_feedback_routes_to_memory_candidate(self):
        router = load_module(ROUTER, "vela_router")

        for text in ["你刚才太像新闻列表了", "你刚才太像机器人了", "这回复太机械"]:
            intent = router.classify_intent(text)

            self.assertEqual(intent.name, "style_feedback", text)
            self.assertIn("style_feedback", intent.focus_tags)
            self.assertFalse(intent.codex_allowed)
            self.assertFalse(intent.market_allowed)

    def test_hell_autopsy_routes_to_deep_analysis(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("地狱验尸一下这个架构")

        self.assertEqual(intent.name, "deep_analysis")
        self.assertIn("architecture", intent.focus_tags)
        self.assertFalse(intent.codex_allowed)
        self.assertFalse(intent.market_allowed)

    def test_relationship_repair_feedback_routes_to_style_feedback(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("你没懂我")

        self.assertEqual(intent.name, "style_feedback")
        self.assertIn("relationship_repair", intent.focus_tags)
        self.assertFalse(intent.codex_allowed)
        self.assertFalse(intent.market_allowed)

    def test_human_iteration_feedback_variants_route_without_tool_pollution(self):
        router = load_module(ROUTER, "vela_router")

        for text in ["我需要你更智能", "你理解一下我的意思", "继续推进，不要拖", "不够像真人", "不要机械道歉"]:
            with self.subTest(text):
                intent = router.classify_intent(text)

                self.assertEqual(intent.name, "style_feedback")
                self.assertIn("style_feedback", intent.focus_tags)
                self.assertFalse(intent.market_allowed)
                self.assertFalse(intent.codex_allowed)

    def test_real_dialogue_scenarios_route_without_tool_pollution(self):
        router = load_module(ROUTER, "vela_router")

        cases = {
            "逻辑是什么呢": "daily_info",
            "协助我分析一下？": "daily_info",
            "这么选择会比较好吗？": "daily_info",
            "今天市场是不是能加仓": "market_brief",
            "VELA 现在和 DeepSeek / Codex / 记忆是什么关系": "memory_related",
        }

        for text, expected_intent in cases.items():
            with self.subTest(text):
                intent = router.classify_intent(text)

                self.assertEqual(intent.name, expected_intent)
                if expected_intent != "market_brief":
                    self.assertFalse(intent.market_allowed)
                if expected_intent != "codex_task":
                    self.assertFalse(intent.codex_allowed)

    def test_realistic_wechat_mixed_scenarios_keep_tool_boundaries(self):
        router = load_module(ROUTER, "vela_router")

        cases = [
            ("刚才那句不是我要的，别解释，重新判断", "style_feedback", False, False),
            ("我现在脑子糊住了，只给我一个下一步", "normal_chat", False, False),
            ("继续 VELA 项目，别讲愿景，给三条风险", "project_assistant", False, False),
            ("我今天有点上头，想直接满仓冲进去", "market_brief", True, False),
            ("明天晋江会不会下雨，能不能出门", "weather_query", False, False),
            ("这是实时数据吗？没有就明说", "freshness_status", False, False),
            ("CODEX/ 现在做到哪了，别发日志", "codex_task", False, True),
            ("VELA 你到底是 DeepSeek 还是 Codex？记忆放哪", "memory_related", False, False),
            ("别客服话术，像个真伙伴一样说", "style_feedback", False, False),
            ("你刚刚还是像客服，下一句别解释身份，直接说人话", "style_feedback", False, False),
            ("我不想看新闻列表，A股今天先等还是冲", "market_brief", True, False),
            ("你就别反驳我，夸我决定英明就行", "normal_chat", False, False),
            ("地狱验尸一下：为什么它还是不聪明", "deep_analysis", False, False),
        ]

        for text, expected_intent, market_allowed, codex_allowed in cases:
            with self.subTest(text):
                intent = router.classify_intent(text)

                self.assertEqual(intent.name, expected_intent)
                self.assertEqual(intent.market_allowed, market_allowed)
                self.assertEqual(intent.codex_allowed, codex_allowed)

    def test_route_decision_is_structured_and_not_final_reply(self):
        router = load_module(ROUTER, "vela_router")

        decision = router.route_decision("今天A股怎么看")
        payload = decision.to_dict()

        self.assertEqual(payload["intent"], "market_brief")
        self.assertFalse(payload["needs_retrieval"])
        self.assertFalse(payload["needs_codex"])
        self.assertTrue(payload["needs_deep_reasoning"])
        self.assertTrue(payload["cache_allowed"])
        self.assertIn("A股", payload["priority_markets"])


    def test_realtime_question_uses_freshness_status_fast_lane(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("这是实时的吗")

        self.assertEqual(intent.name, "freshness_status")
        self.assertFalse(intent.codex_allowed)
        self.assertFalse(intent.market_allowed)
        started = time.perf_counter()
        reply = router.reply_for("这是实时的吗")
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 2.0)
        self.assertIn("更新时间", reply)
        self.assertIn("数据来源", reply)
        self.assertIn("实时源：未接入", reply)
        self.assertNotIn("data_status", reply)
        self.assertNotIn("source_type", reply)
        self.assertNotIn("real_time_source_available", reply)
        self.assertNotIn("Market & World Briefing", reply)

    def test_refresh_market_question_uses_refresh_lane_without_blocking(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("刷新最新市场资讯")

        self.assertEqual(intent.name, "market_refresh")
        self.assertTrue(intent.market_allowed)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(router, "MARKET_REFRESH_DIR", Path(tmp)):
                with patch("subprocess.Popen") as popen:
                    popen.return_value.pid = 12345
                    reply = router.reply_for("刷新最新市场资讯")
                    popen_args = popen.call_args.args[0]
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 2.0)
        self.assertIn("不拿缓存冒充实时", reply)
        self.assertIn("前台先返回状态", reply)
        self.assertIn("实时源：未接入", reply)
        self.assertIn("--lock-file", popen_args)
        self.assertNotIn("以下基于最近缓存", reply)
        self.assertNotIn("VELA 市场简报", reply)
        self.assertNotIn("Market & World Briefing", reply)
        self.assertNotIn("data_status", reply)
        self.assertNotIn("source_type", reply)
        self.assertNotIn("real_time_source_available", reply)

    def test_explicit_realtime_retrieval_request_does_not_return_cached_brief(self):
        router = load_module(ROUTER, "vela_router")
        text = "OK 明白了，开启检索，我需要实时的资讯"

        intent = router.classify_intent(text)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(router, "MARKET_REFRESH_DIR", Path(tmp)):
                with patch("subprocess.Popen") as popen:
                    popen.return_value.pid = 12345
                    reply = router.reply_for(text)

        self.assertEqual(intent.name, "market_refresh")
        self.assertIn("不拿缓存冒充实时", reply)
        self.assertIn("前台先返回状态", reply)
        self.assertNotIn("以下基于最近缓存", reply)
        self.assertNotIn("VELA 市场简报", reply)
        self.assertNotIn("data_status", reply)
        self.assertNotIn("source_type", reply)

    def test_greeting_fast_lane_bypasses_slow_gpt_command(self):
        router = load_module(ROUTER, "vela_router")
        slow_command = 'python -c "import time; time.sleep(30); print(\'slow\')"'

        with patch.dict(
            "os.environ",
            {"VELA_GPT_COMMAND": slow_command, "VELA_GPT_TIMEOUT_SECONDS": "5"},
            clear=True,
        ):
            started = time.perf_counter()
            reply = router.reply_for("你好")
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 2.0)
        self.assertLess(len(reply), 160)
        self.assertNotIn("Market & World Briefing", reply)

    def test_hello_vela_can_use_real_adapter_when_available(self):
        router = load_module(ROUTER, "vela_router")

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test-secret"}, clear=True):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K real")) as run:
                reply = router.reply_for("你好 VELA")

        self.assertEqual(reply, "K real")
        self.assertNotIn("reply_adapter", run.call_args.kwargs)

    def test_plain_hello_can_use_real_adapter_when_available(self):
        router = load_module(ROUTER, "vela_router")

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test-secret"}, clear=True):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K real")) as run:
                reply = router.reply_for("你好")

        self.assertEqual(reply, "K real")
        self.assertNotIn("reply_adapter", run.call_args.kwargs)

    def test_plain_vela_uses_deepseek_layer_when_available(self):
        router = load_module(ROUTER, "vela_router")

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test-secret"}, clear=True):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K real")) as run:
                reply = router.reply_for("VELA")

        self.assertEqual(reply, "K real")
        self.assertNotIn("reply_adapter", run.call_args.kwargs)

    def test_structured_project_model_reply_is_not_wrapped_with_duplicate_sections(self):
        product = load_module(PRODUCT, "vela_product_layers")

        class StructuredProjectAdapter:
            name = "deepseek_chat"

            def generate(self, context):
                return SimpleNamespace(
                    text=(
                        "K，目标：锁 AugSun 的最小用户闭环。\n"
                        "风险：别开新模块，别让工程噪音进前台。\n"
                        "下一步：先验证一个用户从触发到反馈的闭环。"
                    ),
                    source="deepseek_chat",
                    used_api=True,
                    adapter=self.name,
                )

        with tempfile.TemporaryDirectory() as tmp:
            reply = product.run_layered_response(
                "继续 AugSun 项目",
                intent="project_assistant",
                reply_adapter=StructuredProjectAdapter(),
                log_dir=Path(tmp),
            ).text

        self.assertIn("目标：锁 AugSun 的最小用户闭环", reply)
        self.assertEqual(reply.count("风险："), 1)
        self.assertEqual(reply.count("下一步："), 1)
        self.assertNotIn("把 Codex 输出当产品判断", reply)
        self.assertNotIn("别把好运气请来当部门主管", reply)

    def test_project_analysis_tracks_minimum_loop_request_instead_of_generic_risks(self):
        product = load_module(PRODUCT, "vela_product_layers")

        packet = product.analysis_layer(
            "继续 AugSun，但不要开新模块，先查最小闭环",
            "project_assistant",
        )
        rendered = product.render_vela_persona(packet)

        self.assertIn("最小闭环", packet.judgment)
        self.assertTrue(any("新模块" in risk for risk in packet.risks), packet.risks)
        self.assertTrue(any("触发" in action and "反馈" in action for action in packet.next_actions), packet.next_actions)
        self.assertNotIn("把 Codex 输出当产品判断", rendered)
        self.assertNotIn("需要代码执行时再交给 /CODEX", rendered)

    def test_markdown_project_model_reply_is_frontstage_ready_without_local_wrap(self):
        product = load_module(PRODUCT, "vela_product_layers")

        class MarkdownProjectAdapter:
            name = "deepseek_chat"

            def generate(self, context):
                return SimpleNamespace(
                    text=(
                        "K，继续推进 AugSun，不开新模块。\n"
                        "**判断**：当前最小闭环是跑通一个真实场景。\n"
                        "**阻塞**：上下文断链，每轮像新对话。\n"
                        "**最短路径**：选一个真实入口，验证触发到反馈是否闭合。"
                    ),
                    source="deepseek_chat",
                    used_api=True,
                    adapter=self.name,
                )

        with tempfile.TemporaryDirectory() as tmp:
            reply = product.run_layered_response(
                "继续 AugSun，但不要开新模块，先查最小闭环",
                intent="project_assistant",
                reply_adapter=MarkdownProjectAdapter(),
                log_dir=Path(tmp),
            ).text

        self.assertIn("当前最小闭环是跑通一个真实场景", reply)
        self.assertIn("验证触发到反馈是否闭合", reply)
        self.assertEqual(reply.count("最短路径"), 1)
        self.assertNotIn("新模块会稀释验收口径", reply)
        self.assertNotIn("别把好运气请来当部门主管", reply)

    def test_persona_alias_routes_through_guarded_local_tool_lane(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("语气")

        self.assertEqual(intent.name, "persona_tool")
        self.assertFalse(intent.codex_allowed)
        with patch.object(router.subprocess, "run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout="VELA 语气校准\n少菜单，多判断。", stderr="")
            reply = router.reply_for("语气")

        self.assertIn("少菜单，多判断", reply)
        self.assertNotIn("persona_tool", reply)
        self.assertNotIn("debug", reply.lower())
        argv = run.call_args.args[0]
        self.assertIn(str(router.PERSONALITY_SCRIPT), argv)
        self.assertIn("voice", argv)

    def test_legacy_personality_command_name_still_enters_router_lane(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("persona growth")

        self.assertEqual(intent.name, "persona_tool")
        with patch.object(router.subprocess, "run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout="成长日志已校准。", stderr="")
            reply = router.reply_for("persona growth")

        self.assertIn("成长日志", reply)
        self.assertIn("growth", run.call_args.args[0])

    def test_daily_briefing_command_name_enters_guarded_router_lane(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("daily-briefing")

        self.assertEqual(intent.name, "daily_briefing")
        with patch.object(router.subprocess, "run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout="VELA 市场简报\n重点风险。", stderr="")
            reply = router.reply_for("daily-briefing")

        self.assertIn("重点风险", reply)
        self.assertNotIn("daily_briefing", reply)
        self.assertIn(str(router.DAILY_BRIEFING_SCRIPT), run.call_args.args[0])

    def test_non_realtime_news_summary_uses_cache_status_before_brief(self):
        router = load_module(ROUTER, "vela_router")

        reply = router.reply_for("如果不是实时的重要资讯梳理给我")

        self.assertIn("不是实时直播", reply)
        self.assertIn("实时源：未接入", reply)
        self.assertIn("最近缓存", reply)
        self.assertNotIn("data_status", reply)
        self.assertIn("60秒判断", reply)
        self.assertNotIn("以下基于最近缓存", reply)
        self.assertNotIn("VELA 市场简报", reply)
        self.assertNotIn("direction:", reply)
        self.assertNotIn("score:", reply)

    def test_response_hash_guard_blocks_duplicate_platform_message(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"CC_MESSAGE_ID": "wechat-msg-1"}, clear=True):
                first = router.claim_response_once(
                    "same reply",
                    "normal_chat",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )
                second = router.claim_response_once(
                    "same reply",
                    "normal_chat",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )

        self.assertTrue(first)
        self.assertFalse(second)

    def test_response_hash_guard_allows_repeated_local_dialogue_without_platform_id(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {}, clear=True):
                first = router.claim_response_once(
                    "K，我在。",
                    "normal_chat",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )
                second = router.claim_response_once(
                    "K，我在。",
                    "normal_chat",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )

        self.assertTrue(first)
        self.assertTrue(second)

    def test_response_hash_guard_allows_same_text_after_style_feedback_with_distinct_messages(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with patch.dict("os.environ", {"CC_MESSAGE_ID": "wechat-msg-1"}, clear=True):
                first = router.claim_response_once(
                    "K，我在。",
                    "normal_chat",
                    state_dir=state_dir,
                    ttl_seconds=30,
                )
            with patch.dict("os.environ", {"CC_MESSAGE_ID": "wechat-msg-2"}, clear=True):
                router.claim_request_once(
                    "你太像机器人了",
                    "style_feedback",
                    state_dir=state_dir,
                    ttl_seconds=30,
                )
            with patch.dict("os.environ", {"CC_MESSAGE_ID": "wechat-msg-3"}, clear=True):
                after_feedback = router.claim_response_once(
                    "K，我在。",
                    "normal_chat",
                    state_dir=state_dir,
                    ttl_seconds=30,
                )
                repeated_after_feedback = router.claim_response_once(
                    "K，我在。",
                    "normal_chat",
                    state_dir=state_dir,
                    ttl_seconds=30,
                )

        self.assertTrue(first)
        self.assertTrue(after_feedback)
        self.assertFalse(repeated_after_feedback)

    def test_router_send_once_claim_blocks_duplicate_platform_message(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"CC_MESSAGE_ID": "wechat-msg-1"}, clear=True):
                first = router.claim_request_once(
                    "你好",
                    "normal_chat",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )
                second = router.claim_request_once(
                    "你好",
                    "normal_chat",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )

            logs = list(Path(tmp).glob("duplicate-requests-*.jsonl"))

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(logs), 1)

    def test_router_send_once_allows_repeated_local_dialogue_without_platform_id(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {}, clear=True):
                first = router.claim_request_once(
                    "你好",
                    "normal_chat",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )
                second = router.claim_request_once(
                    "你好",
                    "normal_chat",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )

            logs = list(Path(tmp).glob("duplicate-requests-*.jsonl"))

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(len(logs), 0)

    def test_market_refresh_still_dedupes_without_platform_id(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {}, clear=True):
                first = router.claim_request_once(
                    "刷新最新市场资讯",
                    "market_refresh",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )
                second = router.claim_request_once(
                    "刷新最新市场资讯",
                    "market_refresh",
                    state_dir=Path(tmp),
                    ttl_seconds=30,
                )

        self.assertTrue(first)
        self.assertFalse(second)

    def test_router_send_once_allows_same_prompt_after_style_feedback(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with patch.dict("os.environ", {"CC_MESSAGE_ID": "wechat-msg-1"}, clear=True):
                first = router.claim_request_once(
                    "你好",
                    "normal_chat",
                    state_dir=state_dir,
                    ttl_seconds=30,
                )
            with patch.dict("os.environ", {"CC_MESSAGE_ID": "wechat-msg-2"}, clear=True):
                feedback = router.claim_request_once(
                    "你太像机器人了",
                    "style_feedback",
                    state_dir=state_dir,
                    ttl_seconds=30,
                )
            with patch.dict("os.environ", {"CC_MESSAGE_ID": "wechat-msg-3"}, clear=True):
                after_feedback = router.claim_request_once(
                    "你好",
                    "normal_chat",
                    state_dir=state_dir,
                    ttl_seconds=30,
                )
                repeated_after_feedback = router.claim_request_once(
                    "你好",
                    "normal_chat",
                    state_dir=state_dir,
                    ttl_seconds=30,
                )

        self.assertTrue(first)
        self.assertTrue(feedback)
        self.assertTrue(after_feedback)
        self.assertFalse(repeated_after_feedback)


class VelaMarketBriefingTests(unittest.TestCase):
    def test_market_briefing_windows_are_9_1230_and_17(self):
        market = load_module(MARKET, "vela_market_briefing")
        cases = [
            ("2026-05-25T08:55:00+08:00", "09:00", "2026-05-24T18:00:00+08:00", "2026-05-25T09:00:00+08:00"),
            ("2026-05-25T12:45:00+08:00", "12:30", "2026-05-25T09:00:00+08:00", "2026-05-25T12:30:00+08:00"),
            ("2026-05-25T17:15:00+08:00", "17:00", "2026-05-25T09:00:00+08:00", "2026-05-25T17:00:00+08:00"),
        ]

        for now_text, slot, start_text, end_text in cases:
            start, end, actual_slot = market.briefing_window(market.datetime.fromisoformat(now_text))
            self.assertEqual(actual_slot, slot)
            self.assertEqual(start.isoformat(), start_text)
            self.assertEqual(end.isoformat(), end_text)

    def test_query_phrases_pin_market_template_slot(self):
        market = load_module(MARKET, "vela_market_briefing")
        base = market.datetime.fromisoformat("2026-05-25T18:00:00+08:00")

        cases = [
            ("今天早上市场怎么看", "09:00"),
            ("午盘怎么看", "12:30"),
            ("收盘后帮我整理一下", "17:00"),
            ("美股和韩国市场风险呢", "17:00"),
        ]

        for query, slot in cases:
            _, _, actual = market.briefing_window(market.resolve_market_time(query, base))
            self.assertEqual(actual, slot, query)

    def test_cached_brief_with_old_window_is_ignored(self):
        market = load_module(MARKET, "vela_market_briefing")
        with tempfile.TemporaryDirectory() as tmp:
            original_cache_dir = market.CACHE_DIR
            market.CACHE_DIR = Path(tmp)
            try:
                payload = {
                    "as_of": "2026-05-25T17:00:00+08:00",
                    "window_label": "2026-05-25 08:00 至 2026-05-25 17:00 中国时间",
                    "slot": "17:00",
                    "dashboard": {},
                    "news": [],
                    "good_signs": [],
                    "bad_signs": [],
                    "main_line": "",
                    "vela_judgment": [],
                    "watch_next": [],
                }
                path = market.cache_path(market.datetime.fromisoformat("2026-05-25T17:00:00+08:00"), "17:00")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

                loaded = market.load_cached_brief(market.datetime.fromisoformat("2026-05-25T17:00:00+08:00"))
            finally:
                market.CACHE_DIR = original_cache_dir

        self.assertIsNone(loaded)

    def test_cached_brief_without_current_schema_is_ignored(self):
        market = load_module(MARKET, "vela_market_briefing")
        with tempfile.TemporaryDirectory() as tmp:
            original_cache_dir = market.CACHE_DIR
            market.CACHE_DIR = Path(tmp)
            try:
                payload = {
                    "as_of": "2026-05-25T12:30:00+08:00",
                    "window_label": "2026-05-25 09:00 至 2026-05-25 12:30 中国时间",
                    "slot": "12:30",
                    "dashboard": {},
                    "news": [],
                    "good_signs": [],
                    "bad_signs": [],
                    "main_line": "",
                    "vela_judgment": ["旧版话术"],
                    "watch_next": [],
                }
                path = market.cache_path(market.datetime.fromisoformat("2026-05-25T12:30:00+08:00"), "12:30")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

                loaded = market.load_cached_brief(market.datetime.fromisoformat("2026-05-25T12:30:00+08:00"))
            finally:
                market.CACHE_DIR = original_cache_dir

        self.assertIsNone(loaded)

    def test_structured_news_item_has_required_market_fields(self):
        market = load_module(MARKET, "vela_market_briefing")

        item = market.MarketNewsItem(
            title="Nvidia lifts semiconductor risk appetite",
            source="Reuters",
            published_at="2026-05-25T16:00:00+08:00",
            market_tags=["us_equities", "semiconductors"],
            impact_type=["AI", "半导体"],
            impact_score=4,
            direction="bullish",
            reason="牵动 AI 与半导体链条。",
            source_url="https://example.test",
        )

        self.assertEqual(item.impact_score, 4)
        self.assertEqual(item.direction, "bullish")
        self.assertEqual(item.impact_type, ["AI", "半导体"])
        self.assertIn("semiconductors", item.market_tags)

    def test_legacy_impact_type_string_is_normalized_to_list(self):
        market = load_module(MARKET, "vela_market_briefing")

        item = market.MarketNewsItem(
            title="Treasury yields pressure tech stocks",
            source="Reuters",
            published_at="2026-05-25T16:00:00+08:00",
            market_tags=["us_equities", "us_10y"],
            impact_type="rates_fx",
            impact_score=4,
            direction="bearish",
            reason="美债上行压估值。",
        )

        self.assertEqual(item.impact_type, ["rates_fx"])

    def test_format_market_brief_has_fixed_sections_and_nonempty_fields(self):
        market = load_module(MARKET, "vela_market_briefing")
        brief = sample_brief(market, "2026-05-25T13:00:00+08:00")

        text = market.format_market_brief(brief)

        self.assertIn("VELA 市场简报", text)
        self.assertNotIn("Market & World Briefing", text)
        for section in ["60秒判断", "A股", "美股", "韩国 / 日本", "关键风险", "VELA 判断", "下一次观察点"]:
            self.assertIn(section, text)
        self.assertIn("A股\n- 上证", text)
        self.assertIn("S&P 500（标普500指数）", text)
        self.assertNotIn("标签：", text)
        self.assertNotIn("评分：", text)
        self.assertNotIn("方向：", text)
        self.assertNotIn("bullish", text)
        self.assertIn("暂无可靠数据，暂不纳入判断。", market.join_fields({}, ["成交额"]))
        self.assertNotIn("raw", text.lower())
        self.assertNotIn("debug", text.lower())
        self.assertNotIn("C:\\", text)

    def test_market_news_line_is_chinese_and_hides_schema_fields(self):
        market = load_module(MARKET, "vela_market_briefing")
        item = market.MarketNewsItem(
            title="Stocks rally, while oil and dollar ease on Middle East peace hopes By Reuters",
            source="Investing.com Canada",
            published_at="2026-05-25T17:00:00+08:00",
            market_tags=["us_equities", "usd", "oil"],
            impact_type=["风险偏好", "汇率", "油价"],
            impact_score=3,
            direction="bullish",
            reason="影响全球风险偏好、汇率和成长股折现率。",
        )

        text = market.format_news_line(1, item)

        self.assertIn("油价和美元走弱", text)
        self.assertIn("全球风险偏好", text)
        self.assertIn("来源：路透社", text)
        self.assertNotIn("Stocks rally", text)
        self.assertNotIn("direction", text.lower())
        self.assertNotIn("bullish", text)
        self.assertNotIn("标签", text)
        self.assertNotIn("评分", text)

    def test_9_beijing_uses_a_share_premarket(self):
        market = load_module(MARKET, "vela_market_briefing")
        brief = sample_brief(market, "2026-05-25T09:00:00+08:00", slot="09:00")

        text = market.format_market_brief(brief)

        self.assertIn("A股盘前", text)
        self.assertIn("前夜美股", text)

    def test_1230_beijing_uses_a_share_midday_and_korea_japan_intraday(self):
        market = load_module(MARKET, "vela_market_briefing")
        brief = sample_brief(market, "2026-05-25T12:30:00+08:00", slot="12:30")

        text = market.format_market_brief(brief)

        self.assertIn("A股午盘后", text)
        self.assertIn("日韩盘中", text)
        self.assertNotIn("日韩收盘", text)

    def test_17_beijing_uses_us_premarket_not_fake_close(self):
        market = load_module(MARKET, "vela_market_briefing")
        brief = sample_brief(market, "2026-05-25T17:30:00+08:00", slot="17:00")

        text = market.format_market_brief(brief)

        self.assertIn("美股盘前", text)
        self.assertNotIn("美股收盘", text)

    def test_select_news_uses_market_priority_weights(self):
        market = load_module(MARKET, "vela_market_briefing")
        items = [
            market.MarketNewsItem(
                title="Military headline with distant market impact",
                source="AP",
                published_at="2026-05-25T12:00:00+08:00",
                market_tags=["geopolitics"],
                impact_type=["地缘"],
                impact_score=5,
                direction="uncertain",
                reason="影响有限。",
            ),
            market.MarketNewsItem(
                title="A-share turnover improves as yuan steadies",
                source="Reuters",
                published_at="2026-05-25T12:00:00+08:00",
                market_tags=["china_a", "usd"],
                impact_type=["风险偏好", "汇率"],
                impact_score=3,
                direction="bullish",
                reason="更接近交易决策。",
            ),
        ]

        selected = market.select_news(items, 1)

        self.assertEqual(selected[0].title, "A-share turnover improves as yuan steadies")

    def test_market_freshness_status_reads_current_cache(self):
        market = load_module(MARKET, "vela_market_briefing")
        now = market.datetime.fromisoformat("2026-05-25T17:30:00+08:00")
        with tempfile.TemporaryDirectory() as tmp:
            original_cache_dir = market.CACHE_DIR
            market.CACHE_DIR = Path(tmp)
            try:
                brief = sample_brief(market, "2026-05-25T17:00:00+08:00", slot="17:00")
                market.save_cached_brief(brief, now)

                status = market.market_freshness_status(now=now)
                text = market.format_freshness_status(status)
            finally:
                market.CACHE_DIR = original_cache_dir

        self.assertEqual(status.data_status, "cached")
        self.assertEqual(status.source_type, "cache")
        self.assertFalse(status.real_time_source_available)
        self.assertTrue(status.cached_summary_available)
        self.assertFalse(status.model_generated_only)
        self.assertFalse(status.unavailable)
        self.assertIn("更新时间", text)
        self.assertIn("数据来源", text)
        self.assertIn("实时源：未接入", text)
        self.assertNotIn("last_updated", text)
        self.assertNotIn("source_type", text)
        self.assertNotIn("real_time_source_available", text)
        self.assertIn("不是实时直播", text)


def sample_brief(market, as_of: str, slot: str = "17:00"):
    dash = market.MarketDashboard(
        china={
            "上证": "3120 (+0.30%)",
            "深成指": "9820 (+0.20%)",
            "创业板": "1880 (-0.10%)",
            "沪深300": "3650 (+0.40%)",
            "成交额": "8200亿",
            "涨跌家数": "2900/2100",
            "强势板块": "半导体、军工",
            "弱势板块": "地产、白酒",
            "人民币/港股联动": "人民币稳定，港股科技偏强",
        },
        us={
            "S&P 500": "6100 (+0.15%)",
            "Nasdaq": "20000 (+0.30%)",
            "Dow": "44000 (-0.05%)",
            "Russell 2000": "2200 (+0.10%)",
            "VIX": "15.2",
            "10Y美债": "4.20%",
            "WTI/黄金": "WTI 74 / 黄金 2360",
            "AI/半导体": "Nvidia 与费半偏强",
        },
        korea={
            "KOSPI": "2800 (+0.40%)",
            "KOSDAQ": "850 (+0.20%)",
            "Samsung": "76000 (+0.50%)",
            "SK Hynix": "210000 (+1.10%)",
            "外资流向": "小幅净流入",
            "半导体/存储链条": "存储价格预期偏强",
        },
        japan={"Nikkei": "39000 (+0.10%)", "TOPIX": "2780 (+0.05%)", "日元/BOJ": "日元弱势"},
        variables={"美元": "偏强", "人民币": "7.18", "美债": "4.20%", "油价": "74", "黄金": "2360", "VIX": "15.2"},
    )
    news = [
        market.MarketNewsItem(
            title="Nvidia lifts semiconductor risk appetite",
            source="Reuters",
            published_at=as_of,
            market_tags=["us_equities", "semiconductors"],
            impact_type=["AI", "半导体"],
            impact_score=4,
            direction="bullish",
            reason="牵动 AI 与半导体链条。",
        )
    ]
    return market.MarketBrief(
        as_of=as_of,
        window_label="2026-05-25 09:00 至 2026-05-25 17:00 中国时间",
        slot=slot,
        dashboard=dash,
        news=news,
        good_signs=["半导体链条仍有承接。"],
        bad_signs=["美元和美债仍压估值。"],
        main_line="主线看半导体和美元美债拔河。",
        vela_judgment=["别把反弹叫胜利，先看成交和美债。"],
        watch_next=["10Y美债", "离岸人民币", "Samsung/SK Hynix"],
    )


if __name__ == "__main__":
    unittest.main()
