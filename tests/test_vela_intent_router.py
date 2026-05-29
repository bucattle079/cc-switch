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


def load_module(path: Path, name: str):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaIntentRouterTests(unittest.TestCase):
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

            self.assertEqual(intent.name, "memory_related", text)
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

    def test_route_decision_is_structured_and_not_final_reply(self):
        router = load_module(ROUTER, "vela_router")

        decision = router.route_decision("今天A股怎么看")
        payload = decision.to_dict()

        self.assertEqual(payload["intent"], "market_brief")
        self.assertTrue(payload["needs_retrieval"])
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
        self.assertIn("data_status", reply)
        self.assertIn("last_updated", reply)
        self.assertIn("source_type", reply)
        self.assertNotIn("Market & World Briefing", reply)

    def test_refresh_market_question_uses_refresh_lane_without_blocking(self):
        router = load_module(ROUTER, "vela_router")

        intent = router.classify_intent("刷新最新市场资讯")

        self.assertEqual(intent.name, "market_refresh")
        self.assertTrue(intent.market_allowed)
        started = time.perf_counter()
        reply = router.reply_for("刷新最新市场资讯")
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 2.0)
        self.assertIn("实时检索链路", reply)
        self.assertIn("不返回缓存简报", reply)
        self.assertNotIn("以下基于最近缓存", reply)
        self.assertNotIn("VELA 市场简报", reply)
        self.assertNotIn("Market & World Briefing", reply)

    def test_explicit_realtime_retrieval_request_does_not_return_cached_brief(self):
        router = load_module(ROUTER, "vela_router")
        text = "OK 明白了，开启检索，我需要实时的资讯"

        intent = router.classify_intent(text)
        reply = router.reply_for(text)

        self.assertEqual(intent.name, "market_refresh")
        self.assertIn("实时检索链路", reply)
        self.assertIn("不返回缓存简报", reply)
        self.assertNotIn("以下基于最近缓存", reply)
        self.assertNotIn("VELA 市场简报", reply)

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

    def test_plain_vela_keeps_fast_fallback_ping(self):
        router = load_module(ROUTER, "vela_router")

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test-secret"}, clear=True):
            with patch.object(router, "run_layered_response", return_value=SimpleNamespace(text="K real")) as run:
                router.reply_for("VELA")

        self.assertEqual(run.call_args.kwargs["reply_adapter"].name, "fallback")

    def test_non_realtime_news_summary_uses_cache_status_before_brief(self):
        router = load_module(ROUTER, "vela_router")

        reply = router.reply_for("如果不是实时的重要资讯梳理给我")

        self.assertIn("以下基于最近缓存", reply)
        self.assertIn("data_status", reply)
        self.assertIn("VELA", reply)
        self.assertNotIn("direction:", reply)
        self.assertNotIn("score:", reply)

    def test_response_hash_guard_blocks_duplicate_candidates(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
            first = router.claim_response_once(
                "same reply",
                "market_refresh",
                state_dir=Path(tmp),
                ttl_seconds=30,
            )
            second = router.claim_response_once(
                "same reply",
                "market_refresh",
                state_dir=Path(tmp),
                ttl_seconds=30,
            )

        self.assertTrue(first)
        self.assertFalse(second)


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

    def test_router_send_once_claim_blocks_duplicate_content(self):
        router = load_module(ROUTER, "vela_router")
        with tempfile.TemporaryDirectory() as tmp:
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
        self.assertIn("last_updated", text)
        self.assertIn("source_type", text)
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
