from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import json
from pathlib import Path
import re
import sys
from typing import Iterable
from urllib.parse import quote, quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree


CHINA_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "VELA" / "market-cache"
DEFAULT_TIMEOUT = 8
DEFAULT_MAX_NEWS = 10
FRONT_MAX_NEWS = 5
MISSING_VALUE = "暂无可靠数据，暂不纳入判断。"
MARKET_BRIEF_SCHEMA_VERSION = "market-brief-v2-2026-05-25"


@dataclass(frozen=True)
class MarketNewsItem:
    title: str
    source: str
    published_at: str
    market_tags: list[str]
    impact_type: list[str] | str
    impact_score: int
    direction: str
    reason: str
    source_url: str = ""

    def __post_init__(self) -> None:
        score = max(1, min(5, int(self.impact_score)))
        object.__setattr__(self, "impact_score", score)
        direction = self.direction if self.direction in VALID_DIRECTIONS else "uncertain"
        object.__setattr__(self, "direction", direction)
        if not self.market_tags:
            object.__setattr__(self, "market_tags", ["global"])
        if isinstance(self.impact_type, str):
            impact_type = [self.impact_type] if self.impact_type else ["market_signal"]
        else:
            impact_type = [str(item) for item in self.impact_type if str(item).strip()]
        object.__setattr__(self, "impact_type", impact_type or ["market_signal"])


@dataclass(frozen=True)
class MarketDashboard:
    china: dict[str, str] = field(default_factory=dict)
    us: dict[str, str] = field(default_factory=dict)
    korea: dict[str, str] = field(default_factory=dict)
    japan: dict[str, str] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketBrief:
    as_of: str
    window_label: str
    slot: str
    dashboard: MarketDashboard
    news: list[MarketNewsItem]
    good_signs: list[str]
    bad_signs: list[str]
    main_line: str
    vela_judgment: list[str]
    watch_next: list[str]


@dataclass(frozen=True)
class MarketFreshnessStatus:
    data_status: str
    last_updated: str
    source_type: str
    refresh_available: bool
    refresh_in_progress: bool
    confidence_note: str
    slot: str = ""
    cache_path: str = ""
    real_time_source_available: bool = False
    cached_summary_available: bool = False
    model_generated_only: bool = False
    unavailable: bool = False


@dataclass(frozen=True)
class LiveMarketSnapshot:
    ok: bool
    as_of: str
    source: str
    lines: list[str]
    source_status: str
    note: str = ""
    error: str = ""


VALID_DIRECTIONS = {"bullish", "bearish", "neutral", "uncertain"}

MARKET_WEIGHT_BY_TAG = {
    "china_a": 35,
    "us_equities": 30,
    "semiconductors": 30,
    "korea": 15,
    "japan": 8,
    "us_10y": 8,
    "usd": 8,
    "oil": 8,
    "gold": 8,
    "geopolitics": 4,
}

QUOTE_SYMBOLS = {
    "上证": "000001.SS",
    "深成指": "399001.SZ",
    "创业板": "399006.SZ",
    "沪深300": "000300.SS",
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Dow": "^DJI",
    "Russell 2000": "^RUT",
    "VIX": "^VIX",
    "10Y美债": "^TNX",
    "WTI": "CL=F",
    "黄金": "GC=F",
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "Samsung": "005930.KS",
    "SK Hynix": "000660.KS",
    "Nikkei": "^N225",
    "TOPIX": "^TOPX",
    "人民币": "CNY=X",
    "韩元": "KRW=X",
    "日元": "JPY=X",
}

SINA_A_SHARE_SYMBOLS = {
    "s_sh000001": "上证指数",
    "s_sz399001": "深证成指",
    "s_sz399006": "创业板指",
    "s_sh000300": "沪深300",
}

LIVE_CHINA_MARKERS = ("a股", "a 股", "上证", "沪深", "深成", "创业板", "人民币", "盘面")
LIVE_FOREIGN_MARKERS = (
    "全球",
    "世界",
    "国际市场",
    "外盘",
    "美股",
    "nasdaq",
    "s&p",
    "sp500",
    "vix",
    "韩国",
    "kospi",
    "samsung",
    "hynix",
    "日本",
    "nikkei",
    "topix",
    "日元",
    "美元",
    "美债",
)

SEARCH_QUERIES = [
    "A shares Shanghai Shenzhen CSI 300 yuan market Reuters CNBC when:1d",
    "US stock futures S&P 500 Nasdaq VIX Treasury yields dollar Reuters when:1d",
    "South Korea KOSPI Samsung SK Hynix foreign investors semiconductor Reuters when:1d",
    "Japan Nikkei TOPIX yen BOJ market Reuters when:1d",
    "oil gold dollar Treasury yields geopolitical risk market Reuters AP when:1d",
    "AI semiconductor Nvidia chips memory market Reuters Bloomberg when:1d",
]

TAG_KEYWORDS = {
    "china_a": ["a-share", "a shares", "shanghai", "shenzhen", "csi 300", "yuan", "china stock", "a股", "上证", "沪深300"],
    "us_equities": ["s&p", "nasdaq", "dow", "russell", "wall street", "us stock", "美股"],
    "korea": ["kospi", "kosdaq", "samsung", "hynix", "won", "south korea", "韩国"],
    "japan": ["nikkei", "topix", "yen", "boj", "japan", "日本"],
    "semiconductors": ["chip", "semiconductor", "nvidia", "hynix", "samsung", "memory", "ai", "半导体", "芯片"],
    "us_10y": ["treasury", "yield", "bond", "10-year", "10y", "美债"],
    "usd": ["dollar", "usd", "美元"],
    "oil": ["oil", "brent", "wti", "crude", "energy", "原油", "油价"],
    "gold": ["gold", "黄金"],
    "geopolitics": ["war", "sanction", "missile", "iran", "russia", "ukraine", "gaza", "taiwan", "military", "地缘"],
}

