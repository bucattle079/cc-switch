from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"
REALTIME_INFO = TOOLS / "vela_realtime_info.py"


def load_module(path: Path, name: str):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeHttpResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class VelaRealtimeInfoTests(unittest.TestCase):
    def test_time_query_uses_timezone_calculation_not_dialogue_template(self):
        info = load_module(REALTIME_INFO, "vela_realtime_info")
        fixed = datetime(2026, 6, 2, 10, 30, tzinfo=timezone.utc)

        reply = info.render_time_query_reply("现在美国时间纽约约是几点", now_utc=fixed)

        self.assertIn("纽约", reply)
        self.assertIn("06:30", reply)
        self.assertIn("UTC-04:00", reply)
        for token in ["DeepSeek API", "信息不用铺满", "你慢慢说", "先说最烦的点"]:
            self.assertNotIn(token, reply)

    def test_weather_query_uses_live_forecast_payload_not_boundary_template(self):
        info = load_module(REALTIME_INFO, "vela_realtime_info")
        fixed = datetime(2026, 6, 2, 10, 30, tzinfo=timezone.utc)
        payload = {
            "daily": {
                "time": ["2026-06-03"],
                "weather_code": [61],
                "temperature_2m_max": [30.4],
                "temperature_2m_min": [24.2],
                "precipitation_probability_max": [70],
                "wind_speed_10m_max": [18.5],
            }
        }

        with patch.object(info.urllib.request, "urlopen", return_value=FakeHttpResponse(payload)):
            reply = info.render_weather_query_reply("明天泉州天气如何", now_utc=fixed)

        self.assertIn("泉州", reply)
        self.assertIn("明天", reply)
        self.assertIn("实时天气源：已接入", reply)
        self.assertIn("24-30°C", reply)
        self.assertIn("降雨概率约70%", reply)
        self.assertIn("判断：", reply)
        self.assertIn("下一步：", reply)
        for token in ["不编实时天气", "天气实时数据不可用", "要精确预报请看本机天气源"]:
            self.assertNotIn(token, reply)

    def test_weather_query_family_uses_location_and_day_semantics(self):
        info = load_module(REALTIME_INFO, "vela_realtime_info_family")
        fixed = datetime(2026, 6, 2, 10, 30, tzinfo=timezone.utc)
        payload = {
            "daily": {
                "time": ["2026-06-03"],
                "weather_code": [2],
                "temperature_2m_max": [28.0],
                "temperature_2m_min": [21.0],
                "precipitation_probability_max": [20],
                "wind_speed_10m_max": [12.0],
            }
        }

        cases = [
            ("明天泉州天气如何", "泉州", "明天"),
            ("明天晋江会不会下雨", "晋江", "明天"),
            ("今天纽约冷吗，出门要不要加外套", "纽约", "今天"),
        ]

        with patch.object(info.urllib.request, "urlopen", return_value=FakeHttpResponse(payload)):
            for text, location, day in cases:
                with self.subTest(text):
                    reply = info.render_weather_query_reply(text, now_utc=fixed)

                    self.assertIn(location, reply)
                    self.assertIn(day, reply)
                    self.assertIn("实时天气源：已接入", reply)
                    self.assertIn("21-28°C", reply)
                    self.assertIn("判断：", reply)
                    for token in ["不编实时天气", "天气实时数据不可用", "客套", "DeepSeek API"]:
                        self.assertNotIn(token, reply)


if __name__ == "__main__":
    unittest.main()
