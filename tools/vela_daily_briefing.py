from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
import subprocess
import sys
import json
from typing import Iterable
from urllib.parse import quote_plus
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


CHINA_TZ = timezone(timedelta(hours=8))
DEFAULT_MAX_ITEMS = 20
CC_CONNECT_EXE = r"C:\Users\Admin\AppData\Roaming\npm\node_modules\cc-connect\bin\cc-connect.exe"


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    link: str
    published: datetime
    category: str


CATEGORY_LABELS = {
    "geopolitics": "军政 / 地缘",
    "markets": "金融 / 市场",
    "tech": "科技 / AI / 半导体",
}

CATEGORY_TARGETS = {
    "geopolitics": 7,
    "markets": 8,
    "tech": 5,
}

FILL_ORDER = ["markets", "tech", "geopolitics"]

QUERY_GROUPS = {
    "geopolitics": [
        "world military geopolitics diplomacy sanctions conflict Reuters OR AP when:1d",
        "Ukraine Russia Iran Gaza Taiwan security Reuters OR AP when:1d",
    ],
    "markets": [
        "US stock market S&P 500 Nasdaq Dow futures Treasury yields Fed Reuters CNBC when:1d",
        "China A-shares Shanghai Composite Shenzhen Component CSI 300 yuan Reuters Bloomberg when:1d",
        "Japan market Nikkei TOPIX yen BOJ Reuters CNBC when:1d",
        "South Korea market KOSPI won Samsung SK Hynix Bank of Korea Reuters when:1d",
        "global markets oil dollar bonds stocks central bank Reuters CNBC when:1d",
    ],
    "tech": [
        "AI semiconductor chips Nvidia OpenAI Microsoft cybersecurity Reuters when:1d",
        "technology regulation antitrust chips artificial intelligence TechCrunch Reuters when:1d",
    ],
}

ZH_QUERY_GROUPS = {
    "geopolitics": [
        "美国 伊朗 停火 核谈判 霍尔木兹 路透 AP",
        "俄乌 乌克兰 俄罗斯 导弹 无人机 路透",
        "以色列 加沙 黎巴嫩 停火 路透",
        "台海 南海 防务 制裁 外交 路透",
    ],
    "markets": [
        "美股 标普500 纳斯达克 道指 美债 美元 油价 路透 彭博 CNBC",
        "A股 上证 深成指 创业板 沪深300 人民币 成交量",
        "日本股市 日经 TOPIX 日元 日本央行",
        "韩国股市 KOSPI 三星 SK海力士 韩元",
    ],
    "tech": [
        "AI 英伟达 OpenAI Anthropic 半导体 芯片 监管 路透 彭博",
        "人工智能 网络安全 算力 数据中心 微软 谷歌",
    ],
}

