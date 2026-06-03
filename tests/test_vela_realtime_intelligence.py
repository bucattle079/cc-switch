from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import json


TOOLS = Path(__file__).resolve().parents[1] / "tools"
REALTIME = TOOLS / "vela_realtime_intelligence.py"
ROUTER = TOOLS / "vela_router.py"


def load_module(path: Path, name: str):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaRealtimeIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patcher = patch.dict(
            "os.environ",
            {"VELA_LEARNING_LOOP_DIR": str(Path(self.temp_dir.name) / "learning-loop")},
            clear=True,
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def test_source_planner_maps_vix_to_market_data_realtime_need(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence")

        plan = rt.plan_sources("现在 VIX 是多少？", "market_brief")

        self.assertTrue(plan.source_need)
        self.assertIn("market_data", plan.source_type)
        self.assertEqual(plan.freshness_requirement, "real_time")
        self.assertTrue(plan.should_warn_if_unavailable)
        self.assertTrue(plan.should_use_cache)

    def test_source_planner_maps_storage_light_module_to_news_and_market(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_storage")

        plan = rt.plan_sources("帮我查一下今天存储和光模块的市场讨论度。", "market_brief")

        self.assertTrue(plan.source_need)
        self.assertIn("news", plan.source_type)
        self.assertIn("web_search", plan.source_type)
        self.assertIn("market_data", plan.source_type)
        self.assertEqual(plan.freshness_requirement, "real_time")

    def test_source_planner_maps_storage_light_module_without_punctuation_to_news_and_market(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_storage_no_punct")

        plan = rt.plan_sources("帮我查一下今天存储和光模块的市场讨论度", "market_brief")

        self.assertTrue(plan.source_need)
        self.assertIn("news", plan.source_type)
        self.assertIn("web_search", plan.source_type)
        self.assertIn("market_data", plan.source_type)
        self.assertEqual(plan.freshness_requirement, "real_time")

    def test_source_planner_default_source_types_are_domain_agnostic(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_sources")

        self.assertEqual(
            set(rt.DEFAULT_SOURCE_TYPES),
            {
                "web_search",
                "news",
                "market_data",
                "weather",
                "local_memory",
                "local_files",
                "user_uploaded_context",
                "generic_tool_connector",
            },
        )
        for connector in rt.default_connectors():
            self.assertIn(connector.source_type, rt.DEFAULT_SOURCE_TYPES)

    def test_source_planner_does_not_route_vertical_business_sources_by_default(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_generic")

        plan = rt.plan_sources("继续 AugSun 广告分析。", "daily_info")

        for source in ["amazon_ads", "seller_sprite_mcp", "gmail_import", "business_data"]:
            self.assertNotIn(source, plan.source_type)

    def test_web_news_connector_without_key_returns_unavailable_boundary(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_no_search_key")

        result = rt.build_realtime_evidence("现在小米汽车有什么公告", "daily_info")

        self.assertTrue(result.plan.source_need)
        self.assertIn("web_search", result.plan.source_type)
        self.assertIn("news", result.plan.source_type)
        self.assertTrue(result.packets)
        for packet in result.packets:
            self.assertEqual(packet.freshness_status, rt.FRESH_UNAVAILABLE)
            self.assertIn("search_provider_not_configured", packet.known_limits)
        self.assertIn("网页/新闻搜索源未接入", result.frontstage_boundary)
        self.assertNotIn("real_time_source_available", result.frontstage_boundary)
        self.assertNotIn("provider_not_configured", result.frontstage_boundary)

    def test_web_news_connector_with_serper_key_builds_evidence_packets(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_serper")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                payload = {
                    "organic": [
                        {
                            "title": "存储和光模块讨论度升温",
                            "snippet": "公开资料显示，AI 算力链带动存储与光模块关注度上升。",
                            "link": "https://example.com/a",
                            "date": "2026-06-03",
                            "source": "Example News",
                        }
                    ],
                    "news": [
                        {
                            "title": "光模块行业消息更新",
                            "snippet": "多家机构关注光模块订单与资本开支变化。",
                            "link": "https://example.com/b",
                            "date": "2026-06-03",
                            "source": "Example Finance",
                        }
                    ],
                }
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")

        with patch.dict(
            "os.environ",
            {
                "VELA_LEARNING_LOOP_DIR": str(Path(self.temp_dir.name) / "learning-loop"),
                "VELA_SEARCH_PROVIDER": "serper",
                "VELA_SEARCH_API_KEY": "test-key",
            },
            clear=True,
        ):
            with patch.object(rt.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen:
                result = rt.build_realtime_evidence("帮我查一下今天存储和光模块的市场讨论度。", "market_brief")

        self.assertGreaterEqual(len(result.packets), 2)
        self.assertTrue(any(packet.source_type == "web_search" for packet in result.packets))
        self.assertTrue(any(packet.source_type == "news" for packet in result.packets))
        self.assertTrue(any(packet.freshness_status == rt.FRESH_REALTIME for packet in result.packets))
        self.assertIn("存储", result.model_context)
        self.assertIn("光模块", result.model_context)
        self.assertNotIn("raw payload", result.frontstage_boundary)
        self.assertGreaterEqual(urlopen.call_count, 2)

    def test_evidence_packet_builder_uses_structured_fields_without_fake_realtime(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_packet")

        result = rt.build_realtime_evidence("现在 VIX 是多少？", "market_brief")

        self.assertTrue(result.plan.source_need)
        self.assertTrue(result.packets)
        packet = result.packets[0]
        self.assertIn(packet.freshness_status, {"cached_summary_available", "unavailable", "delayed_source_available"})
        self.assertNotEqual(packet.freshness_status, "real_time_source_available")
        self.assertIn("known_limits", packet.to_dict())
        self.assertIn("source_type", packet.to_dict())
        self.assertNotIn("当前 VIX 数值", result.frontstage_boundary)

    def test_router_vix_reply_does_not_invent_number_or_storage_topic(self):
        router = load_module(ROUTER, "vela_router_realtime_vix")

        reply = router.reply_for("现在 VIX 是多少？")

        self.assertIn("VIX", reply)
        self.assertIn("实时源", reply)
        self.assertTrue(any(token in reply for token in ["不能给", "暂不可用", "未接入"]), reply)
        self.assertNotRegex(reply, r"VIX[^\d\n]{0,8}\d{1,3}(?:\.\d+)?")
        self.assertNotIn("存储", reply)
        self.assertNotIn("光模块", reply)
        for raw in ["real_time_source_available", "cached_summary_available", "source_type", "evidence_id"]:
            self.assertNotIn(raw, reply)

    def test_router_augsun_ads_stays_out_of_default_business_source_routing(self):
        router = load_module(ROUTER, "vela_router_realtime_ads")

        intent = router.classify_intent("继续 AugSun 广告分析。")
        reply = router.reply_for("继续 AugSun 广告分析。")

        self.assertEqual(intent.name, "style_feedback")
        self.assertIn("context_quarantine", intent.focus_tags)
        for token in ["Amazon Ads", "SellerSprite", "business_data", "amazon_ads", "seller_sprite_mcp"]:
            self.assertNotIn(token, reply)
        for raw in ["source_type", "evidence_id", "raw payload", "schema"]:
            self.assertNotIn(raw, reply)

    def test_router_storage_light_module_discussion_uses_realtime_evidence_boundary(self):
        router = load_module(ROUTER, "vela_router_realtime_storage_reply")

        reply = router.reply_for("帮我查一下今天存储和光模块的市场讨论度。")

        self.assertIn("存储", reply)
        self.assertIn("光模块", reply)
        self.assertTrue(any(token in reply for token in ["新闻", "网页", "讨论度", "资料源", "实时源"]), reply)
        self.assertTrue(any(token in reply for token in ["不完整", "暂不可用", "不能", "缺口"]), reply)
        self.assertNotIn("A股仍按震荡修复处理", reply)
        for raw in ["source_type", "evidence_id", "raw payload", "schema"]:
            self.assertNotIn(raw, reply)

    def test_router_current_news_without_key_uses_search_connector_boundary(self):
        router = load_module(ROUTER, "vela_router_realtime_current_news")

        reply = router.reply_for("现在小米汽车有什么公告")

        self.assertIn("网页/新闻搜索源未接入", reply)
        self.assertNotIn("实时资讯源：暂未抓到高置信条目", reply)
        for raw in ["real_time_source_available", "provider_not_configured", "source_type", "evidence_id", "raw payload"]:
            self.assertNotIn(raw, reply)

    def test_weather_query_has_weather_source_plan(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_weather")

        plan = rt.plan_sources("天气怎么样？", "weather_query")

        self.assertTrue(plan.source_need)
        self.assertEqual(plan.source_type, ["weather"])
        self.assertEqual(plan.freshness_requirement, "real_time")


if __name__ == "__main__":
    unittest.main()