NOISE_KEYWORDS = [
    "podcast",
    "live updates",
    "as it happened",
    "questions answered",
    "horoscope",
    "celebrity",
]

SOURCE_CN = {
    "Reuters": "路透社",
    "AP": "美联社",
    "Associated Press": "美联社",
    "Bloomberg": "彭博社",
    "Wall Street Journal": "华尔街日报",
    "Financial Times": "金融时报",
    "CNBC": "CNBC",
    "MarketWatch": "MarketWatch",
    "Seoul Economic Daily": "首尔经济日报",
    "Korea JoongAng Daily": "韩国中央日报",
    "The Economic Times": "经济时报",
    "Startup Fortune": "Startup Fortune",
    "Investing.com Canada": "Investing.com",
}

TERM_LABELS = {
    "S&P 500": "S&P 500（标普500指数）",
    "Nasdaq": "Nasdaq（纳斯达克指数）",
    "Dow": "Dow（道琼斯指数）",
    "Russell 2000": "Russell 2000（罗素2000指数）",
    "VIX": "VIX（恐慌指数）",
    "10Y美债": "10Y 美债（美国10年期国债收益率）",
    "WTI": "WTI（美国原油）",
    "KOSPI": "KOSPI（韩国综合指数）",
    "KOSDAQ": "KOSDAQ（韩国创业板指数）",
    "Samsung": "Samsung（三星电子）",
    "SK Hynix": "SK Hynix（SK 海力士）",
    "Nikkei": "Nikkei（日经225指数）",
    "TOPIX": "TOPIX（东证指数）",
    "Nvidia": "Nvidia（英伟达）",
}

TITLE_TRANSLATIONS = {
    "foreign demand for k-etfs expands beyond samsung, sk hynix to kospi 200": "韩国 ETF 外资需求扩大，资金关注点从三星、SK 海力士扩展到 KOSPI 200。",
    "stocks rally, while oil and dollar ease on middle east peace hopes by reuters": "油价和美元走弱，全球风险偏好短线改善。",
    "gold is rising as iran deal hopes reshape the hedge trade": "黄金上涨，说明避险资金仍未完全退场。",
    "japan's nikkei jumps past 65,000 mark for first time on iran talks optimism": "日经指数创新高，中东降温预期推升日本市场风险偏好。",
    "one-stock etf high reward, and high risk with double-or-less-than-nothing leverage": "韩国单一股票 ETF 杠杆风险升温，高收益背后波动也被放大。",
    "top 5 exporters account for 43.5% of total exports in q1, indicates worsening 'k-shaped' divide": "韩国出口集中度上升，头部企业占比扩大，经济分化风险加重。",
    "tsmc workers push for union, strike over bonus cuts despite record profits": "台积电员工因奖金削减推动工会和罢工，供应链劳资风险进入视野。",
    "nvidia lifts semiconductor risk appetite": "Nvidia（英伟达）带动半导体风险偏好，AI 主线仍有承接。",
    "treasury yields pressure tech stocks": "美国国债收益率压制科技股，成长股估值仍受利率牵制。",
}


def ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def now_china() -> datetime:
    return datetime.now(CHINA_TZ)


def briefing_window(now: datetime) -> tuple[datetime, datetime, str]:
    now = now.astimezone(CHINA_TZ)
    today = now.date()
    if now.time() < time(12, 30):
        start = datetime.combine(today - timedelta(days=1), time(18, 0), CHINA_TZ)
        end = datetime.combine(today, time(9, 0), CHINA_TZ)
        return start, end, "09:00"
    if now.time() < time(17, 0):
        start = datetime.combine(today, time(9, 0), CHINA_TZ)
        end = datetime.combine(today, time(12, 30), CHINA_TZ)
        return start, end, "12:30"
    start = datetime.combine(today, time(9, 0), CHINA_TZ)
    end = datetime.combine(today, time(17, 0), CHINA_TZ)
    return start, end, "17:00"


def cache_path(now: datetime, slot: str | None = None) -> Path:
    now = now.astimezone(CHINA_TZ)
    _, _, resolved_slot = briefing_window(now)
    slot = slot or resolved_slot
    return CACHE_DIR / f"market-brief-{now.date().isoformat()}-{slot.replace(':', '')}.json"


def resolve_market_time(query: str, base_now: datetime | None = None) -> datetime:
    base = (base_now or now_china()).astimezone(CHINA_TZ)
    text = (query or "").lower()
    if any(word in text for word in ["午盘", "午间", "中午"]):
        return base.replace(hour=12, minute=30, second=0, microsecond=0)
    if any(word in text for word in ["收盘", "盘后", "美股盘前", "ai 龙头盘前"]):
        return base.replace(hour=17, minute=0, second=0, microsecond=0)
    if any(word in text for word in ["早上", "早盘", "a股盘前", "开盘前"]):
        return base.replace(hour=9, minute=0, second=0, microsecond=0)
    return base


def default_dashboard() -> MarketDashboard:
    missing = MISSING_VALUE
    return MarketDashboard(
        china={
            "上证": missing,
            "深成指": missing,
            "创业板": missing,
            "沪深300": missing,
            "成交额": missing,
            "涨跌家数": missing,
            "强势板块": "待盘面确认",
            "弱势板块": "待盘面确认",
            "人民币/港股联动": "待确认",
        },
        us={
            "S&P 500": missing,
            "Nasdaq": missing,
            "Dow": missing,
            "Russell 2000": missing,
            "VIX": missing,
            "10Y美债": missing,
            "WTI/黄金": missing,
            "AI/半导体": "看 Nvidia、费半、内存链条",
        },
        korea={
            "KOSPI": missing,
            "KOSDAQ": missing,
            "Samsung": missing,
            "SK Hynix": missing,
            "外资流向": "待交易所确认",
            "半导体/存储链条": "看 Samsung、SK Hynix 与美股半导体共振",
        },
        japan={
            "Nikkei": missing,
            "TOPIX": missing,
            "日元/BOJ": "待确认",
        },
        variables={
            "美元": missing,
            "人民币": missing,
            "美债": missing,
            "油价": missing,
            "黄金": missing,
            "VIX": missing,
        },
    )