RSS_FEEDS = {
    "geopolitics": [
        "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.theguardian.com/world/rss",
    ],
    "markets": [
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://www.theguardian.com/business/rss",
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    ],
    "tech": [
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://www.theguardian.com/technology/rss",
        "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    ],
}

CATEGORY_KEYWORDS = {
    "geopolitics": [
        "war",
        "military",
        "defence",
        "defense",
        "army",
        "navy",
        "air force",
        "missile",
        "drone",
        "sanction",
        "border",
        "ceasefire",
        "peace",
        "attack",
        "security",
        "nato",
        "election",
        "ukraine",
        "russia",
        "iran",
        "israel",
        "gaza",
        "taiwan",
        "china",
        "pakistan",
        "troops",
        "hypersonic",
        "kyiv",
        "armenia",
        "俄乌",
        "俄罗斯",
        "乌克兰",
        "基辅",
        "导弹",
        "无人机",
        "伊朗",
        "美国",
        "以色列",
        "加沙",
        "黎巴嫩",
        "台海",
        "南海",
        "防务",
        "制裁",
        "外交",
        "停火",
        "核谈判",
        "高超音速",
    ],
    "markets": [
        "market",
        "stock",
        "shares",
        "s&p",
        "nasdaq",
        "dow",
        "nikkei",
        "topix",
        "kospi",
        "a-share",
        "a-shares",
        "shanghai composite",
        "shenzhen",
        "csi 300",
        "yuan",
        "won",
        "oil",
        "brent",
        "wti",
        "dollar",
        "yen",
        "bond",
        "yield",
        "treasury",
        "fed",
        "central bank",
        "inflation",
        "commodity",
        "gold",
        "bitcoin",
        "crypto",
        "earnings",
        "export",
        "bid",
        "offer",
        "acquisition",
        "merger",
        "fertiliser",
        "fertilizer",
        "sulphur",
        "sulfur",
        "supply",
        "supplies",
        "美股",
        "标普",
        "纳斯达克",
        "道指",
        "美债",
        "美元",
        "油价",
        "黄金",
        "a股",
        "上证",
        "深成指",
        "创业板",
        "沪深300",
        "人民币",
        "日经",
        "韩国股市",
        "日本股市",
    ],
    "tech": [
        "ai",
        "artificial intelligence",
        "chip",
        "semiconductor",
        "nvidia",
        "openai",
        "anthropic",
        "microsoft",
        "google",
        "cyber",
        "security",
        "datacenter",
        "data centre",
        "cloud",
        "model",
        "regulation",
        "antitrust",
        "人工智能",
        "芯片",
        "半导体",
        "算力",
        "数据中心",
        "网络安全",
    ],
}

NEGATIVE_KEYWORDS = {
    "all": [
        "podcast",
        "questions answered",
        "your questions",
        "ivf",
        "birthrate",
        "gunman",
        "shooting",
        "shot",
        "killed",
        "beach",
        "obituary",
        "dies",
        "died",
        "conbini",
        "empire",
        "sales",
        "deals",
        "as it happened",
        "live updates",
        "live:",
        "luxury",
        "heritage gold",
        "homegrown luxury",
    ],
    "geopolitics": [
        "student",
        "university",
        "tourist",
        "sports",
        "shark",
        "beach",
        "ivf",
        "birthrate",
        "podcast",
        "questions answered",
        "your questions",
        "obituary",
        "dies",
        "died",
    ],
    "markets": ["ai security", "game", "teacher", "student", "letter", "retire", "multi-job", "beer"],
    "tech": [
        "dlc",
        "game",
        "gaming",
        "deals",
        "sale",
        "sales",
        "piano",
        "teacher",
        "kitchen",
        "gadget",
        "air conditioner",
        "summer",
        "wearable",
    ],
}

SOURCE_WEIGHTS = {
    "reuters": 5,
    "ap": 5,
    "associated press": 5,
    "bloomberg": 4,
    "cnbc": 4,
    "financial times": 4,
    "wall street journal": 4,
    "wsj": 4,
    "washington post": 3,
    "al jazeera": 3,
    "marketwatch": 3,
    "new york times": 3,
    "nytimes": 3,
    "bbc": 3,
    "guardian": 2,
    "politico": 2,
    "fx168": 2,
    "techcrunch": 3,
    "the verge": 2,
    "wired": 2,
}


def briefing_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = (now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ)
    today = now.date()
    if now.time() < time(13, 0):
        return (
            datetime.combine(today - timedelta(days=1), time(18, 0), CHINA_TZ),
            datetime.combine(today, time(9, 0) if now.time() >= time(9, 0) else time(8, 0), CHINA_TZ),
        )
    if now.time() < time(17, 0):
        return (
            datetime.combine(today, time(8, 0), CHINA_TZ),
            datetime.combine(today, time(12, 0), CHINA_TZ),
        )
    return (
        datetime.combine(today, time(8, 0), CHINA_TZ),
        datetime.combine(today, time(17, 0), CHINA_TZ),
    )


def google_news_rss_url(query: str, zh: bool = False) -> str:
    if zh:
        return (
            "https://news.google.com/rss/search?q="
            + quote_plus(query)
            + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )


def clean_title(title: str) -> str:
    title = unescape(title or "")
    title = re.sub(r"\s+", " ", title).strip()
    return title


def parse_rss(data: bytes, category: str) -> list[NewsItem]:
    root = ElementTree.fromstring(data)
    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = clean_title(node.findtext("title", ""))
        link = (node.findtext("link", "") or "").strip()
        source_node = node.find("source")
        source = clean_title(source_node.text if source_node is not None else "")
        if not source:
            host = urlparse(link).netloc.removeprefix("www.")
            source = title.rsplit(" - ", 1)[-1] if " - " in title else host or "RSS"
        published_text = (node.findtext("pubDate", "") or "").strip()
        try:
            published = parsedate_to_datetime(published_text).astimezone(CHINA_TZ)
        except (TypeError, ValueError, AttributeError):
            published = datetime.now(CHINA_TZ)
        if title:
            items.append(
                NewsItem(
                    title=title,
                    source=source,
                    link=link,
                    published=published,
                    category=category,
                )
            )
    return items


def fetch_rss(url: str, timeout: float = 8.0) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "VELA/1.0 (+cc-connect; overnight intelligence briefing)",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def collect_items(now: datetime | None = None) -> list[NewsItem]:
    start, end = briefing_window(now)
    collected: list[NewsItem] = []
    for category, queries in ZH_QUERY_GROUPS.items():
        for query in queries:
            try:
                collected.extend(parse_rss(fetch_rss(google_news_rss_url(query, zh=True)), category))
            except Exception:
                continue
    for category, queries in QUERY_GROUPS.items():
        for query in queries:
            try:
                collected.extend(parse_rss(fetch_rss(google_news_rss_url(query)), category))
            except Exception:
                continue
    for category, feeds in RSS_FEEDS.items():
        for feed in feeds:
            try:
                collected.extend(parse_rss(fetch_rss(feed), category))
            except Exception:
                continue
    deduped = dedupe_items(recategorize_items(collected))
    in_window = [item for item in deduped if start <= item.published <= end]
    if len(in_window) >= 8:
        return select_balanced(in_window, DEFAULT_MAX_ITEMS)
    return select_balanced(deduped, DEFAULT_MAX_ITEMS)


def dedupe_items(items: Iterable[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    result: list[NewsItem] = []
    for item in sorted(items, key=lambda n: n.published, reverse=True):
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", canonical_title(item.title).lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def select_balanced(items: list[NewsItem], max_items: int) -> list[NewsItem]:
    selected: list[NewsItem] = []
    ranked = sorted(items, key=lambda item: (item_score(item), item.published), reverse=True)
    remaining = [item for item in ranked if item_score(item) > 0]
    neutral = [
        item
        for item in ranked
        if item_score(item) == 0 and source_weight(item.source) >= 4
    ]
    for category, target in CATEGORY_TARGETS.items():
        picked = [item for item in remaining if item.category == category][:target]
        selected.extend(picked)
        picked_ids = {id(item) for item in picked}
        remaining = [item for item in remaining if id(item) not in picked_ids]
    if len(selected) < max_items:
        selected.extend(prioritized_fill(remaining, max_items - len(selected)))
    if len(selected) < max_items:
        selected_ids = {id(item) for item in selected}
        selected.extend(
            prioritized_fill(
                [item for item in neutral if id(item) not in selected_ids],
                max_items - len(selected),
            )
        )
    return selected[:max_items]


def prioritized_fill(items: list[NewsItem], limit: int) -> list[NewsItem]:
    picked: list[NewsItem] = []
    seen: set[int] = set()
    for category in FILL_ORDER:
        for item in items:
            if len(picked) >= limit:
                return picked
            if id(item) in seen or item.category != category:
                continue
            picked.append(item)
            seen.add(id(item))
    for item in items:
        if len(picked) >= limit:
            break
        if id(item) not in seen:
            picked.append(item)
            seen.add(id(item))
    return picked


def recategorize_items(items: Iterable[NewsItem]) -> list[NewsItem]:
    return [recategorize_item(item) for item in items]


def recategorize_item(item: NewsItem) -> NewsItem:
    text = f"{item.title} {item.source}".lower()
    if item.category != "markets" and category_keyword_score(text, "markets") >= 2:
        return item.__class__(
            title=item.title,
            source=item.source,
            link=item.link,
            published=item.published,
            category="markets",
        )
    if item.category != "tech" and category_keyword_score(text, "tech") >= 2:
        return item.__class__(
            title=item.title,
            source=item.source,
            link=item.link,
            published=item.published,
            category="tech",
        )
    return item


def item_score(item: NewsItem) -> int:
    text = f"{item.title} {item.source}".lower()
    source_score = source_weight(item.source)
    keyword_score = category_keyword_score(text, item.category)
    penalty = 0
    for keyword in NEGATIVE_KEYWORDS.get("all", []) + NEGATIVE_KEYWORDS.get(item.category, []):
        if contains_keyword(text, keyword):
            penalty -= 6
    if keyword_score <= 0:
        return penalty
    return keyword_score + source_score + penalty


def category_keyword_score(text: str, category: str) -> int:
    score = 0
    for keyword in CATEGORY_KEYWORDS.get(category, []):
        if contains_keyword(text, keyword):
            score += 2
    return score


def source_weight(source_text: str) -> int:
    source_text = source_text.lower()
    for source, weight in SOURCE_WEIGHTS.items():
        if source in source_text:
            return weight
    return 0


def contains_keyword(text: str, keyword: str) -> bool:
    if len(keyword) <= 3 and keyword.isalnum():
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def canonical_title(title: str) -> str:
    return re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip()


def format_briefing(
    items: list[NewsItem],
    start: datetime,
    end: datetime,
    translations: dict[str, str] | None = None,
) -> str:
    date_label = end.strftime("%Y-%m-%d")
    window = f"{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}（中国时间）"
    briefing_name = briefing_name_for_window(start, end)
    if not items:
        return (
            f"{briefing_name}｜{date_label}｜窗口：{window}\n"
            "实时源没有打开。我不拿空气当情报，也不把猜测包装成判断。请检查网络，或给我指定来源。"
        )

    lines = [
        f"{briefing_name}｜{date_label}｜窗口：{window}",
        "地图不干净，但轮廓够用。先看会改变今天判断的东西。",
        "",
    ]
    translations = translations if translations is not None else translate_titles(items)
    number = 1
    for category, label in CATEGORY_LABELS.items():
        grouped = [item for item in items if item.category == category]
        lines.append(label)
        if category == "markets":
            lines.append(
                "重点盯盘：美股（S&P 500 / Nasdaq / Dow / 美债 / 美元）、A股（上证 / 深成指 / 创业板 / 沪深300 / 人民币）、日本（Nikkei / TOPIX / 日元 / BOJ）、韩国（KOSPI / 三星 / SK海力士 / 韩元）。"
            )
        if not grouped:
            lines.append("暂无高置信条目。")
        for item in grouped:
            source = item.source.replace("\n", " ").strip() or "未标明来源"
            title = display_title(item, translations)
            lines.append(f"{number}. {title}。来源：{source}")
            number += 1
        lines.append("")

    lines.extend(
        [
            "VELA 判断",
            "- 主线：先看军政风险有没有向能源、航运、利率传导；没有传导，就是噪音，有传导，就是价格。",
            "- 市场：风险偏好可以反弹，但不要把反弹叫胜利，很多时候那只是空头换口气。",
            "- A股：先看人民币、政策预期和成交量。若外部风险降温、人民币企稳、量能跟上，修复可以延续；若只是题材轮动，别把换防当突破。",
            "- 美股：先看美债收益率、美元、油价和 AI 龙头宽度。若只有少数巨头托指数，中小盘和周期不跟，指数好看也只是装甲车开进窄巷。",
            "- 日本 / 韩国：日本看日元、BOJ 和出口链；韩国看 KOSPI、三星、SK海力士和韩元。半导体若不跟，亚洲风险偏好就是纸面热闹。",
            "- 科技：AI 线继续盯算力、芯片出口、监管和安全，不要被单个产品标题牵着走。",
            "- 下一步：12-24 小时内盯官方声明、油价、美元、长债和头部科技公司的资本开支信号。",
        ]
    )
    return "\n".join(lines).strip()


def briefing_name_for_window(start: datetime, end: datetime) -> str:
    if start.time() == time(18, 0):
        return "夜间简报"
    if end.time() == time(12, 0):
        return "午间简报"
    if end.time() == time(16, 0):
        return "日内简报"
    return "盘中简报"


def display_title(item: NewsItem, translations: dict[str, str]) -> str:
    title = canonical_title(item.title).replace("\n", " ").strip()
    translated = translations.get(title) or translations.get(item.title) or ""
    if translated:
        title = translated
    title = re.sub(r"\s+", " ", title).strip()
    title = title.rstrip("。.;；")
    return polish_chinese_title(title)


def polish_chinese_title(title: str) -> str:
    replacements = {
        "油价下跌因美伊和平协议的希望而下跌": "美伊和平协议预期升温，油价回落",
        "美伊和平协议的希望": "美伊和平协议预期",
        "随着协议乐观，油价下跌": "协议预期升温，油价回落",
        "可靠的伊朗协议": "伊朗协议框架",
        "相当稳固": "框架较稳",
        "您的问题已得到解答": "要点梳理",
    }
    for old, new in replacements.items():
        title = title.replace(old, new)
    title = title.replace("因美伊和平协议预期而下跌", "受美伊协议预期影响回落")
    title = title.replace("和平协议的希望", "和平协议预期")
    return title


def translate_titles(items: list[NewsItem]) -> dict[str, str]:
    titles = []
    for item in items:
        title = canonical_title(item.title)
        if title and not mostly_chinese(title):
            titles.append(title)
    titles = list(dict.fromkeys(titles))
    if not titles:
        return {}
    translated = translate_batch_to_chinese(titles)
    return {src: dst for src, dst in zip(titles, translated) if dst and dst != src}


def mostly_chinese(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha() or "\u4e00" <= ch <= "\u9fff"]
    if not letters:
        return False
    chinese = [ch for ch in letters if "\u4e00" <= ch <= "\u9fff"]
    return len(chinese) / len(letters) >= 0.45


def translate_batch_to_chinese(texts: list[str]) -> list[str]:
    if not texts:
        return []
    joined = "\n".join(texts)
    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=auto&tl=zh-CN&dt=t&q="
        + quote_plus(joined)
    )
    try:
        data = fetch_rss(url, timeout=6.0)
        payload = json.loads(data.decode("utf-8"))
        translated = "".join(part[0] for part in payload[0] if part and part[0])
        lines = [line.strip() for line in translated.splitlines() if line.strip()]
        if len(lines) == len(texts):
            return lines
    except Exception:
        pass
    return texts


def send_via_cc_connect(
    message: str,
    project: str,
    cc_connect: str = CC_CONNECT_EXE,
    session: str = "",
) -> int:
    cmd = [cc_connect, "send", "--project", project]
    if session:
        cmd.extend(["--session", session])
    cmd.append("--stdin")
    completed = subprocess.run(
        cmd,
        input=message,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        return completed.returncode
    return 0


def build_briefing(now: datetime | None = None) -> str:
    start, end = briefing_window(now)
    return format_briefing(collect_items(now), start, end)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--project", default="VELA")
    parser.add_argument("--session", default="")
    parser.add_argument("--cc-connect", default=CC_CONNECT_EXE)
    args = parser.parse_args(argv)

    if args.send and args.detach and not args.worker:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [
                sys.executable,
                "-X",
                "utf8",
                __file__,
                "--send",
                "--worker",
                "--project",
                args.project,
                "--session",
                args.session,
                "--cc-connect",
                args.cc_connect,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return 0

    message = build_briefing()
    if args.send:
        return send_via_cc_connect(message, args.project, args.cc_connect, args.session)
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
