from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlencode
import urllib.request


ROOT = Path(__file__).resolve().parents[1]

FRESH_REALTIME = "real_time_source_available"
FRESH_DELAYED = "delayed_source_available"
FRESH_CACHE = "cached_summary_available"
FRESH_MODEL_ONLY = "model_generated_only"
FRESH_UNAVAILABLE = "unavailable"

DEFAULT_SOURCE_TYPES = (
    "web_search",
    "news",
    "market_data",
    "weather",
    "local_memory",
    "local_files",
    "user_uploaded_context",
    "generic_tool_connector",
)

WEATHERAPI_FORECAST_URL = "https://api.weatherapi.com/v1/forecast.json"
ALPHA_VANTAGE_QUERY_URL = "https://www.alphavantage.co/query"
WEATHER_EVIDENCE_KEYS = (
    "location",
    "temperature",
    "condition",
    "precipitation_probability",
    "wind",
    "humidity",
    "forecast_window",
    "provider_updated_at",
)


@dataclass(frozen=True)
class SourcePlan:
    source_need: bool
    source_type: list[str] = field(default_factory=list)
    freshness_requirement: str = "none"
    acceptable_fallback: list[str] = field(default_factory=list)
    should_use_cache: bool = False
    should_warn_if_unavailable: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidencePacket:
    evidence_id: str
    source_name: str
    source_type: str
    retrieved_at: str
    freshness_status: str
    title: str
    summary: str
    key_values: dict[str, str] = field(default_factory=dict)
    source_url_or_origin: str = ""
    confidence_level: str = "medium"
    known_limits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.source_type == "weather":
            for key in WEATHER_EVIDENCE_KEYS:
                if key in self.key_values:
                    payload[key] = self.key_values[key]
        return payload


@dataclass(frozen=True)
class ConnectorRawResult:
    source_name: str
    source_type: str
    freshness_status: str
    title: str
    summary: str
    key_values: dict[str, str] = field(default_factory=dict)
    source_url_or_origin: str = ""
    confidence_level: str = "medium"
    known_limits: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarketTarget:
    label: str
    target_type: str
    symbol: str = ""
    from_currency: str = ""
    to_currency: str = ""


@dataclass(frozen=True)
class RealtimeEvidenceResult:
    plan: SourcePlan
    packets: list[EvidencePacket] = field(default_factory=list)
    frontstage_boundary: str = ""
    model_context: str = ""


class RetrievalConnector:
    source_type = "generic_tool_connector"
    source_name = "generic connector"

    def can_handle(self, source_type: str) -> bool:
        return source_type == self.source_type

    def fetch(self, query: str, freshness_requirement: str) -> ConnectorRawResult:
        return ConnectorRawResult(
            source_name=self.source_name,
            source_type=self.source_type,
            freshness_status=FRESH_UNAVAILABLE,
            title="资料源未接入",
            summary="这个资料源还没有配置真实 connector；不能把模型推断伪装成检索结果。",
            source_url_or_origin="local connector registry",
            confidence_level="high",
            known_limits=["connector_not_configured"],
        )

    def normalize(self, raw_result: ConnectorRawResult) -> ConnectorRawResult:
        return raw_result

    def build_evidence_packet(self, normalized_result: ConnectorRawResult, *, query: str) -> EvidencePacket:
        seed = "|".join(
            [
                normalized_result.source_type,
                normalized_result.title,
                query,
                normalized_result.freshness_status,
            ]
        )
        evidence_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        return EvidencePacket(
            evidence_id=evidence_id,
            source_name=normalized_result.source_name,
            source_type=normalized_result.source_type,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            freshness_status=normalized_result.freshness_status,
            title=normalized_result.title,
            summary=normalized_result.summary,
            key_values=normalized_result.key_values,
            source_url_or_origin=normalized_result.source_url_or_origin,
            confidence_level=normalized_result.confidence_level,
            known_limits=normalized_result.known_limits,
        )


