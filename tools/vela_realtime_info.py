from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from urllib.parse import urlencode
import urllib.request
from zoneinfo import ZoneInfo


WEATHER_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class Location:
    label: str
    latitude: float
    longitude: float
    timezone_name: str


CITY_LOCATIONS: tuple[tuple[str, Location], ...] = (
    ("泉州", Location("泉州", 24.8741, 118.6757, "Asia/Shanghai")),
    ("晋江", Location("晋江", 24.7814, 118.5511, "Asia/Shanghai")),
    ("纽约", Location("纽约", 40.7128, -74.0060, "America/New_York")),
    ("new york", Location("纽约", 40.7128, -74.0060, "America/New_York")),
    ("北京", Location("北京", 39.9042, 116.4074, "Asia/Shanghai")),
    ("上海", Location("上海", 31.2304, 121.4737, "Asia/Shanghai")),
    ("东京", Location("东京", 35.6764, 139.6500, "Asia/Tokyo")),
    ("首尔", Location("首尔", 37.5665, 126.9780, "Asia/Seoul")),
    ("伦敦", Location("伦敦", 51.5072, -0.1276, "Europe/London")),
    ("洛杉矶", Location("洛杉矶", 34.0522, -118.2437, "America/Los_Angeles")),
    ("los angeles", Location("洛杉矶", 34.0522, -118.2437, "America/Los_Angeles")),
)


TIMEZONE_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("纽约", "纽约", "America/New_York"),
    ("new york", "纽约", "America/New_York"),
    ("美东", "美东", "America/New_York"),
    ("美国东部", "美东", "America/New_York"),
    ("美国时间", "纽约", "America/New_York"),
    ("洛杉矶", "洛杉矶", "America/Los_Angeles"),
    ("美西", "美西", "America/Los_Angeles"),
    ("北京", "北京", "Asia/Shanghai"),
    ("中国", "北京", "Asia/Shanghai"),
    ("东京", "东京", "Asia/Tokyo"),
    ("日本", "东京", "Asia/Tokyo"),
    ("首尔", "首尔", "Asia/Seoul"),
    ("韩国", "首尔", "Asia/Seoul"),
    ("伦敦", "伦敦", "Europe/London"),
    ("英国", "伦敦", "Europe/London"),
)


WEATHER_CODE_TEXT = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "有雾",
    48: "有雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "冻毛毛雨",
    57: "较强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "较强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "较强阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "强雷阵雨伴冰雹",
}


def _timeout_seconds() -> float:
    raw = str(os.environ.get("VELA_WEATHER_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return 6.0
    try:
        value = float(raw)
    except ValueError:
        return 6.0
    return min(max(value, 2.0), 12.0)


def _now_utc(now_utc: datetime | None = None) -> datetime:
    if now_utc is None:
        return datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(timezone.utc)


def _compact(text: str) -> str:
    return " ".join(str(text or "").strip().split()).lower()


def location_for_weather(text: str) -> Location:
    lowered = _compact(text)
    for marker, location in CITY_LOCATIONS:
        if marker.lower() in lowered:
            return location
    return Location("这个位置", 39.9042, 116.4074, "Asia/Shanghai")


def weather_target_date(text: str, location: Location, now_utc: datetime | None = None) -> tuple[str, datetime]:
    local_now = _now_utc(now_utc).astimezone(ZoneInfo(location.timezone_name))
    raw = str(text or "")
    if "后天" in raw:
        return "后天", local_now + timedelta(days=2)
    if "明天" in raw:
        return "明天", local_now + timedelta(days=1)
    return "今天", local_now


def _fmt_number(value: object, *, digits: int = 0) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "未知"
    if digits <= 0:
        return str(int(round(num)))
    return f"{num:.{digits}f}"


def _weather_description(code: object) -> str:
    try:
        key = int(code)
    except (TypeError, ValueError):
        return "天气码未知"
    return WEATHER_CODE_TEXT.get(key, f"天气码{key}")


def fetch_weather_forecast(location: Location, target_date: datetime) -> dict:
    date_text = target_date.date().isoformat()
    params = {
        "latitude": f"{location.latitude:.4f}",
        "longitude": f"{location.longitude:.4f}",
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "wind_speed_10m_max",
            ]
        ),
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "timezone": "auto",
        "start_date": date_text,
        "end_date": date_text,
    }
    url = f"{WEATHER_FORECAST_URL}?{urlencode(params)}"
    with urllib.request.urlopen(url, timeout=_timeout_seconds()) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("weather_payload_not_object")
    return payload


def _daily_value(daily: dict, key: str) -> object:
    values = daily.get(key)
    if isinstance(values, list) and values:
        return values[0]
    return None


def render_weather_query_reply(text: str, *, now_utc: datetime | None = None) -> str:
    location = location_for_weather(text)
    day_label, target = weather_target_date(text, location, now_utc=now_utc)
    try:
        payload = fetch_weather_forecast(location, target)
        daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
        description = _weather_description(_daily_value(daily, "weather_code"))
        temp_min = _fmt_number(_daily_value(daily, "temperature_2m_min"))
        temp_max = _fmt_number(_daily_value(daily, "temperature_2m_max"))
        rain = _fmt_number(_daily_value(daily, "precipitation_probability_max"))
        wind = _fmt_number(_daily_value(daily, "wind_speed_10m_max"))
        rain_judgment = "雨具要带，行程别压太死。" if rain != "未知" and int(rain) >= 40 else "可正常安排，临近出门再确认一次。"
        return (
            f"K，{location.label}{day_label}实时天气源：已接入；{description}，{temp_min}-{temp_max}°C，"
            f"降雨概率约{rain}%，最大风速约{wind}km/h。\n"
            f"判断：{rain_judgment}\n"
            "下一步：出门前再看一次临近预报，重点盯降雨和风；天气这东西最爱临场翻脸，别给它表演空间。"
        )
    except Exception:
        return (
            f"K，{location.label}{day_label}实时天气源：暂不可用。\n"
            "判断：这轮不编温度、降雨概率或精确预报；只能按出行风险保守处理。\n"
            "下一步：稍后重试天气源；出门先按有雨和温差处理，别把空白数据当好运。"
        )


def timezone_for_time_query(text: str) -> tuple[str, str]:
    lowered = _compact(text)
    for marker, label, timezone_name in TIMEZONE_ALIASES:
        if marker.lower() in lowered:
            return label, timezone_name
    return "北京", "Asia/Shanghai"


def _utc_offset_text(dt: datetime) -> str:
    offset = dt.utcoffset()
    if offset is None:
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def render_time_query_reply(text: str, *, now_utc: datetime | None = None) -> str:
    label, timezone_name = timezone_for_time_query(text)
    local = _now_utc(now_utc).astimezone(ZoneInfo(timezone_name))
    date_text = local.strftime("%Y-%m-%d")
    time_text = local.strftime("%H:%M")
    offset = _utc_offset_text(local)
    return (
        f"K，{label}现在约 {time_text}（{date_text}，{offset}）。\n"
        "判断：这是按本地时区直接计算的当前时间，不拿闲聊模板冒充答案。"
    )