def fetch_dashboard() -> MarketDashboard:
    symbols = ",".join(QUOTE_SYMBOLS.values())
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={quote_plus(symbols)}"
    try:
        payload = fetch_json(url, DEFAULT_TIMEOUT)
        by_symbol = {row.get("symbol"): row for row in payload.get("quoteResponse", {}).get("result", [])}
    except Exception:
        by_symbol = fetch_chart_quotes(QUOTE_SYMBOLS.values())

    values = {label: quote_label(by_symbol.get(symbol)) for label, symbol in QUOTE_SYMBOLS.items()}
    dash = default_dashboard()
    return MarketDashboard(
        china={**dash.china, **{k: values[k] for k in ["上证", "深成指", "创业板", "沪深300"]}},
        us={
            **dash.us,
            "S&P 500": values["S&P 500"],
            "Nasdaq": values["Nasdaq"],
            "Dow": values["Dow"],
            "Russell 2000": values["Russell 2000"],
            "VIX": values["VIX"],
            "10Y美债": values["10Y美债"],
            "WTI/黄金": f"WTI {values['WTI']} / 黄金 {values['黄金']}",
        },
        korea={
            **dash.korea,
            "KOSPI": values["KOSPI"],
            "KOSDAQ": values["KOSDAQ"],
            "Samsung": values["Samsung"],
            "SK Hynix": values["SK Hynix"],
        },
        japan={**dash.japan, "Nikkei": values["Nikkei"], "TOPIX": values["TOPIX"], "日元/BOJ": values["日元"]},
        variables={
            "美元": "看 DXY 与离岸人民币",
            "人民币": values["人民币"],
            "美债": values["10Y美债"],
            "油价": values["WTI"],
            "黄金": values["黄金"],
            "VIX": values["VIX"],
        },
    )


def quote_label(row: dict | None) -> str:
    if not row:
        return "数据暂缺"
    price = row.get("regularMarketPrice")
    change_pct = row.get("regularMarketChangePercent")
    if price is None:
        return "数据暂缺"
    if change_pct is None:
        return f"{price:g}"
    sign = "+" if change_pct > 0 else ""
    return f"{price:g} ({sign}{change_pct:.2f}%)"


def fetch_live_market_snapshot(query: str = "", timeout: int = DEFAULT_TIMEOUT) -> LiveMarketSnapshot:
    """Fetch a frontstage real-time-ish market snapshot without claiming a full report refresh."""
    if requests_foreign_market_without_china(query):
        return LiveMarketSnapshot(
            ok=False,
            as_of="",
            source="外盘行情快照",
            lines=[],
            source_status="实时源：暂不可用",
            note="当前前台只接入内地指数行情源；外盘实时源未接通，不能拿本地指数冒充全球市场。",
            error="foreign_live_source_not_configured",
        )
    try:
        return fetch_sina_a_share_snapshot(timeout=timeout)
    except Exception as exc:
        try:
            return fetch_yahoo_china_snapshot(timeout=timeout)
        except Exception as fallback_exc:
            return LiveMarketSnapshot(
                ok=False,
                as_of="",
                source="行情快照",
                lines=[],
                source_status="实时源：暂不可用",
                note="外部行情源拉取失败，前台只能降级到最近缓存。",
                error=f"{type(exc).__name__}; {type(fallback_exc).__name__}",
            )


def requests_foreign_market_without_china(query: str) -> bool:
    text = str(query or "").lower()
    return any(marker in text for marker in LIVE_FOREIGN_MARKERS) and not any(marker in text for marker in LIVE_CHINA_MARKERS)


def fetch_sina_a_share_snapshot(timeout: int = DEFAULT_TIMEOUT) -> LiveMarketSnapshot:
    symbols = ",".join(SINA_A_SHARE_SYMBOLS)
    url = f"https://hq.sinajs.cn/list={symbols}"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 VELA market assistant",
            "Referer": "https://finance.sina.com.cn",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("gb18030", errors="replace")
    rows = parse_sina_index_rows(raw)
    if len(rows) < 2:
        raise ValueError("sina snapshot returned too few rows")
    return LiveMarketSnapshot(
        ok=True,
        as_of=f"{now_china():%Y-%m-%d %H:%M} 北京时间",
        source="新浪财经行情快照",
        lines=rows,
        source_status="实时源：已接入",
        note="行情快照按交易所交易时段解释；收盘后代表最新收盘/延时快照。",
    )


def parse_sina_index_rows(raw: str) -> list[str]:
    rows: list[str] = []
    matches = re.findall(r'var hq_str_(s_[a-z0-9]+)="([^"]*)";', raw or "")
    by_symbol = {symbol: body for symbol, body in matches}
    for symbol, fallback_name in SINA_A_SHARE_SYMBOLS.items():
        body = by_symbol.get(symbol)
        if not body:
            continue
        fields = [field.strip() for field in body.split(",")]
        if len(fields) < 4:
            continue
        name = fields[0] or fallback_name
        try:
            price = float(fields[1])
            change = float(fields[2])
            pct = float(fields[3])
        except ValueError:
            continue
        rows.append(f"{name} {price:.2f}（{signed_number(change)}，{signed_number(pct, '%')}）")
    return rows


def signed_number(value: float, suffix: str = "") -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}{suffix}"


