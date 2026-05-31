import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import tomllib
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "vela_daily_briefing.py"
CONFIG = Path(r"C:\Users\Admin\.cc-connect\config.toml")


def load_module():
    spec = importlib.util.spec_from_file_location("vela_daily_briefing", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaDailyBriefingScriptTests(unittest.TestCase):
    def test_before_9am_uses_previous_evening_to_8am_window(self):
        briefing = load_module()

        start, end = briefing.briefing_window(
            datetime(2026, 5, 25, 8, 30, tzinfo=briefing.CHINA_TZ)
        )

        self.assertEqual(start.isoformat(), "2026-05-24T18:00:00+08:00")
        self.assertEqual(end.isoformat(), "2026-05-25T08:00:00+08:00")

    def test_9am_slot_uses_previous_evening_to_9am_window(self):
        briefing = load_module()

        start, end = briefing.briefing_window(
            datetime(2026, 5, 25, 9, 30, tzinfo=briefing.CHINA_TZ)
        )

        self.assertEqual(start.isoformat(), "2026-05-24T18:00:00+08:00")
        self.assertEqual(end.isoformat(), "2026-05-25T09:00:00+08:00")

    def test_before_1pm_uses_9am_cache_window(self):
        briefing = load_module()

        start, end = briefing.briefing_window(
            datetime(2026, 5, 25, 12, 30, tzinfo=briefing.CHINA_TZ)
        )

        self.assertEqual(start.isoformat(), "2026-05-24T18:00:00+08:00")
        self.assertEqual(end.isoformat(), "2026-05-25T09:00:00+08:00")

    def test_after_5pm_uses_current_day_to_5pm_window(self):
        briefing = load_module()

        start, end = briefing.briefing_window(
            datetime(2026, 5, 25, 17, 30, tzinfo=briefing.CHINA_TZ)
        )

        self.assertEqual(start.isoformat(), "2026-05-25T08:00:00+08:00")
        self.assertEqual(end.isoformat(), "2026-05-25T17:00:00+08:00")

    def test_between_1pm_and_5pm_uses_midday_window(self):
        briefing = load_module()

        start, end = briefing.briefing_window(
            datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        )

        self.assertEqual(start.isoformat(), "2026-05-25T08:00:00+08:00")
        self.assertEqual(end.isoformat(), "2026-05-25T12:00:00+08:00")

    def test_parse_google_news_rss_item_source_and_time(self):
        briefing = load_module()
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Oil falls as risk premium eases - Reuters</title>
            <link>https://news.google.com/rss/articles/example</link>
            <pubDate>Sun, 24 May 2026 23:30:00 GMT</pubDate>
            <source url="https://www.reuters.com">Reuters</source>
          </item>
        </channel></rss>
        """

        items = briefing.parse_rss(xml.encode("utf-8"), "markets")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "markets")
        self.assertEqual(items[0].source, "Reuters")
        self.assertEqual(items[0].published.isoformat(), "2026-05-25T07:30:00+08:00")

    def test_format_briefing_is_wechat_plain_text(self):
        briefing = load_module()
        start = datetime(2026, 5, 24, 18, 0, tzinfo=briefing.CHINA_TZ)
        end = datetime(2026, 5, 25, 8, 0, tzinfo=briefing.CHINA_TZ)
        items = [
            briefing.NewsItem(
                title="Oil falls as risk premium eases",
                source="Reuters",
                link="https://example.test/1",
                published=end,
                category="markets",
            )
        ]

        text = briefing.format_briefing(
            items,
            start,
            end,
            translations={"Oil falls as risk premium eases": "油价回落，风险溢价降温"},
        )

        self.assertIn("夜间简报｜2026-05-25", text)
        self.assertIn("军政 / 地缘", text)
        self.assertIn("金融 / 市场", text)
        self.assertIn("科技 / AI / 半导体", text)
        self.assertIn("油价回落，风险溢价降温。来源：Reuters", text)
        self.assertNotIn("Oil falls as risk premium eases", text)
        self.assertNotIn("意义：", text)
        self.assertIn("VELA 判断", text)
        self.assertIn("A股：", text)
        self.assertIn("美股：", text)
        self.assertIn("日本 / 韩国：", text)
        self.assertNotIn("```", text)
        self.assertNotIn("Traceback", text)

    def test_market_queries_focus_us_a_share_korea_and_japan(self):
        briefing = load_module()
        market_queries = " ".join(briefing.QUERY_GROUPS["markets"]).lower()

        self.assertIn("s&p", market_queries)
        self.assertIn("a-shares", market_queries)
        self.assertIn("kospi", market_queries)
        self.assertIn("nikkei", market_queries)

    def test_select_balanced_prefers_high_signal_tech_over_consumer_noise(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 7, 30, tzinfo=briefing.CHINA_TZ)
        items = [
            briefing.NewsItem(
                title="Tekken 8 DLC character announced",
                source="Gematsu",
                link="https://example.test/game",
                published=now,
                category="tech",
            ),
            briefing.NewsItem(
                title="Nvidia chip export rules reshape AI datacenter spending",
                source="Reuters",
                link="https://example.test/ai",
                published=now,
                category="tech",
            ),
        ]

        selected = briefing.select_balanced(items, 5)

        titles = [item.title for item in selected]
        self.assertIn("Nvidia chip export rules reshape AI datacenter spending", titles)
        self.assertNotIn("Tekken 8 DLC character announced", titles)

    def test_neutral_fill_prioritizes_markets_before_geopolitics(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        items = [
            briefing.NewsItem(
                title="Local politics live update",
                source="Example",
                link="https://example.test/politics",
                published=now,
                category="geopolitics",
            ),
            briefing.NewsItem(
                title="Midday desk note",
                source="Bloomberg",
                link="https://example.test/market",
                published=now,
                category="markets",
            ),
        ]

        selected = briefing.select_balanced(items, 1)

        self.assertEqual(selected[0].category, "markets")

    def test_market_story_is_recategorized_when_found_in_geopolitics_feed(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        item = briefing.NewsItem(
            title="Oil prices slide on hopes of US-Iran peace deal",
            source="BBC",
            link="https://example.test/oil",
            published=now,
            category="geopolitics",
        )

        normalized = briefing.recategorize_item(item)

        self.assertEqual(normalized.category, "markets")

    def test_low_value_social_noise_scores_negative(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        item = briefing.NewsItem(
            title="The byelection, Wes Streeting and Europe: your questions answered podcast",
            source="The Guardian",
            link="https://example.test/podcast",
            published=now,
            category="geopolitics",
        )

        self.assertLess(briefing.item_score(item), 0)

    def test_social_violence_noise_is_negative_even_in_market_feed(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        item = briefing.NewsItem(
            title="Bondi Beach gunman killed 11 people within 30 seconds",
            source="The Guardian",
            link="https://example.test/noise",
            published=now,
            category="markets",
        )

        self.assertLess(briefing.item_score(item), 0)

    def test_chinese_geopolitical_story_scores_positive(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        item = briefing.NewsItem(
            title="俄乌重大突发！俄罗斯使用高超音速导弹袭击乌克兰，基辅遭严重空袭",
            source="FX168",
            link="https://example.test/ukraine",
            published=now,
            category="geopolitics",
        )

        self.assertGreater(briefing.item_score(item), 0)

    def test_fertiliser_supply_story_scores_as_market_risk(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        item = briefing.NewsItem(
            title="Fertiliser groups cut production as Iran war squeezes sulphur supplies",
            source="Financial Times",
            link="https://example.test/fertiliser",
            published=now,
            category="markets",
        )

        self.assertGreater(briefing.item_score(item), 0)

    def test_luxury_consumer_noise_scores_negative_in_market_feed(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        item = briefing.NewsItem(
            title="$140,000 E.V.s and Heritage Gold: The Rise of China's Homegrown Luxury Market",
            source="The New York Times",
            link="https://example.test/luxury",
            published=now,
            category="markets",
        )

        self.assertLess(briefing.item_score(item), 0)

    def test_liveblog_noise_scores_negative(self):
        briefing = load_module()
        now = datetime(2026, 5, 25, 14, 30, tzinfo=briefing.CHINA_TZ)
        item = briefing.NewsItem(
            title="Oil prices fall to two-week lows - as it happened",
            source="The Guardian",
            link="https://example.test/live",
            published=now,
            category="markets",
        )

        self.assertLess(briefing.item_score(item), 0)

    def test_polish_chinese_title_removes_literal_repetition(self):
        briefing = load_module()

        self.assertEqual(
            briefing.polish_chinese_title("油价下跌因美伊和平协议的希望而下跌"),
            "美伊和平协议预期升温，油价回落",
        )

    def test_config_overrides_skill_with_local_exec_command(self):
        data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
        commands = {item["name"]: item for item in data.get("commands", [])}

        self.assertIn("vela-daily-briefing", commands)
        self.assertIn("vela_router.py", commands["vela-daily-briefing"]["exec"])
        self.assertIn("daily-briefing", commands["vela-daily-briefing"]["exec"])
        self.assertNotIn("vela_daily_briefing.py", commands["vela-daily-briefing"]["exec"])
        self.assertNotIn("--send", commands["vela-daily-briefing"]["exec"])
        self.assertNotIn("--detach", commands["vela-daily-briefing"]["exec"])


if __name__ == "__main__":
    unittest.main()