class MarketDataConnector(RetrievalConnector):
    source_type = "market_data"
    source_name = "VELA market data boundary"

    def fetch(self, query: str, freshness_requirement: str) -> ConnectorRawResult:
        provider = str(os.environ.get("VELA_MARKET_PROVIDER") or "").strip().lower()
        api_key = str(os.environ.get("VELA_MARKET_API_KEY") or "").strip()
        if provider and api_key:
            target = _market_target_for_query(query)
            if target is None:
                return self._unavailable(
                    query,
                    "市场数据源已配置，但这条问题没有可直接查询的行情标的。",
                    ["market_instrument_not_mapped"],
                    include_cache=False,
                )
            if provider in {"alpha_vantage", "alphavantage"}:
                try:
                    payload = self._fetch_alpha_vantage(target, api_key)
                    return self._normalize_alpha_vantage(payload, target)
                except Exception as exc:
                    return ConnectorRawResult(
                        source_name="Alpha Vantage market data",
                        source_type=self.source_type,
                        freshness_status=FRESH_UNAVAILABLE,
                        title="市场数据源调用失败",
                        summary="已配置市场数据源，但这轮没有返回可用行情；不能把模型判断伪装成当前数值。",
                        key_values={"provider": "alpha_vantage", "error": type(exc).__name__},
                        source_url_or_origin="Alpha Vantage API",
                        confidence_level="medium",
                        known_limits=["market_provider_error"],
                    )
            return self._unavailable(
                query,
                "市场数据 provider 暂不支持；不能给当前行情数值。",
                ["market_provider_unsupported"],
                include_cache=False,
            )
        return self._unavailable(
            query,
            "当前未接入实时市场数据源；不能给当前行情数值。",
            ["market_provider_not_configured"],
            include_cache=True,
        )

    def _unavailable(
        self,
        query: str,
        summary: str,
        limits: list[str],
        *,
        include_cache: bool,
    ) -> ConnectorRawResult:
        key_values: dict[str, str] = {}
        status_text = FRESH_UNAVAILABLE
        if include_cache and not _market_requires_current_value(query):
            try:
                from vela_market_briefing import market_freshness_status

                status = market_freshness_status(query)
                if status.cached_summary_available:
                    status_text = FRESH_CACHE
                    key_values["cache_last_updated"] = status.last_updated
                elif status.model_generated_only:
                    status_text = FRESH_MODEL_ONLY
            except Exception as exc:
                key_values["status_error"] = type(exc).__name__
        target = _market_target_for_query(query)
        if target is not None:
            key_values["instrument"] = target.label
        elif _has_any(_compact(query), ["存储", "光模块"]):
            key_values["instrument"] = "存储/光模块讨论度"
        if "vix" in _compact(query):
            limits = _dedupe(limits + ["no_vix_realtime_value"])
        return ConnectorRawResult(
            source_name=self.source_name,
            source_type=self.source_type,
            freshness_status=status_text,
            title="市场数据源边界",
            summary=summary,
            key_values=key_values,
            source_url_or_origin="VELA market connector config",
            confidence_level="high",
            known_limits=limits,
        )

    def _fetch_alpha_vantage(self, target: MarketTarget, api_key: str) -> dict[str, Any]:
        if target.target_type == "fx":
            params = {
                "function": "CURRENCY_EXCHANGE_RATE",
                "from_currency": target.from_currency,
                "to_currency": target.to_currency,
                "apikey": api_key,
            }
        else:
            params = {"function": "GLOBAL_QUOTE", "symbol": target.symbol, "apikey": api_key}
        request = urllib.request.Request(f"{ALPHA_VANTAGE_QUERY_URL}?{urlencode(params)}", method="GET")
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("market_payload_not_object")
        return payload

    def _normalize_alpha_vantage(self, payload: dict[str, Any], target: MarketTarget) -> ConnectorRawResult:
        if target.target_type == "fx":
            data = payload.get("Realtime Currency Exchange Rate")
            if not isinstance(data, dict):
                return ConnectorRawResult(
                    source_name="Alpha Vantage market data",
                    source_type=self.source_type,
                    freshness_status=FRESH_UNAVAILABLE,
                    title=f"{target.label}汇率暂不可用",
                    summary="Alpha Vantage 没有返回可整理的实时汇率字段；不能给当前数值。",
                    key_values={"provider": "alpha_vantage", "instrument": target.label},
                    source_url_or_origin="Alpha Vantage API",
                    confidence_level="medium",
                    known_limits=["market_provider_payload_unusable"],
                )
            value = _clean_market_value(data.get("5. Exchange Rate"))
            as_of = str(data.get("6. Last Refreshed") or "").strip()
            timezone_text = str(data.get("7. Time Zone") or "").strip()
            if as_of and timezone_text:
                as_of = f"{as_of} {timezone_text}"
            key_values = {
                "provider": "alpha_vantage",
                "instrument": target.label,
                "value": value,
                "as_of": as_of or "provider reported",
                "data_time": as_of or "provider reported",
                "delay_status": "provider_reported; may be delayed",
            }
            return ConnectorRawResult(
                source_name="Alpha Vantage market data",
                source_type=self.source_type,
                freshness_status=FRESH_REALTIME,
                title=f"{target.label}当前汇率",
                summary=f"{target.label}当前汇率约为 {value}；仍需结合新闻、美元指数和风险资产表现判断。",
                key_values=key_values,
                source_url_or_origin="Alpha Vantage API",
                confidence_level="medium",
                known_limits=["provider_may_be_delayed", "not_investment_advice"],
            )
        data = payload.get("Global Quote")
        if not isinstance(data, dict):
            return ConnectorRawResult(
                source_name="Alpha Vantage market data",
                source_type=self.source_type,
                freshness_status=FRESH_UNAVAILABLE,
                title=f"{target.label}行情暂不可用",
                summary="Alpha Vantage 没有返回可整理的行情字段；不能给当前数值。",
                key_values={"provider": "alpha_vantage", "instrument": target.label},
                source_url_or_origin="Alpha Vantage API",
                confidence_level="medium",
                known_limits=["market_provider_payload_unusable"],
            )
        value = _clean_market_value(data.get("05. price"))
        latest_day = str(data.get("07. latest trading day") or "").strip()
        change_percent = str(data.get("10. change percent") or "").strip()
        key_values = {
            "provider": "alpha_vantage",
            "instrument": target.label,
            "value": value,
            "as_of": latest_day or "provider reported",
            "data_time": latest_day or "provider reported",
            "change_percent": change_percent,
            "delay_status": "provider_reported; may be delayed",
        }
        return ConnectorRawResult(
            source_name="Alpha Vantage market data",
            source_type=self.source_type,
            freshness_status=FRESH_REALTIME,
            title=f"{target.label}当前行情",
            summary=f"{target.label}当前价格约为 {value}；涨跌幅 {change_percent or '未返回'}。",
            key_values=key_values,
            source_url_or_origin="Alpha Vantage API",
            confidence_level="medium",
            known_limits=["provider_may_be_delayed", "not_investment_advice"],
        )