def fetch_yahoo_china_snapshot(timeout: int = DEFAULT_TIMEOUT) -> LiveMarketSnapshot:
    symbols = {key: QUOTE_SYMBOLS[key] for key in ["上证", "深成指", "创业板", "沪深300"]}
    joined = ",".join(symbols.values())
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={quote_plus(joined)}"
    payload = fetch_json(url, timeout)
    by_symbol = {row.get("symbol"): row for row in payload.get("quoteResponse", {}).get("result", [])}
    rows = []
    label_map = {"上证": "上证指数", "深成指": "深证成指", "创业板": "创业板指", "沪深300": "沪深300"}
    for label, symbol in symbols.items():
        rendered = quote_label(by_symbol.get(symbol))
        if rendered != "数据暂缺":
            rows.append(f"{label_map[label]} {rendered}")
    if len(rows) < 2:
        raise ValueError("yahoo snapshot returned too few rows")
    return LiveMarketSnapshot(
        ok=True,
        as_of=f"{now_china():%Y-%m-%d %H:%M} 北京时间",
        source="Yahoo Finance 行情快照",
        lines=rows,
        source_status="实时源：已接入",
        note="行情快照按交易所交易时段解释；收盘后代表最新收盘/延时快照。",
    )


def fetch_json(url: str, timeout: int) -> dict:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 VELA market assistant"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_chart_quotes(symbols: Iterable[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for symbol in symbols:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?range=5d&interval=1d"
        try:
            payload = fetch_json(url, DEFAULT_TIMEOUT)
            result = (payload.get("chart", {}).get("result") or [None])[0]
            if not result:
                continue
            meta = result.get("meta", {})
            price = meta.get("regularMarketPrice")
            previous = meta.get("chartPreviousClose")
            closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
            closes = [item for item in closes if item is not None]
            if price is None and closes:
                price = closes[-1]
            if previous is None and len(closes) >= 2:
                previous = closes[-2]
            change_pct = None
            if price is not None and previous:
                change_pct = ((price - previous) / previous) * 100
            rows[symbol] = {
                "symbol": symbol,
                "regularMarketPrice": price,
                "regularMarketChangePercent": change_pct,
            }
        except Exception:
            continue
    return rows


def fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 VELA market assistant"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def google_news_url(query: str) -> str:
    return "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"


def parse_rss(data: bytes) -> list[MarketNewsItem]:
    root = ElementTree.fromstring(data)
    items: list[MarketNewsItem] = []
    for node in root.findall(".//item"):
        raw_title = text_of(node, "title")
        title = clean_title(raw_title)
        if not title or is_noise(title):
            continue
        source_node = node.find("source")
        source = "Google News"
        if source_node is not None and (source_node.text or "").strip():
            source = unescape(source_node.text.strip())
        link = text_of(node, "link")
        published = parse_pubdate(text_of(node, "pubDate"))
        tags = infer_market_tags(title)
        items.append(
            MarketNewsItem(
                title=title,
                source=source,
                published_at=published.isoformat(),
                market_tags=tags,
                impact_type=infer_impact_type(title, tags),
                impact_score=infer_impact_score(title, tags),
                direction=infer_direction(title),
                reason=infer_reason(tags),
                source_url=link,
            )
        )
    return items


def text_of(node: ElementTree.Element, child: str) -> str:
    found = node.find(child)
    return unescape((found.text or "").strip()) if found is not None else ""


