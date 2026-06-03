from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

FRESH_REALTIME = "real_time_source_available"
FRESH_DELAYED = "delayed_source_available"
FRESH_CACHE = "cached_summary_available"
FRESH_MODEL_ONLY = "model_generated_only"
FRESH_UNAVAILABLE = "unavailable"


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
        return asdict(self)


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
class RealtimeEvidenceResult:
    plan: SourcePlan
    packets: list[EvidencePacket] = field(default_factory=list)
    frontstage_boundary: str = ""
    model_context: str = ""


class RetrievalConnector:
    source_type = "generic"
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
        key_values: dict[str, str] = {}
        status_text = FRESH_UNAVAILABLE
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
        wants_vix = "vix" in _compact(query)
        summary = (
            "当前没有 VIX/外盘实时行情 connector；不能给当前数值。"
            if wants_vix
            else "当前市场实时 connector 不完整；只能使用本地缓存、已有行情快照或用户提供材料做方向判断。"
        )
        limits = ["no_realtime_market_connector"]
        if wants_vix:
            limits.append("no_vix_realtime_value")
        return ConnectorRawResult(
            source_name=self.source_name,
            source_type=self.source_type,
            freshness_status=status_text,
            title="市场数据源边界",
            summary=summary,
            key_values=key_values,
            source_url_or_origin="VELA/market-cache and configured market connectors",
            confidence_level="high",
            known_limits=limits,
        )


class WeatherConnector(RetrievalConnector):
    source_type = "weather"
    source_name = "Open-Meteo weather lane"

    def fetch(self, query: str, freshness_requirement: str) -> ConnectorRawResult:
        return ConnectorRawResult(
            source_name=self.source_name,
            source_type=self.source_type,
            freshness_status=FRESH_DELAYED,
            title="天气资料源计划",
            summary="天气问题必须走 weather connector；真实预报由 weather lane 拉取，失败时只给出行风险边界。",
            source_url_or_origin="Open-Meteo forecast API via vela_realtime_info",
            confidence_level="high",
            known_limits=["weather_fetch_happens_in_weather_lane"],
        )


class NewsConnector(RetrievalConnector):
    source_type = "news"
    source_name = "news/rss connector"

    def fetch(self, query: str, freshness_requirement: str) -> ConnectorRawResult:
        try:
            from vela_realtime_info import fetch_current_info_items

            items = fetch_current_info_items(query, max_items=3)
        except Exception:
            items = []
        if not items:
            return ConnectorRawResult(
                source_name=self.source_name,
                source_type=self.source_type,
                freshness_status=FRESH_UNAVAILABLE,
                title="新闻资料源暂未抓到高置信条目",
                summary="没有抓到可验证新闻条目；不能把模型常识包装成今天发生的事。",
                source_url_or_origin="Google News RSS connector",
                confidence_level="medium",
                known_limits=["no_high_confidence_news_items"],
            )
        first = items[0]
        return ConnectorRawResult(
            source_name=str(first.source or self.source_name),
            source_type=self.source_type,
            freshness_status=FRESH_REALTIME,
            title=str(first.title or "实时资讯线索"),
            summary=f"抓到 {len(items)} 条可用线索；第一条来自 {first.source or '未标明来源'}。",
            key_values={"item_count": str(len(items))},
            source_url_or_origin=str(first.link or "Google News RSS"),
            confidence_level="medium",
            known_limits=["rss_title_is_not_final_conclusion"],
        )


class WebSearchConnector(RetrievalConnector):
    source_type = "web_search"
    source_name = "web search connector"

    def fetch(self, query: str, freshness_requirement: str) -> ConnectorRawResult:
        return ConnectorRawResult(
            source_name=self.source_name,
            source_type=self.source_type,
            freshness_status=FRESH_UNAVAILABLE,
            title="网页搜索 connector 未配置",
            summary="MVP 还没有独立网页搜索 API；如新闻 RSS 没抓到资料，就不能伪装成已联网检索。",
            source_url_or_origin="local placeholder connector",
            confidence_level="high",
            known_limits=["web_search_api_not_configured"],
        )


class BusinessDataConnector(RetrievalConnector):
    def __init__(self, source_type: str, source_name: str):
        self.source_type = source_type
        self.source_name = source_name

    def fetch(self, query: str, freshness_requirement: str) -> ConnectorRawResult:
        readable = {
            "amazon_ads": "Amazon Ads",
            "seller_sprite_mcp": "SellerSprite MCP",
            "local_files": "本地文件",
            "local_memory": "本地记忆",
            "gmail_import": "Gmail 导入",
        }.get(self.source_type, self.source_name)
        return ConnectorRawResult(
            source_name=readable,
            source_type=self.source_type,
            freshness_status=FRESH_UNAVAILABLE,
            title=f"{readable} 资料源边界",
            summary=f"{readable} connector 尚未接入当前 VELA 前台；不能用普通网页搜索替代广告账户或店铺数据。",
            source_url_or_origin="future connector slot",
            confidence_level="high",
            known_limits=["business_connector_not_configured"],
        )