@dataclass(frozen=True)
class WeatherLocationTarget:
    label: str
    query: str

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "query": self.query}


WEATHER_LOCATION_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("晋江", "晋江", "24.7814,118.5511"),
    ("泉州", "泉州", "24.8741,118.6757"),
    ("纽约", "纽约", "40.7128,-74.0060"),
    ("new york", "纽约", "40.7128,-74.0060"),
    ("北京", "北京", "39.9042,116.4074"),
    ("上海", "上海", "31.2304,121.4737"),
    ("东京", "东京", "35.6764,139.6500"),
    ("首尔", "首尔", "37.5665,126.9780"),
    ("伦敦", "伦敦", "51.5072,-0.1276"),
    ("洛杉矶", "洛杉矶", "34.0522,-118.2437"),
    ("los angeles", "洛杉矶", "34.0522,-118.2437"),
)

WEATHER_LOCATION_STOP_PHRASES = (
    "天气怎么样",
    "天气如何",
    "会不会下雨",
    "会不会下雪",
    "会下雨吗",
    "会下雪吗",
    "今天",
    "明天",
    "后天",
    "现在",
    "当前",
    "目前",
    "此刻",
    "今晚",
    "早上",
    "上午",
    "中午",
    "下午",
    "晚上",
    "本周",
    "周末",
    "天气",
    "气温",
    "温度",
    "降雨",
    "下雨",
    "下雪",
    "冷不冷",
    "热不热",
    "冷吗",
    "热吗",
    "风大不大",
    "风大",
    "适不适合",
    "适合",
    "能不能",
    "要不要",
    "出门",
    "带伞",
    "外套",
    "客户",
    "行程",
    "影响",
    "多少",
    "怎么样",
    "如何",
    "吗",
)

WEATHER_GENERIC_LOCATION_WORDS = {"", "某地", "当地", "这里", "那边", "附近", "这个位置", "你那里"}


def _weather_alias_target(text: str) -> WeatherLocationTarget | None:
    lowered = str(text or "").lower()
    for marker, label, query in WEATHER_LOCATION_ALIASES:
        if marker.lower() in lowered:
            return WeatherLocationTarget(label=label, query=query)
    return None


def _weather_location_candidate(text: str) -> str:
    cleaned = re.sub(r"[？?！!，,。；;：:\s]+", "", str(text or "").strip())
    for phrase in WEATHER_LOCATION_STOP_PHRASES:
        cleaned = cleaned.replace(phrase, "")
    cleaned = cleaned.strip()
    if cleaned in WEATHER_GENERIC_LOCATION_WORDS:
        return ""
    if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,40}", cleaned):
        return cleaned
    if re.search(r"[\u4e00-\u9fff]", cleaned) and 1 < len(cleaned) <= 12:
        return cleaned
    return ""


def _weather_location_target(text: str) -> WeatherLocationTarget | None:
    alias_target = _weather_alias_target(text)
    if alias_target is not None:
        return alias_target
    default_location = str(os.environ.get("VELA_DEFAULT_WEATHER_LOCATION") or "").strip()
    if default_location:
        default_alias = _weather_alias_target(default_location)
        if default_alias is not None:
            return default_alias
        return WeatherLocationTarget(label=default_location, query=default_location)
    candidate = _weather_location_candidate(text)
    if candidate:
        return WeatherLocationTarget(label=candidate, query=candidate)
    return None


def _weather_day_index(text: str) -> tuple[int, str]:
    raw = str(text or "")
    if "后天" in raw:
        return 2, "后天"
    if "明天" in raw:
        return 1, "明天"
    return 0, "今天"