def parse_pubdate(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return now_china()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(CHINA_TZ)


def clean_title(title: str) -> str:
    title = unescape(re.sub(r"\s+", " ", title)).strip()
    title = re.sub(r" - [^-]+$", "", title)
    return title


def is_noise(title: str) -> bool:
    lower = title.lower()
    return any(word in lower for word in NOISE_KEYWORDS)


def infer_market_tags(title: str) -> list[str]:
    lower = title.lower()
    tags = [tag for tag, words in TAG_KEYWORDS.items() if any(word.lower() in lower for word in words)]
    return tags or ["global"]


def infer_impact_type(title: str, tags: list[str]) -> list[str]:
    lower = title.lower()
    if "geopolitics" in tags:
        return ["地缘", "风险偏好"]
    if "us_10y" in tags or "usd" in tags:
        return ["利率", "汇率"]
    if "oil" in tags or "gold" in tags:
        return ["油价", "避险"]
    if "semiconductors" in tags:
        return ["AI", "半导体"]
    if any(tag in tags for tag in ["china_a", "us_equities", "korea", "japan"]):
        return ["风险偏好", "权益市场"]
    if any(word in lower for word in ["fed", "inflation", "central bank"]):
        return ["利率", "宏观政策"]
    return ["市场信号"]


def infer_impact_score(title: str, tags: list[str]) -> int:
    lower = title.lower()
    score = 2
    if any(tag in tags for tag in ["china_a", "us_equities", "korea", "semiconductors", "us_10y", "usd"]):
        score += 1
    if any(word in lower for word in ["surge", "plunge", "slump", "war", "sanction", "fed", "tariff", "earnings", "export"]):
        score += 1
    if len(tags) >= 3:
        score += 1
    return max(1, min(5, score))


def infer_direction(title: str) -> str:
    lower = title.lower()
    bearish = ["fall", "falls", "drop", "drops", "slump", "selloff", "risk", "war", "sanction", "tariff", "yield rise", "strong dollar"]
    bullish = ["rise", "rises", "gain", "gains", "rally", "record", "peace", "deal", "cut rates", "stimulus"]
    if any(word in lower for word in bearish):
        return "bearish"
    if any(word in lower for word in bullish):
        return "bullish"
    return "uncertain"


def infer_reason(tags: list[str]) -> str:
    if "semiconductors" in tags:
        return "牵动 AI、半导体和存储链条估值。"
    if "us_10y" in tags or "usd" in tags:
        return "影响全球风险偏好、汇率和成长股折现率。"
    if "china_a" in tags:
        return "影响 A股风险偏好、人民币和北向/港股联动。"
    if "korea" in tags:
        return "韩国市场是半导体周期和外资风险偏好的前哨。"
    if "geopolitics" in tags:
        return "地缘风险会穿透到能源、航运、军工和避险资产。"
    return "进入市场定价的高频变量。"


def fetch_market_news(max_items: int = DEFAULT_MAX_NEWS) -> list[MarketNewsItem]:
    items: list[MarketNewsItem] = []
    for query in SEARCH_QUERIES:
        try:
            items.extend(parse_rss(fetch_url(google_news_url(query))))
        except Exception:
            continue
    return select_news(items, max_items)


def select_news(items: Iterable[MarketNewsItem], max_items: int) -> list[MarketNewsItem]:
    unique: dict[str, MarketNewsItem] = {}
    for item in items:
        key = re.sub(r"\W+", "", item.title.lower())[:90]
        existing = unique.get(key)
        if existing is None or item.impact_score > existing.impact_score:
            unique[key] = item
    selected = sorted(
        unique.values(),
        key=lambda item: (weighted_market_score(item), item.impact_score, len(item.market_tags), item.published_at),
        reverse=True,
    )
    return selected[:max_items]


def weighted_market_score(item: MarketNewsItem) -> int:
    return max((MARKET_WEIGHT_BY_TAG.get(tag, 1) for tag in item.market_tags), default=1)


def build_market_brief(query: str = "", now: datetime | None = None, force_refresh: bool = False) -> MarketBrief:
    now = resolve_market_time(query, now or now_china())
    if not force_refresh:
        cached = load_cached_brief(now)
        if cached is not None:
            return cached
    start, end, slot = briefing_window(now)
    dashboard = fetch_dashboard()
    news = fetch_market_news()
    if not news:
        news = [
            MarketNewsItem(
                title="实时新闻检索暂缺，先以市场仪表盘和关键变量控风险",
                source="VELA",
                published_at=now.isoformat(),
                market_tags=["global", "china_a", "us_equities"],
                impact_type=["data_availability"],
                impact_score=1,
                direction="uncertain",
                reason="无实时新闻时，不编故事，只收紧观察清单。",
            )
        ]
    brief = MarketBrief(
        as_of=now.isoformat(),
        window_label=f"{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M} 中国时间",
        slot=slot,
        dashboard=dashboard,
        news=news,
        good_signs=derive_good_signs(news),
        bad_signs=derive_bad_signs(news),
        main_line=derive_main_line(query, news),
        vela_judgment=derive_vela_judgment(now, query, news),
        watch_next=derive_watch_next(query, now, news),
    )
    save_cached_brief(brief, now)
    return brief


def derive_good_signs(news: list[MarketNewsItem]) -> list[str]:
    signs: list[str] = []
    if any(item.direction == "bullish" and "china_a" in item.market_tags for item in news):
        signs.append("A股相关利多进入定价，但必须等成交量和涨跌家数确认。")
    if any(item.direction == "bullish" and "semiconductors" in item.market_tags for item in news):
        signs.append("AI/半导体链条仍有承接，韩国和美股科技线可作为前哨。")
    if any(item.direction == "bullish" and ("usd" in item.market_tags or "us_10y" in item.market_tags) for item in news):
        signs.append("美元或美债压力若缓和，成长股估值会先松一口气。")
    if not signs:
        signs.append("没有强行把噪音写成利好，这是今天最干净的正面信号。")
    if len(signs) == 1:
        signs.append("市场变量尚未互相打架，至少还没到必须防御的程度。")
    return signs[:4]


def derive_bad_signs(news: list[MarketNewsItem]) -> list[str]:
    signs = []
    if any("us_10y" in item.market_tags or "usd" in item.market_tags for item in news):
        signs.append("美债和美元若继续走硬，A股、韩股和美股成长线都会被压估值。")
    if any("geopolitics" in item.market_tags or "oil" in item.market_tags for item in news):
        signs.append("地缘和油价会把风险偏好切薄，反弹容易变成短线换气。")
    if any(item.direction == "bearish" and "semiconductors" in item.market_tags for item in news):
        signs.append("半导体链条如果先走弱，韩国、美股科技和A股科技题材都会被拖住。")
    if not signs:
        signs.append("坏迹象还没排成队，但成交和外资如果不给力，所有反弹都先按试探处理。")
    if len(signs) == 1:
        signs.append("资金方向没有确认前，别把一根阳线当成战略转折。")
    return signs[:4]


def derive_main_line(query: str, news: list[MarketNewsItem]) -> str:
    tags = {tag for item in news for tag in item.market_tags}
    if "semiconductors" in tags or "korea" in tags:
        return "当前主线是 AI/半导体链条能否继续承担风险偏好。更像震荡修复，不是无条件趋势延续；若美债、美元和韩国半导体同时转弱，阶段性调整风险会抬头。"
    if "us_10y" in tags or "usd" in tags:
        return "当前主线不是单一股指，是美元、美债和风险资产的拔河。先按震荡修复处理；只有成交、资金流向和利率变量共振，才配谈趋势延续。"
    if "china_a" in tags or "a股" in query.lower():
        return "A股主线先看成交额、资金方向和强弱板块扩散。指数好看但量不跟，就是漂亮的空壳；阶段性调整风险取决于人民币、美债和科技线是否同时走弱。"
    return "主线还在风险偏好和流动性之间摆动，更像等待确认而不是趋势加速。先看变量，不急着给市场戴王冠。"


def derive_vela_judgment(now: datetime, query: str, news: list[MarketNewsItem]) -> list[str]:
    now = now.astimezone(CHINA_TZ)
    us_timing = "美股盘前/期货" if now.time() >= time(17, 0) else "美股和前夜/期货线"
    return [
        "现在不是给市场加皇冠的时候。成交量、资金方向和美债变量还没形成共振，先按震荡修复处理，别把半山腰误判成登基大典。",
        f"{us_timing}只看会改风险偏好的东西：Nasdaq、S&P 500、VIX、10Y美债和 AI 龙头。漂亮叙事没有成交确认，就是涂了口红的噪音。",
        "韩国盯 Samsung、SK Hynix。它们扛住，半导体链还有火；它们先塌，A股科技线别硬装神勇。",
    ]


def derive_watch_next(query: str, now: datetime, news: list[MarketNewsItem]) -> list[str]:
    return [
        "A股成交额是否放大，强势板块是否从少数题材扩散到权重。",
        "美元、10Y美债、离岸人民币是否同时压风险资产。",
        "Samsung/SK Hynix、Nvidia/费半是否同向，确认半导体链条强弱。",
        "油价和地缘新闻是否从标题风险变成真实通胀压力。",
    ]


def save_cached_brief(brief: MarketBrief, now: datetime | None = None) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(now or datetime.fromisoformat(brief.as_of), brief.slot)
    payload = asdict(brief)
    payload["schema_version"] = MARKET_BRIEF_SCHEMA_VERSION
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cached_brief(now: datetime) -> MarketBrief | None:
    path = cache_path(now)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != MARKET_BRIEF_SCHEMA_VERSION:
            return None
        brief = brief_from_dict(payload)
    except Exception:
        return None
    if not cache_matches_current_window(brief, now):
        return None
    return brief


def load_latest_cached_brief(now: datetime | None = None) -> tuple[MarketBrief | None, Path | None]:
    now = (now or now_china()).astimezone(CHINA_TZ)
    current = load_cached_brief(now)
    if current is not None:
        return current, cache_path(now, current.slot)
    if not CACHE_DIR.exists():
        return None, None
    for path in sorted(CACHE_DIR.glob("market-brief-*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != MARKET_BRIEF_SCHEMA_VERSION:
                continue
            return brief_from_dict(payload), path
        except Exception:
            continue
    return None, None


def build_cached_market_brief(query: str = "", now: datetime | None = None) -> MarketBrief | None:
    resolved_now = resolve_market_time(query, now or now_china())
    brief, _ = load_latest_cached_brief(resolved_now)
    return brief


def market_freshness_status(query: str = "", now: datetime | None = None) -> MarketFreshnessStatus:
    resolved_now = resolve_market_time(query, now or now_china())
    current = load_cached_brief(resolved_now)
    if current is not None:
        updated = datetime.fromisoformat(current.as_of).astimezone(CHINA_TZ)
        return MarketFreshnessStatus(
            data_status="cached",
            last_updated=f"{updated:%Y-%m-%d %H:%M} 北京时间",
            source_type="cache",
            refresh_available=True,
            refresh_in_progress=False,
            confidence_note="不是实时直播；适合方向判断，不适合秒级交易依据。",
            slot=current.slot,
            cache_path=str(cache_path(resolved_now, current.slot)),
            real_time_source_available=False,
            cached_summary_available=True,
            model_generated_only=False,
            unavailable=False,
        )
    latest, path = load_latest_cached_brief(resolved_now)
    if latest is not None:
        updated = datetime.fromisoformat(latest.as_of).astimezone(CHINA_TZ)
        return MarketFreshnessStatus(
            data_status="stale",
            last_updated=f"{updated:%Y-%m-%d %H:%M} 北京时间",
            source_type="cache",
            refresh_available=True,
            refresh_in_progress=False,
            confidence_note="当前时间段没有命中最新缓存；可先参考最近缓存，但要降低实时性权重。",
            slot=latest.slot,
            cache_path=str(path or ""),
            real_time_source_available=False,
            cached_summary_available=True,
            model_generated_only=False,
            unavailable=False,
        )
    return MarketFreshnessStatus(
        data_status="unavailable",
        last_updated="暂无可靠缓存",
        source_type="unknown",
        refresh_available=True,
        refresh_in_progress=False,
        confidence_note="本地没有可用市场缓存；需要外部检索/API 才能形成新报告。",
        real_time_source_available=False,
        cached_summary_available=False,
        model_generated_only=False,
        unavailable=True,
    )


def format_status_boundary(status: MarketFreshnessStatus) -> str:
    cache_text = "可用" if status.cached_summary_available else "不可用"
    model_text = "是" if status.model_generated_only else "否"
    availability = "不可用" if status.unavailable else ("缓存可用" if status.cached_summary_available else "待刷新")
    return f"状态边界：实时源：未接入；缓存摘要：{cache_text}；模型仅生成：{model_text}；可用性：{availability}。"


def format_freshness_status(status: MarketFreshnessStatus) -> str:
    if status.data_status == "cached":
        first_line = f"不是实时直播。当前报告基于 {status.slot or '最近一次'} 缓存，适合做方向判断，不适合当秒级交易信号。"
        cache_state = "当前时段缓存可用"
        source = "本地市场缓存"
    elif status.data_status == "stale":
        first_line = f"不是实时直播。当前只有 {status.slot or '最近一次'} 旧缓存，可以参考方向，不能当最新盘面。"
        cache_state = "只有旧缓存"
        source = "本地市场缓存"
    else:
        first_line = "不是实时直播。当前没有可靠缓存，暂不生成新判断。"
        cache_state = "无可用缓存"
        source = "未接入实时源"
    return "\n".join(
        [
            first_line,
            f"更新时间：{status.last_updated}",
            f"数据来源：{source}，{cache_state}。",
            format_status_boundary(status),
            f"刷新状态：{'可刷新，当前未在前台刷新。' if status.refresh_available else '暂不可刷新。'}",
            f"可信度：{status.confidence_note}",
        ]
    )


def cache_matches_current_window(brief: MarketBrief, now: datetime) -> bool:
    start, end, slot = briefing_window(now)
    expected_label = f"{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M} 中国时间"
    return brief.slot == slot and brief.window_label == expected_label


def brief_from_dict(payload: dict) -> MarketBrief:
    dash = payload.get("dashboard", {})
    return MarketBrief(
        as_of=payload["as_of"],
        window_label=payload["window_label"],
        slot=payload["slot"],
        dashboard=MarketDashboard(
            china=dict(dash.get("china", {})),
            us=dict(dash.get("us", {})),
            korea=dict(dash.get("korea", {})),
            japan=dict(dash.get("japan", {})),
            variables=dict(dash.get("variables", {})),
        ),
        news=[MarketNewsItem(**item) for item in payload.get("news", [])],
        good_signs=list(payload.get("good_signs", [])),
        bad_signs=list(payload.get("bad_signs", [])),
        main_line=payload.get("main_line", ""),
        vela_judgment=list(payload.get("vela_judgment", [])),
        watch_next=list(payload.get("watch_next", [])),
    )


def format_market_brief(brief: MarketBrief, detail: bool = False) -> str:
    as_of = datetime.fromisoformat(brief.as_of).astimezone(CHINA_TZ)
    slot = brief.slot or briefing_window(as_of)[2]
    slot_profile = market_slot_profile(slot)
    short_slot = {"09:00": "09:00 开盘前", "12:30": "12:30 午盘后", "17:00": "17:00 收盘后"}.get(slot, f"{slot} 更新")
    lines = [
        f"VELA 市场简报｜{short_slot}",
        f"时间：{as_of:%Y-%m-%d}，北京时间",
        f"状态：{slot_profile['label']}",
        "",
        "60秒判断",
        "- A股：偏震荡修复，成交量和涨跌家数没确认前，不把反弹当胜利。",
        "- 美股：风险偏好看 AI 龙头、美元、美债和 VIX；盘前乐观不等于现金盘买账。",
        "- 韩国：半导体链条仍是加分项，但 Samsung（三星电子）和 SK Hynix（SK 海力士）不能先掉队。",
        "- 今日变量：美债、美元、人民币、油价、AI 龙头，其次才是地缘标题。",
        "",
        "A股",
        "- " + join_fields(brief.dashboard.china, ["上证", "深成指", "创业板", "沪深300"]),
        "- " + join_fields(brief.dashboard.china, ["成交额", "涨跌家数", "强势板块", "弱势板块", "人民币/港股联动"]),
        "",
        "美股",
        "- " + join_fields(brief.dashboard.us, ["S&P 500", "Nasdaq", "Dow", "VIX", "10Y美债"]),
        "- " + join_fields(brief.dashboard.us, ["WTI/黄金", "AI/半导体"]),
        "",
        "韩国 / 日本",
        "- 韩国：" + join_fields(brief.dashboard.korea, ["KOSPI", "Samsung", "SK Hynix", "外资流向", "半导体/存储链条"]),
        "- 日本：" + join_fields({**brief.dashboard.japan, **brief.dashboard.variables}, ["Nikkei", "TOPIX", "日元/BOJ", "美元", "人民币", "油价"]),
    ]
    if brief.news:
        lines.extend(["", "关键风险"])
        news_limit = DEFAULT_MAX_NEWS if detail else FRONT_MAX_NEWS
        for idx, item in enumerate(brief.news[:news_limit], 1):
            lines.append(format_news_line(idx, item))
    lines.extend(f"- 好迹象：{item}" for item in brief.good_signs[:2])
    lines.extend(f"- 坏迹象：{item}" for item in brief.bad_signs[:2])
    lines.extend(["", "主线判断", brief.main_line])
    lines.extend(["", "VELA 判断"])
    lines.extend(f"- {item}" for item in brief.vela_judgment)
    lines.extend(["", "下一次观察点"])
    lines.extend(f"- {item}" for item in brief.watch_next)
    return "\n".join(lines)


_FRONTSTAGE_TRANSLATIONS = (
    ("Samsung/SK Hynix", "三星电子/SK海力士"),
    ("SK Hynix", "SK海力士"),
    ("Samsung", "三星电子"),
    ("Nvidia", "英伟达"),
    ("Nasdaq", "纳斯达克"),
    ("S&P 500", "标普500"),
    ("10Y", "10年期"),
)


def _market_frontstage_text(text: str) -> str:
    translated = text
    for source, target in _FRONTSTAGE_TRANSLATIONS:
        translated = translated.replace(source, target)
    return translated


def format_market_frontstage_summary(brief: MarketBrief) -> str:
    lines = [
        "60秒判断",
        "- A股：偏震荡修复，成交量和涨跌家数没确认前，不把反弹当胜利。",
        "- 美股：风险偏好看 AI 龙头、美元、美债和 VIX；盘前乐观不等于现金盘买账。",
        "- 韩国：半导体链条仍是加分项，但三星电子和 SK 海力士不能先掉队。",
        "- 今日变量：美债、美元、人民币、油价、AI 龙头，其次才是地缘标题。",
    ]
    if brief.main_line:
        lines.extend(["", f"判断：{brief.main_line}"])
    if brief.vela_judgment:
        lines.extend(["", "要点："])
        lines.extend(f"- {_market_frontstage_text(item)}" for item in brief.vela_judgment[:2])
    if brief.watch_next:
        watch_next = [_market_frontstage_text(item) for item in brief.watch_next[:3]]
        lines.extend(["", "下一观察点：" + "；".join(watch_next)])
    return "\n".join(lines)


def format_live_market_frontstage(
    snapshot: LiveMarketSnapshot,
    *,
    fallback_brief: MarketBrief | None = None,
    fallback_status: MarketFreshnessStatus | None = None,
) -> str:
    if snapshot.ok:
        lines = [
            f"{snapshot.source_status}（{snapshot.source}，{snapshot.as_of}）",
            "A股快照：",
            *[f"- {line}" for line in snapshot.lines[:4]],
            "判断：今天先按盘面快照处理；上证与沪深300没同向走强、成交额没放大前，不把反弹当趋势，仓位只按试探。",
            "下一步：盯成交额、人民币/美债、强弱板块扩散；要完整来源，再说“展开市场来源”。",
        ]
        if snapshot.note:
            lines.append(f"边界：{snapshot.note}")
        return "\n".join(lines)

    lines = [f"{snapshot.source_status or '实时源：暂不可用'}；缓存降级。"]
    if snapshot.note:
        lines.append(f"边界：{snapshot.note}")
    if fallback_status is not None:
        lines.append(f"最近缓存：{fallback_status.last_updated}，只做方向判断。")
    if fallback_brief is not None:
        if snapshot.error == "foreign_live_source_not_configured" or "外盘" in snapshot.source:
            lines.extend(
                [
                    "判断：全球/外盘实时源没回来前，不下新的盘中结论；只按缓存看风险方向，不把本地指数外推成全球市场。",
                    "下一步：先等外盘实时源接通，或明确说“展开缓存报告”；旧数据只配做路标，不配当方向盘。",
                ]
            )
        else:
            lines.extend(
                [
                    "判断：实时源没回来前，不下新的盘中结论；按缓存看，A股仍按震荡修复处理，仓位只留试探。",
                    "下一步：先等实时源恢复，或明确说“展开缓存报告”；别把旧数据当今天的刀。人类已经很会自欺，交易别再添一把火。",
                ]
            )
    else:
        lines.extend(
            [
                "判断：没有实时源，也没有可靠缓存，暂不生成盘面结论；仓位不加。",
                "下一步：先接通行情/API，再谈今天怎么做；现在硬猜就是给噪音戴皇冠。",
            ]
        )
    return "\n".join(lines)


def market_slot_profile(slot: str) -> dict[str, str]:
    if slot == "09:00":
        return {
            "label": "09:00 A股盘前 / 前夜美股 / 外部风险",
            "a_share": "A股盘前，不写盘中；重点看前夜美股、人民币、港股联动和影响交易决策的政经大事",
            "us_equity": "前夜美股与期货线，判断风险偏好是否延续",
            "korea": "日韩早盘信号只作前哨，不抢结论",
        }
    if slot == "12:30":
        return {
            "label": "12:30 A股午盘后 / 日韩盘中 / 板块轮动",
            "a_share": "A股午盘后，重点看板块轮动、资金方向和上午成交质量",
            "us_equity": "美股看隔夜余波与期货线，等待新数据",
            "korea": "日韩盘中，韩国半导体和外资扰动只按盘中信号处理",
        }
    return {
        "label": "17:00 A股收盘 / 日韩收盘 / 美股盘前",
        "a_share": "A股收盘后，重点看成交量、资金流向和强弱板块是否扩散",
        "us_equity": "美股盘前，只看期货、美债、美元和 AI 龙头盘前风险",
        "korea": "日韩收盘后，看韩国半导体链条是否给明天风险偏好留火种",
    }


def format_news_line(idx: int, item: MarketNewsItem) -> str:
    title = chinese_news_summary(item)
    source = chinese_source(item.source, item.title)
    reason = item.reason.rstrip("。")
    return f"{idx}. {title}为什么影响市场：{reason}。来源：{source}。"


def join_fields(data: dict[str, str], keys: list[str]) -> str:
    return "；".join(f"{display_market_term(key)} {data.get(key) or MISSING_VALUE}" for key in keys)


def display_market_term(term: str) -> str:
    return TERM_LABELS.get(term, term)


def chinese_source(source: str, title: str = "") -> str:
    text = f"{source} {title}"
    for english, chinese in SOURCE_CN.items():
        if english.lower() in text.lower():
            return chinese
    return source or "未标明来源"


def chinese_news_summary(item: MarketNewsItem) -> str:
    title = canonical_news_title(item.title)
    translated = TITLE_TRANSLATIONS.get(title.lower())
    if translated:
        return ensure_sentence(translated)
    lower = title.lower()
    if "nvidia" in lower or "semiconductor" in lower or "chip" in lower:
        return "AI / 半导体链条出现新的高影响信号，重点看 Nvidia（英伟达）和韩国存储线是否共振。"
    if "treasury" in lower or "yield" in lower or "dollar" in lower:
        return "美债或美元变量正在影响风险资产，成长股估值会先被重新定价。"
    if "oil" in lower or "gold" in lower:
        return "油价或黄金出现新的避险定价，说明资金还没完全解除警报。"
    if "kospi" in lower or "samsung" in lower or "hynix" in lower or "korea" in lower:
        return "韩国市场出现新的资金信号，半导体链条和外资风险偏好需要盯紧。"
    if "nikkei" in lower or "japan" in lower:
        return "日本市场出现新的风险偏好信号，日元和全球资金流向需要一起看。"
    if "a-share" in lower or "yuan" in lower or "china" in lower:
        return "A股相关变量出现变化，重点看人民币、成交额和港股科技联动。"
    return "出现新的市场信号，暂按高影响变量观察，不把英文标题原样塞给你。"


def canonical_news_title(title: str) -> str:
    title = clean_title(title)
    title = re.sub(r"\s+", " ", title).strip().rstrip(".。")
    return title


def ensure_sentence(text: str) -> str:
    text = text.strip()
    if text.endswith(("。", "！", "？")):
        return text
    return text + "。"


def cleanup_lock_file(path: str) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def main(argv: list[str]) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="*", help="market question")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--refresh-slot", choices=["0900", "1230", "1700"], default="")
    parser.add_argument("--lock-file", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    now = now_china()
    if args.refresh_slot:
        hour, minute = {"0900": (9, 0), "1230": (12, 30), "1700": (17, 0)}[args.refresh_slot]
        now = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    try:
        brief = build_market_brief(" ".join(args.query), now=now, force_refresh=args.refresh or bool(args.refresh_slot))
        if args.json:
            print(json.dumps(asdict(brief), ensure_ascii=False, indent=2))
        else:
            print(format_market_brief(brief))
    finally:
        cleanup_lock_file(args.lock_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