def default_connectors() -> list[RetrievalConnector]:
    return [
        MarketDataConnector(),
        WeatherConnector(),
        NewsConnector(),
        WebSearchConnector(),
        BusinessDataConnector("amazon_ads", "Amazon Ads connector"),
        BusinessDataConnector("seller_sprite_mcp", "SellerSprite MCP connector"),
        BusinessDataConnector("local_files", "local files connector"),
        BusinessDataConnector("local_memory", "local memory connector"),
        BusinessDataConnector("gmail_import", "Gmail import connector"),
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


def plan_sources(message: str, intent: str) -> SourcePlan:
    compact = _compact(message)
    source_types: list[str] = []
    freshness = "none"
    fallback: list[str] = []
    should_use_cache = False
    warn = False
    reason = ""

    ads_query = _has_any(
        compact,
        ["augsun广告", "amazonads", "广告分析", "广告投放", "acos", "seller_sprite", "sellersprite", "gmail导入"],
    )
    if ads_query:
        source_types.extend(["amazon_ads", "seller_sprite_mcp", "local_files", "local_memory"])
        if "gmail" in compact or "邮件" in compact:
            source_types.append("gmail_import")
        return SourcePlan(
            source_need=True,
            source_type=_dedupe(source_types),
            freshness_requirement="recent_local_or_account_data",
            acceptable_fallback=["local_memory", "local_files", FRESH_UNAVAILABLE],
            should_use_cache=True,
            should_warn_if_unavailable=True,
            reason="广告/业务分析要账户、店铺、本地文件或记忆，不用普通网页搜索代替。",
        )

    if intent == "weather_query" or _has_any(compact, ["天气", "冷吗", "热吗", "下雨", "温度"]):
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
        "光模块",
        "存储",
        "半导体",
    ]
    if intent == "market_brief" or _has_any(compact, market_markers):
        source_types.append("market_data")
        should_use_cache = True
        warn = True
        freshness = "real_time" if _has_any(compact, ["现在", "今天", "当前", "实时", "vix", "是多少"]) else "cached_or_delayed"
        fallback = [FRESH_CACHE, FRESH_DELAYED, FRESH_UNAVAILABLE]
        reason = "市场问题先查行情/缓存边界，不能凭模型生成盘中事实。"
        if _has_any(compact, ["讨论度", "新闻", "资讯", "消息", "存储", "光模块"]):
            source_types.extend(["news", "web_search"])
            reason = "市场讨论度需要行情、新闻和网页线索共同验证。"
        return SourcePlan(
            source_need=True,
            source_type=_dedupe(source_types),
            freshness_requirement=freshness,
            acceptable_fallback=fallback,
            should_use_cache=should_use_cache,
            should_warn_if_unavailable=warn,
            reason=reason,
        )

    current_info = _has_any(compact, ["现在", "今天", "当前", "最新", "查一下", "搜一下", "检索", "资料", "新闻", "公告"])
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
            source_type=["local_memory", "local_files"],
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


def format_realtime_boundary(plan: SourcePlan, packets: list[EvidencePacket]) -> str:
    if not plan.source_need:
        return ""
    statuses = {packet.freshness_status for packet in packets}
    types = set(plan.source_type)
    if {"amazon_ads", "seller_sprite_mcp", "local_files", "local_memory"} & types:
        return (
            "这类广告分析要读 Amazon Ads、SellerSprite、本地文件或本地记忆；"
            "当前这些业务数据源还没接到前台，所以只能先说明缺口，不能冒充账户数据。"
        )
    if "market_data" in types and {"news", "web_search"} & types:
        return (
            "存储和光模块讨论度要同时看行情、新闻和网页线索；"
            "当前实时资料源不完整，只能先标出证据缺口，不能把缓存盘面当成板块热度。"
        )
    if "market_data" in types and FRESH_REALTIME not in statuses:
        if FRESH_CACHE in statuses:
            return "我现在没有完整实时行情源，只能基于本地缓存和已接入资料做方向判断。"
        return "我现在没有可用实时行情源，不能给盘中数值，也不能把模型判断伪装成行情。"
    if "weather" in types:
        return "天气问题先走天气源；源不可用时只给出行风险边界，不编温度。"
    if FRESH_REALTIME in statuses:
        return "实时资料源已有可用线索；结论仍要区分标题证据和最终判断。"
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