def _weather_timeout_seconds() -> float:
    raw = str(os.environ.get("VELA_WEATHER_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return 6.0
    try:
        value = float(raw)
    except ValueError:
        return 6.0
    return min(max(value, 2.0), 12.0)


def _fmt_weather_number(value: object, *, digits: int = 0) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "未知"
    if digits <= 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _weather_condition_text(current: dict[str, Any], day: dict[str, Any], day_index: int) -> str:
    source = current if day_index == 0 else day
    condition = source.get("condition") if isinstance(source.get("condition"), dict) else {}
    text = str(condition.get("text") or "").strip()
    if text:
        return text
    fallback = day.get("condition") if isinstance(day.get("condition"), dict) else {}
    return str(fallback.get("text") or "未知").strip() or "未知"


def _weather_temperature_text(current: dict[str, Any], day: dict[str, Any], day_index: int) -> str:
    low = _fmt_weather_number(day.get("mintemp_c"), digits=0)
    high = _fmt_weather_number(day.get("maxtemp_c"), digits=0)
    range_text = "" if low == "未知" or high == "未知" else f"{low}-{high}°C"
    if day_index == 0:
        current_temp = _fmt_weather_number(current.get("temp_c"), digits=1)
        if current_temp != "未知" and range_text:
            return f"{current_temp}°C（今日{range_text}）"
        if current_temp != "未知":
            return f"{current_temp}°C"
    return range_text or "未知"


def _weather_precipitation_text(day: dict[str, Any]) -> str:
    rain = _fmt_weather_number(day.get("daily_chance_of_rain"), digits=0)
    snow = _fmt_weather_number(day.get("daily_chance_of_snow"), digits=0)
    if rain == "未知" and snow == "未知":
        return "未知"
    if snow != "未知" and int(snow) > max(int(rain) if rain != "未知" else 0, 0):
        return f"{snow}%（降雪）"
    return f"{rain if rain != '未知' else snow}%"


def _weather_wind_text(current: dict[str, Any], day: dict[str, Any], day_index: int) -> str:
    value = current.get("wind_kph") if day_index == 0 and current.get("wind_kph") is not None else day.get("maxwind_kph")
    wind = _fmt_weather_number(value, digits=0)
    return "未知" if wind == "未知" else f"{wind} km/h"


def _weather_humidity_text(current: dict[str, Any], day: dict[str, Any], day_index: int) -> str:
    value = current.get("humidity") if day_index == 0 and current.get("humidity") is not None else day.get("avghumidity")
    humidity = _fmt_weather_number(value, digits=0)
    return "未知" if humidity == "未知" else f"{humidity}%"


class WeatherConnector(RetrievalConnector):
    source_type = "weather"
    source_name = "WeatherAPI.com forecast"

    def fetch(self, query: str, freshness_requirement: str) -> ConnectorRawResult:
        provider = str(os.environ.get("VELA_WEATHER_PROVIDER") or "").strip().lower()
        api_key = str(os.environ.get("VELA_WEATHER_API_KEY") or "").strip()
        if not provider or not api_key:
            return self._unavailable(
                "真实天气源未接入",
                "未配置 VELA_WEATHER_PROVIDER / VELA_WEATHER_API_KEY；不能生成实时天气。",
                ["weather_provider_not_configured"],
            )
        if provider not in {"weatherapi", "weatherapi.com"}:
            return self._unavailable(
                "天气 provider 暂不支持",
                "当前 weather connector 只支持 WeatherAPI.com；不把未支持 provider 冒充可用。",
                ["weather_provider_unsupported"],
            )
        target = _weather_location_target(query)
        if target is None:
            return self._unavailable(
                "天气查询缺少地点",
                "用户没有给城市/地点，本地上下文也没有默认地点；不能猜位置。",
                ["weather_location_required"],
            )
        day_index, day_label = _weather_day_index(query)
        try:
            payload = self._fetch_weatherapi(target.query, day_index + 1)
            return self.normalize(
                {
                    "provider": provider,
                    "payload": payload,
                    "target": target.to_dict(),
                    "day_index": day_index,
                    "day_label": day_label,
                }
            )
        except Exception as exc:
            return ConnectorRawResult(
                source_name=self.source_name,
                source_type=self.source_type,
                freshness_status=FRESH_UNAVAILABLE,
                title="天气源调用失败",
                summary="真实天气源这轮没有返回可用数据；不能补编温度、降雨概率或风力。",
                key_values={"error": type(exc).__name__},
                source_url_or_origin="WeatherAPI.com forecast.json",
                confidence_level="medium",
                known_limits=["weather_provider_error"],
            )

    def _unavailable(self, title: str, summary: str, limits: list[str]) -> ConnectorRawResult:
        return ConnectorRawResult(
            source_name=self.source_name,
            source_type=self.source_type,
            freshness_status=FRESH_UNAVAILABLE,
            title=title,
            summary=summary,
            source_url_or_origin="local weather connector config",
            confidence_level="high",
            known_limits=limits,
        )

    def _fetch_weatherapi(self, location_query: str, days: int) -> dict[str, Any]:
        params = {
            "key": str(os.environ.get("VELA_WEATHER_API_KEY") or "").strip(),
            "q": location_query,
            "days": str(min(max(days, 1), 3)),
            "aqi": "no",
            "alerts": "no",
            "lang": "zh",
        }
        url = f"{WEATHERAPI_FORECAST_URL}?{urlencode(params)}"
        with urllib.request.urlopen(url, timeout=_weather_timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("weather_payload_not_object")
        return payload

    def normalize(self, raw_result: ConnectorRawResult | dict[str, Any]) -> ConnectorRawResult:
        if isinstance(raw_result, ConnectorRawResult):
            return raw_result
        payload = raw_result.get("payload") if isinstance(raw_result.get("payload"), dict) else {}
        target = raw_result.get("target") if isinstance(raw_result.get("target"), dict) else {}
        forecast = payload.get("forecast") if isinstance(payload.get("forecast"), dict) else {}
        forecast_days = forecast.get("forecastday") if isinstance(forecast.get("forecastday"), list) else []
        if not forecast_days:
            return ConnectorRawResult(
                source_name=self.source_name,
                source_type=self.source_type,
                freshness_status=FRESH_UNAVAILABLE,
                title="天气源缺少预报字段",
                summary="天气 provider 返回了数据，但没有可整理的 forecastday；不补编预报。",
                source_url_or_origin="WeatherAPI.com forecast.json",
                confidence_level="medium",
                known_limits=["weather_forecast_missing"],
            )
        requested_day = int(raw_result.get("day_index") or 0)
        day_index = min(max(requested_day, 0), len(forecast_days) - 1)
        forecast_day = forecast_days[day_index] if isinstance(forecast_days[day_index], dict) else {}
        day = forecast_day.get("day") if isinstance(forecast_day.get("day"), dict) else {}
        current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
        api_location = payload.get("location") if isinstance(payload.get("location"), dict) else {}

        label = str(target.get("label") or api_location.get("name") or "未知地点").strip()
        day_label = str(raw_result.get("day_label") or "今天").strip()
        date_text = str(forecast_day.get("date") or "").strip()
        forecast_window = f"{day_label}（{date_text}）" if date_text else day_label
        temperature = _weather_temperature_text(current, day, day_index)
        condition = _weather_condition_text(current, day, day_index)
        precipitation = _weather_precipitation_text(day)
        wind = _weather_wind_text(current, day, day_index)
        humidity = _weather_humidity_text(current, day, day_index)
        updated_at = str(current.get("last_updated") or api_location.get("localtime") or "").strip()
        known_limits = ["forecast_probability_is_daily_not_minute_level"]
        if requested_day >= len(forecast_days):
            known_limits.append("requested_forecast_window_not_returned")
        for key, value in {
            "temperature": temperature,
            "condition": condition,
            "precipitation_probability": precipitation,
            "wind": wind,
            "humidity": humidity,
        }.items():
            if value == "未知":
                known_limits.append(f"missing_{key}")
        key_values = {
            "location": label,
            "temperature": temperature,
            "condition": condition,
            "precipitation_probability": precipitation,
            "wind": wind,
            "humidity": humidity,
            "forecast_window": forecast_window,
        }
        if updated_at:
            key_values["provider_updated_at"] = updated_at
        summary = (
            f"{label}{forecast_window}：{condition}，温度{temperature}，"
            f"降水概率{precipitation}，风{wind}，湿度{humidity}。"
        )
        return ConnectorRawResult(
            source_name=self.source_name,
            source_type=self.source_type,
            freshness_status=FRESH_REALTIME,
            title=f"{label}{forecast_window}天气",
            summary=summary,
            key_values=key_values,
            source_url_or_origin="WeatherAPI.com forecast.json",
            confidence_level="high" if not any(limit.startswith("missing_") for limit in known_limits) else "medium",
            known_limits=known_limits,
        )


class WebNewsSearchConnector(RetrievalConnector):
    source_name = "web/news search connector"

    def __init__(self, source_type: str):
        self.source_type = source_type

    def can_handle(self, source_type: str) -> bool:
        return source_type in {"web_search", "news"} and source_type == self.source_type

    def fetch(self, query: str, freshness_requirement: str) -> ConnectorRawResult:
        provider = str(os.environ.get("VELA_SEARCH_PROVIDER") or "").strip().lower()
        api_key = str(os.environ.get("VELA_SEARCH_API_KEY") or "").strip()
        if not provider or not api_key:
            return self._unavailable("网页/新闻搜索源未接入", ["search_provider_not_configured"])
        if provider != "serper":
            return self._unavailable("搜索 provider 暂不支持", ["search_provider_unsupported"])
        try:
            payload = self._fetch_serper(query)
            return self.normalize(payload)
        except Exception as exc:
            return ConnectorRawResult(
                source_name="Serper search",
                source_type=self.source_type,
                freshness_status=FRESH_UNAVAILABLE,
                title="搜索源调用失败",
                summary="公开搜索源调用失败；不能把模型判断伪装成已检索结果。",
                key_values={"error": type(exc).__name__},
                source_url_or_origin="Serper API",
                confidence_level="medium",
                known_limits=["search_provider_error"],
            )

    def _unavailable(self, title: str, limits: list[str]) -> ConnectorRawResult:
        return ConnectorRawResult(
            source_name=self.source_name,
            source_type=self.source_type,
            freshness_status=FRESH_UNAVAILABLE,
            title=title,
            summary="未配置 VELA_SEARCH_PROVIDER / VELA_SEARCH_API_KEY；不能把模型常识包装成实时检索。",
            source_url_or_origin="local search connector config",
            confidence_level="high",
            known_limits=limits,
        )

    def _fetch_serper(self, query: str) -> dict[str, Any]:
        endpoint = "https://google.serper.dev/news" if self.source_type == "news" else "https://google.serper.dev/search"
        data = json.dumps({"q": query, "num": 5}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "X-API-KEY": str(os.environ.get("VELA_SEARCH_API_KEY") or "").strip(),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("search_payload_not_object")
        return payload

    def normalize(self, raw_result: ConnectorRawResult | dict[str, Any]) -> ConnectorRawResult:
        if isinstance(raw_result, ConnectorRawResult):
            return raw_result
        items = raw_result.get("news") if self.source_type == "news" else raw_result.get("organic")
        if not isinstance(items, list) or not items:
            items = raw_result.get("organic") if isinstance(raw_result.get("organic"), list) else []
        if not items:
            return ConnectorRawResult(
                source_name="Serper search",
                source_type=self.source_type,
                freshness_status=FRESH_UNAVAILABLE,
                title="搜索源暂未返回可用条目",
                summary="搜索 provider 已调用，但没有返回可整理为证据包的公开条目。",
                source_url_or_origin="Serper API",
                confidence_level="medium",
                known_limits=["no_search_results"],
            )
        first = items[0] if isinstance(items[0], dict) else {}
        title = str(first.get("title") or "公开资料线索").strip()
        summary = str(first.get("snippet") or first.get("description") or "搜索结果缺少摘要；需要打开原始来源复核。").strip()
        source = str(first.get("source") or first.get("sitelinks", "") or "Serper search").strip()
        link = str(first.get("link") or first.get("url") or "Serper API").strip()
        key_values = {"provider": "serper", "item_count": str(len(items))}
        date_text = str(first.get("date") or "").strip()
        if date_text:
            key_values["published_or_indexed"] = date_text
        return ConnectorRawResult(
            source_name=source or "Serper search",
            source_type=self.source_type,
            freshness_status=FRESH_REALTIME,
            title=title,
            summary=summary,
            key_values=key_values,
            source_url_or_origin=link,
            confidence_level="medium",
            known_limits=["search_result_is_lead_not_final_fact", "source_must_be_verified_before_strong_claims"],
        )


def default_connectors() -> list[RetrievalConnector]:
    return [
        MarketDataConnector(),
        WeatherConnector(),
        WebNewsSearchConnector("news"),
        WebNewsSearchConnector("web_search"),
        RetrievalConnector(),
    ]


def _compact(text: str) -> str:
    return "".join(str(text or "").lower().split())


def _has_any(text: str, markers: tuple[str, ...] | list[str]) -> bool:
    return any(marker.lower() in text for marker in markers)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _timeout_seconds() -> float:
    raw = str(os.environ.get("VELA_SEARCH_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return 8.0
    try:
        value = float(raw)
    except ValueError:
        return 8.0
    return min(max(value, 2.0), 20.0)


def _market_requires_current_value(query: str) -> bool:
    compact = _compact(query)
    return _has_any(
        compact,
        [
            "现在",
            "当前",
            "目前",
            "此刻",
            "实时",
            "是多少",
            "多少",
            "正常",
            "汇率",
            "vix",
            "美元人民币",
            "美元/人民币",
            "usdcny",
            "usd/cny",
        ],
    )


def _market_target_for_query(query: str) -> MarketTarget | None:
    compact = _compact(query)
    if _has_any(compact, ["美元人民币", "美元/人民币", "美元兑人民币", "人民币汇率", "美元人民币汇率", "usdcny", "usd/cny"]) or (
        "美元" in compact and "人民币" in compact and "汇率" in compact
    ):
        return MarketTarget(label="美元/人民币", target_type="fx", from_currency="USD", to_currency="CNY")
    if "vix" in compact:
        return MarketTarget(label="VIX", target_type="quote", symbol="VIX")
    if _has_any(compact, ["s&p500", "sp500", "标普500"]):
        return MarketTarget(label="S&P 500", target_type="quote", symbol="SPY")
    if _has_any(compact, ["nasdaq", "纳斯达克", "纳指"]):
        return MarketTarget(label="Nasdaq", target_type="quote", symbol="QQQ")
    if _has_any(compact, ["美元指数", "dxy"]):
        return MarketTarget(label="美元指数", target_type="quote", symbol="UUP")
    return None


def _clean_market_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "未返回"
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return text[:32]
    number = match.group(0)
    if "." not in number:
        return number
    integer, decimal = number.split(".", 1)
    decimal = decimal[:4].rstrip("0")
    return integer if not decimal else f"{integer}.{decimal}"


def plan_sources(message: str, intent: str) -> SourcePlan:
    compact = _compact(message)
    source_types: list[str] = []
    freshness = "none"
    fallback: list[str] = []
    should_use_cache = False
    warn = False
    reason = ""

    if intent == "weather_query" or _has_any(compact, ["天气", "冷吗", "热吗", "下雨", "下雪", "降雨", "风大", "温度", "气温"]):
        return SourcePlan(
            source_need=True,
            source_type=["weather"],
            freshness_requirement="real_time",
            acceptable_fallback=[FRESH_UNAVAILABLE],
            should_use_cache=False,
            should_warn_if_unavailable=True,
            reason="天气必须由天气源提供，不用人格层编预报。",
        )

    market_markers = [
        "vix",
        "市场",
        "加仓",
        "a股",
        "港股",
        "美股",
        "走势",
        "行情",
        "汇率",
        "股票",
        "基金",
        "指数",
        "美元人民币",
        "美元/人民币",
        "人民币",
        "美元",
        "美债",
        "黄金",
        "油价",
        "正常阶段",
        "非正常阶段",
        "光模块",
        "存储",
        "半导体",
    ]
    if intent == "market_brief" or _has_any(compact, market_markers):
        source_types.append("market_data")
        should_use_cache = True
        warn = True
        real_time_markers = [
            "现在",
            "当前",
            "目前",
            "此刻",
            "实时",
            "vix",
            "是多少",
            "多少",
            "能不能",
            "要不要",
            "加仓",
            "汇率",
            "正常",
            "讨论度",
            "最新",
        ]
        realtime_requested = _has_any(compact, real_time_markers) and not _has_any(compact, ["不是实时", "不需要实时"])
        freshness = "real_time" if realtime_requested else "cached_or_delayed"
        fallback = [FRESH_CACHE, FRESH_DELAYED, FRESH_UNAVAILABLE]
        reason = "市场问题先查行情/缓存边界，不能凭模型生成盘中事实。"
        if freshness == "real_time" or _has_any(compact, ["讨论度", "新闻", "资讯", "消息", "存储", "光模块"]):
            source_types.extend(["news", "web_search"])
            reason = "实时金融判断需要行情、新闻和网页线索共同校准，不能只看模型口感。"
        return SourcePlan(
            source_need=True,
            source_type=_dedupe(source_types),
            freshness_requirement=freshness,
            acceptable_fallback=fallback,
            should_use_cache=should_use_cache,
            should_warn_if_unavailable=warn,
            reason=reason,
        )

    if _has_any(compact, ["deepseek", "codex", "记忆"]) and _has_any(compact, ["关系", "是什么", "能访问", "资料源", "自己搜"]):
        return SourcePlan(
            source_need=True,
            source_type=["local_memory", "generic_tool_connector"],
            freshness_requirement="local_context",
            acceptable_fallback=["local_memory", FRESH_UNAVAILABLE],
            should_use_cache=True,
            should_warn_if_unavailable=False,
            reason="身份/工具能力问题读取本地记忆和通用工具状态，不触发外部检索。",
        )

    life_info = _has_any(compact, ["附近", "生活资讯", "出门建议", "本地生活", "周边", "活动", "通勤", "路线", "餐厅"])
    current_info = life_info or _has_any(
        compact,
        ["现在", "今天", "当前", "最新", "查一下", "搜一下", "检索", "资料", "新闻", "公告", "网上讨论", "行业资讯", "政策"],
    )
    if intent in {"daily_info", "world_brief"} and current_info:
        return SourcePlan(
            source_need=True,
            source_type=["news", "web_search"],
            freshness_requirement="real_time",
            acceptable_fallback=[FRESH_UNAVAILABLE],
            should_use_cache=False,
            should_warn_if_unavailable=True,
            reason="现在类信息要先检索资料，再交给模型判断。",
        )

    if intent in {"memory_related", "project_assistant"}:
        return SourcePlan(
            source_need=True,
            source_type=["local_memory", "local_files", "generic_tool_connector"],
            freshness_requirement="local_context",
            acceptable_fallback=["local_memory", FRESH_UNAVAILABLE],
            should_use_cache=True,
            should_warn_if_unavailable=False,
            reason="项目/记忆问题优先读取本地上下文。",
        )

    return SourcePlan(source_need=False, source_type=[], reason="不需要外部资料源。")


def connector_for(source_type: str, connectors: list[RetrievalConnector]) -> RetrievalConnector:
    for connector in connectors:
        if connector.can_handle(source_type):
            return connector
    return RetrievalConnector()


def build_realtime_evidence(
    message: str,
    intent: str,
    *,
    connectors: list[RetrievalConnector] | None = None,
) -> RealtimeEvidenceResult:
    plan = plan_sources(message, intent)
    if not plan.source_need:
        return RealtimeEvidenceResult(plan=plan)
    registry = connectors or default_connectors()
    packets: list[EvidencePacket] = []
    for source_type in plan.source_type:
        connector = connector_for(source_type, registry)
        raw = connector.fetch(message, plan.freshness_requirement)
        normalized = connector.normalize(raw)
        packets.append(connector.build_evidence_packet(normalized, query=message))
    boundary = format_realtime_boundary(plan, packets)
    model_context = format_evidence_for_model(plan, packets, boundary)
    return RealtimeEvidenceResult(plan=plan, packets=packets, frontstage_boundary=boundary, model_context=model_context)


def _first_number(text: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(text or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _weather_advice(packet: EvidencePacket) -> str:
    values = packet.key_values
    rain = _first_number(values.get("precipitation_probability", ""))
    wind = _first_number(values.get("wind", ""))
    temperature = _first_number(values.get("temperature", ""))
    if rain is not None and rain >= 60:
        return "出门可以，但别硬刚天气：带伞，鞋别穿太娇贵，行程留十五到三十分钟缓冲。"
    if rain is not None and rain >= 35:
        return "能出门，但天气有变脸风险；伞带上，别把行程排到一秒不剩。"
    if wind is not None and wind >= 25:
        return "风偏大，能出门但别安排太狼狈的户外行程；外套和发型至少保一个。"
    if temperature is not None and temperature <= 10:
        return "偏冷，外套别省；省这一层布，最后会用体温还债。"
    if temperature is not None and temperature >= 30:
        return "偏热，少折腾户外；水和防晒比嘴硬更可靠。"
    return "整体可以正常安排；出门前再看一次临近预报，重点盯降雨和风。"


def _format_weather_frontstage(packet: EvidencePacket) -> str:
    values = packet.key_values
    location = values.get("location", "这个地点")
    window = values.get("forecast_window", "今天")
    condition = values.get("condition", "未知")
    temperature = values.get("temperature", "未知")
    precipitation = values.get("precipitation_probability", "未知")
    wind = values.get("wind", "未知")
    humidity = values.get("humidity", "未知")
    updated_at = values.get("provider_updated_at") or packet.retrieved_at
    return "\n".join(
        [
            f"{location}{window}：{_weather_advice(packet)}",
            f"关键数据：{condition}，温度{temperature}，降雨概率{precipitation}，风{wind}，湿度{humidity}。",
            f"更新时间：{updated_at}；边界：这是天气源预报，不是分钟级临场保证，出门前再扫一眼。"
        ]
    )


def _format_market_frontstage(packet: EvidencePacket | None, packets: list[EvidencePacket]) -> str:
    market = packet or next((item for item in packets if item.source_type == "market_data"), None)
    if market is None:
        return (
            "当前可用数据：暂未形成市场数据包。\n"
            "不可用数据：实时行情源未接入，不能给当前数值。\n"
            "可判断部分：只能做问题类型识别和资料缺口判断。\n"
            "不能确定部分：当前价格、VIX、汇率、仓位时点都不能确定。\n"
            "下一步：配置 VELA_MARKET_PROVIDER / VELA_MARKET_API_KEY 后再查。"
        )
    values = market.key_values
    instrument = values.get("instrument") or ("VIX" if "vix" in _compact(market.title + market.summary) else "市场指标")
    if market.freshness_status == FRESH_REALTIME:
        value = values.get("value", "未返回")
        data_time = values.get("data_time") or market.retrieved_at
        provider = values.get("provider", market.source_name)
        delay = values.get("delay_status", "provider_reported")
        extra = ""
        if values.get("change_percent"):
            extra = f"；涨跌幅 {values['change_percent']}"
        return "\n".join(
            [
                f"结论：{instrument} 已查到可用行情，当前值约 {value}{extra}。",
                f"依据：数据时间 {data_time}；来源 {provider}；状态 {delay}。",
                "边界：行情可能延迟，结论只能辅助判断，不是确定性买卖指令。",
                "下一步：再叠加新闻、美元/美债和主要指数表现，别拿一个数字替整个战场下令。",
            ]
        )
    cache_text = values.get("cache_last_updated")
    available = f"本地缓存（更新时间 {cache_text}）" if cache_text else "本地缓存、用户提供材料、已接入的网页/新闻线索（如有）"
    unavailable = f"{instrument} 实时行情源未接入，不能给当前数值"
    if values.get("provider"):
        unavailable = f"{instrument} provider 未返回可用行情，不能给当前数值"
    return "\n".join(
        [
            f"当前可用数据：{available}。",
            f"不可用数据：{unavailable}。",
            "可判断部分：可以做方向框架、风险清单和低置信度观察，不能把缓存当直播。",
            f"不能确定部分：{instrument} 当前值、异常程度、交易时点和买卖强度都不能确定。",
            "下一步：接入市场数据 provider 和密钥；VIX、汇率、指数要拿到实时行情后，再交给 DeepSeek 综合判断。",
        ]
    )


def format_realtime_boundary(plan: SourcePlan, packets: list[EvidencePacket]) -> str:
    if not plan.source_need:
        return ""
    statuses = {packet.freshness_status for packet in packets}
    types = set(plan.source_type)
    if "market_data" in types and FRESH_REALTIME not in statuses:
        return _format_market_frontstage(next((packet for packet in packets if packet.source_type == "market_data"), None), packets)
    if "market_data" in types and FRESH_REALTIME in statuses:
        market_packet = next((packet for packet in packets if packet.source_type == "market_data"), None)
        if market_packet is not None and market_packet.freshness_status == FRESH_REALTIME:
            return _format_market_frontstage(market_packet, packets)
        return _format_market_frontstage(market_packet, packets)
    if {"web_search", "news"} & types and FRESH_REALTIME not in statuses:
        return "网页/新闻搜索源未接入；我不能把模型常识伪装成实时检索。"
    if "weather" in types:
        first = packets[0] if packets else None
        if first is None:
            return "我现在还没接入真实天气源，所以不能给实时天气。接上天气 provider 后，我就能按地点读取天气，再给你自然判断。"
        limits = set(first.known_limits)
        if first.freshness_status == FRESH_REALTIME:
            return _format_weather_frontstage(first)
        if "weather_provider_not_configured" in limits:
            return "我现在还没接入真实天气源，所以不能给实时天气。接上天气 provider 后，我就能按地点读取天气，再给你自然判断。"
        if "weather_location_required" in limits:
            return "你要看天气，先给地点；城市名发我就行。我不猜你在哪，天气这东西猜错了会很蠢。"
        if "weather_provider_unsupported" in limits:
            return "天气 provider 还没接到可用类型；现在不能给实时天气。把 VELA_WEATHER_PROVIDER 配成 weatherapi 后再查。"
        return "真实天气源这轮没拉回可用数据；我不编温度和降雨概率。要安排出门，先按有雨、有温差处理。"
    if {"web_search", "news"} & types and FRESH_REALTIME in statuses:
        first = next((packet for packet in packets if packet.freshness_status == FRESH_REALTIME), None)
        if first is not None:
            return f"公开网页/新闻搜索源已返回线索；先看《{first.title}》。判断前仍要复核原始来源。"
        return "公开网页/新闻搜索源已返回线索；判断前仍要复核原始来源。"
    if "generic_tool_connector" in types:
        return "这类问题先看本地记忆和通用工具状态；不把模型能力说成外部检索能力。"
    return "我现在没有可用外部资料源，不能把模型判断伪装成实时检索。"


def _status_label(status: str) -> str:
    labels = {
        FRESH_REALTIME: "实时可用",
        FRESH_DELAYED: "延时/专用链路",
        FRESH_CACHE: "本地缓存",
        FRESH_MODEL_ONLY: "仅模型推断",
        FRESH_UNAVAILABLE: "不可用",
    }
    return labels.get(status, status)


def format_evidence_for_model(plan: SourcePlan, packets: list[EvidencePacket], boundary: str) -> str:
    if not plan.source_need:
        return ""
    lines = [
        "资料源计划："
        f"需要 {', '.join(plan.source_type)}；新鲜度要求：{plan.freshness_requirement}；"
        f"可降级：{', '.join(plan.acceptable_fallback) or '无'}。",
        f"资料边界：{boundary}",
        "证据包：",
    ]
    for packet in packets:
        values = "；".join(f"{key}={value}" for key, value in packet.key_values.items())
        value_text = f"；关键值：{values}" if values else ""
        limits = "、".join(packet.known_limits) if packet.known_limits else "无"
        lines.append(
            f"- {packet.source_name}（{packet.source_type}，{_status_label(packet.freshness_status)}）："
            f"{packet.title}。摘要：{packet.summary}{value_text}；限制：{limits}。"
        )
    return "\n".join(lines).strip()
