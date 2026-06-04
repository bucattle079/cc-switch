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

    def test_weather_connector_without_key_returns_unavailable_boundary(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_weather_no_key")

        result = rt.build_realtime_evidence("天气怎么样", "weather_query")

        self.assertTrue(result.plan.source_need)
        self.assertEqual(result.plan.source_type, ["weather"])
        self.assertTrue(result.packets)
        packet = result.packets[0]
        self.assertEqual(packet.source_type, "weather")
        self.assertEqual(packet.freshness_status, rt.FRESH_UNAVAILABLE)
        self.assertIn("weather_provider_not_configured", packet.known_limits)
        self.assertIn("没接入真实天气源", result.frontstage_boundary)
        for raw in [
            "provider_not_configured",
            "connector_unavailable",
            "real_time_source_available=false",
            "cached_summary_available=false",
            "source_type",
            "evidence_id",
        ]:
            self.assertNotIn(raw, result.frontstage_boundary)

    def test_weather_connector_with_weatherapi_key_builds_weather_evidence_packet(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_weatherapi")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                payload = {
                    "location": {
                        "name": "New York",
                        "country": "United States",
                        "localtime": "2026-06-04 09:10",
                    },
                    "current": {
                        "temp_c": 16.2,
                        "condition": {"text": "多云"},
                        "wind_kph": 12.4,
                        "humidity": 62,
                        "last_updated": "2026-06-04 09:00",
                    },
                    "forecast": {
                        "forecastday": [
                            {
                                "date": "2026-06-04",
                                "day": {
                                    "mintemp_c": 13.0,
                                    "maxtemp_c": 19.0,
                                    "daily_chance_of_rain": 20,
                                    "daily_chance_of_snow": 0,
                                    "maxwind_kph": 14.0,
                                    "avghumidity": 60,
                                    "condition": {"text": "多云"},
                                },
                            },
                            {
                                "date": "2026-06-05",
                                "day": {
                                    "mintemp_c": 14.0,
                                    "maxtemp_c": 20.0,
                                    "daily_chance_of_rain": 70,
                                    "daily_chance_of_snow": 0,
                                    "maxwind_kph": 18.0,
                                    "avghumidity": 68,
                                    "condition": {"text": "小雨"},
                                },
                            },
                        ]
                    },
                }
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")

        with patch.dict(
            "os.environ",
            {
                "VELA_LEARNING_LOOP_DIR": str(Path(self.temp_dir.name) / "learning-loop"),
                "VELA_WEATHER_PROVIDER": "weatherapi",
                "VELA_WEATHER_API_KEY": "test-weather-key",
            },
            clear=True,
        ):
            with patch.object(rt.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen:
                result = rt.build_realtime_evidence("明天纽约会下雨吗", "weather_query")

        self.assertEqual(urlopen.call_count, 1)
        self.assertTrue(result.packets)
        packet = result.packets[0]
        self.assertEqual(packet.freshness_status, rt.FRESH_REALTIME)
        packet_dict = packet.to_dict()
        for key in [
            "location",
            "temperature",
            "condition",
            "precipitation_probability",
            "wind",
            "humidity",
            "forecast_window",
            "source_url_or_origin",
            "confidence_level",
            "known_limits",
        ]:
            self.assertIn(key, packet_dict)
        self.assertIn("纽约", packet.key_values["location"])
        self.assertIn("70%", packet.key_values["precipitation_probability"])
        self.assertIn("纽约", result.frontstage_boundary)
        self.assertIn("降雨概率", result.frontstage_boundary)
        self.assertNotIn("source_type", result.frontstage_boundary)
        self.assertNotIn("provider_not_configured", result.frontstage_boundary)

    def test_weather_connector_with_provider_but_no_location_asks_for_city_without_fetching(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_weather_location_required")

        with patch.dict(
            "os.environ",
            {
                "VELA_LEARNING_LOOP_DIR": str(Path(self.temp_dir.name) / "learning-loop"),
                "VELA_WEATHER_PROVIDER": "weatherapi",
                "VELA_WEATHER_API_KEY": "test-weather-key",
            },
            clear=True,
        ):
            with patch.object(rt.urllib.request, "urlopen") as urlopen:
                result = rt.build_realtime_evidence("天气怎么样", "weather_query")

        self.assertEqual(urlopen.call_count, 0)
        self.assertTrue(result.packets)
        packet = result.packets[0]
        self.assertEqual(packet.freshness_status, rt.FRESH_UNAVAILABLE)
        self.assertIn("weather_location_required", packet.known_limits)
        self.assertIn("先给地点", result.frontstage_boundary)
        self.assertNotIn("北京", result.frontstage_boundary)
        self.assertNotIn("source_type", result.frontstage_boundary)

    def test_router_weather_with_mock_provider_gives_natural_advice_without_engineering_fields(self):
        router = load_module(ROUTER, "vela_router_weather_natural")
        rt_module = sys.modules["vela_realtime_intelligence"]

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                payload = {
                    "location": {"name": "New York", "country": "United States", "localtime": "2026-06-04 08:30"},
                    "current": {
                        "temp_c": 8.4,
                        "condition": {"text": "小雨"},
                        "wind_kph": 22.0,
                        "humidity": 74,
                        "last_updated": "2026-06-04 08:15",
                    },
                    "forecast": {
                        "forecastday": [
                            {
                                "date": "2026-06-04",
                                "day": {
                                    "mintemp_c": 7.0,
                                    "maxtemp_c": 12.0,
                                    "daily_chance_of_rain": 65,
                                    "daily_chance_of_snow": 0,
                                    "maxwind_kph": 24.0,
                                    "avghumidity": 76,
                                    "condition": {"text": "小雨"},
                                },
                            }
                        ]
                    },
                }
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")

        with patch.dict(
            "os.environ",
            {
                "VELA_LEARNING_LOOP_DIR": str(Path(self.temp_dir.name) / "learning-loop"),
                "VELA_WEATHER_PROVIDER": "weatherapi",
                "VELA_WEATHER_API_KEY": "test-weather-key",
                "VELA_DEFAULT_WEATHER_LOCATION": "纽约",
            },
            clear=True,
        ):
            with patch.object(rt_module.urllib.request, "urlopen", return_value=FakeResponse()):
                reply = router.reply_for("今天适合出门吗")

        self.assertIn("纽约", reply)
        self.assertIn("出门", reply)
        self.assertIn("降雨概率", reply)
        for raw in [
            "source_type",
            "evidence_id",
            "provider_not_configured",
            "connector_unavailable",
            "real_time_source_available",
            "cached_summary_available",
            "schema",
            "raw payload",
        ]:
            self.assertNotIn(raw, reply)

    def test_current_vix_still_routes_to_market_data(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_vix_pollution")

        result = rt.build_realtime_evidence("现在 VIX 是多少", "market_brief")

        self.assertIn("market_data", result.plan.source_type)
        self.assertNotIn("weather", result.plan.source_type)

    def test_source_planner_maps_financial_realtime_to_market_news_and_web(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_finance_sources")

        for message in ["美元人民币汇率现在多少", "目前 VIX 是否正常？", "今天市场能不能加仓"]:
            with self.subTest(message):
                plan = rt.plan_sources(message, "market_brief")

                self.assertTrue(plan.source_need)
                self.assertIn("market_data", plan.source_type)
                self.assertIn("news", plan.source_type)
                self.assertIn("web_search", plan.source_type)
                self.assertEqual(plan.freshness_requirement, "real_time")

    def test_market_connector_without_provider_returns_structured_capability_boundary(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_market_no_provider")

        result = rt.build_realtime_evidence("美元人民币汇率现在多少", "market_brief")

        self.assertTrue(result.packets)
        market_packet = next(packet for packet in result.packets if packet.source_type == "market_data")
        self.assertEqual(market_packet.freshness_status, rt.FRESH_UNAVAILABLE)
        self.assertIn("market_provider_not_configured", market_packet.known_limits)
        for token in ["当前可用数据", "不可用数据", "可判断部分", "不能确定部分", "下一步"]:
            self.assertIn(token, result.frontstage_boundary)
        self.assertNotRegex(result.frontstage_boundary, r"(美元|人民币|VIX)[^\n]{0,12}\d{1,3}(?:\.\d+)?")
        for raw in ["source_type", "evidence_id", "provider_not_configured", "real_time_source_available"]:
            self.assertNotIn(raw, result.frontstage_boundary)

    def test_market_connector_with_alpha_vantage_fx_builds_evidence_packet(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_market_alpha_fx")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                payload = {
                    "Realtime Currency Exchange Rate": {
                        "1. From_Currency Code": "USD",
                        "2. From_Currency Name": "United States Dollar",
                        "3. To_Currency Code": "CNY",
                        "4. To_Currency Name": "Chinese Yuan",
                        "5. Exchange Rate": "7.18320000",
                        "6. Last Refreshed": "2026-06-04 02:20:00",
                        "7. Time Zone": "UTC",
                    }
                }
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")

        with patch.dict(
            "os.environ",
            {
                "VELA_LEARNING_LOOP_DIR": str(Path(self.temp_dir.name) / "learning-loop"),
                "VELA_MARKET_PROVIDER": "alpha_vantage",
                "VELA_MARKET_API_KEY": "test-market-key",
            },
            clear=True,
        ):
            with patch.object(rt.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen:
                result = rt.build_realtime_evidence("美元人民币汇率现在多少", "market_brief")

        self.assertGreaterEqual(urlopen.call_count, 1)
        market_packet = next(packet for packet in result.packets if packet.source_type == "market_data")
        self.assertEqual(market_packet.freshness_status, rt.FRESH_REALTIME)
        self.assertIn("美元/人民币", market_packet.key_values["instrument"])
        self.assertIn("7.1832", market_packet.key_values["value"])
        self.assertIn("2026-06-04", market_packet.key_values["as_of"])
        self.assertNotIn("test-market-key", market_packet.source_url_or_origin)
        self.assertIn("数据时间", result.frontstage_boundary)
        self.assertIn("辅助判断", result.frontstage_boundary)

    def test_life_information_query_plans_web_and_news_without_weather_pollution(self):
        rt = load_module(REALTIME, "vela_realtime_intelligence_life_sources")

        plan = rt.plan_sources("附近生活资讯/出门建议", "daily_info")

        self.assertTrue(plan.source_need)
        self.assertIn("web_search", plan.source_type)
        self.assertIn("news", plan.source_type)
        self.assertNotIn("weather", plan.source_type)

    def test_deepseek_search_boundary_and_identity_routes_stay_out_of_weather(self):
        router = load_module(ROUTER, "vela_router_weather_pollution")

        search_reply = router.reply_for("DeepSeek API 为什么不能自己搜")
        identity_reply = router.reply_for("VELA 和 DeepSeek / Codex / 记忆是什么关系")

        self.assertIn("DeepSeek", search_reply)
        self.assertTrue(any(token in search_reply for token in ["外部", "检索", "搜索", "资料源"]), search_reply)
        self.assertIn("DeepSeek", identity_reply)
        self.assertIn("Codex", identity_reply)
        self.assertIn("记忆", identity_reply)
        for reply in [search_reply, identity_reply]:
            self.assertNotIn("天气源", reply)
            self.assertNotIn("source_type", reply)


if __name__ == "__main__":
    unittest.main()
