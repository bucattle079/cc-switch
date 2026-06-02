from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from vela_market_briefing import (
    build_cached_market_brief,
    build_market_brief,
    fetch_live_market_snapshot,
    format_freshness_status,
    format_live_market_frontstage,
    format_market_brief,
    format_market_frontstage_summary,
    format_status_boundary,
    market_freshness_status,
)
from vela_product_layers import (
    RouteDecision,
    guard_wechat_output,
    interpret_user_need,
    is_current_information_request,
    record_interaction,
    record_reply_quality,
    record_session_note,
    run_layered_response,
)
from vela_reply_engine import FallbackReplyAdapter, reply_engine_status


ROOT = Path(__file__).resolve().parents[1]
CODEX_CONSOLE = ROOT / "tools" / "clawbot_codex_console.py"
PERSONALITY_SCRIPT = ROOT / "tools" / "vela_personality.py"
DAILY_BRIEFING_SCRIPT = ROOT / "tools" / "vela_daily_briefing.py"
SEND_ONCE_DIR = ROOT / "VELA" / "send-once"
MARKET_REFRESH_DIR = ROOT / "VELA" / "market-refresh"
MARKET_REFRESH_LOCK_TTL_SECONDS = 20 * 60
LOCAL_TOOL_TIMEOUT_SECONDS = 45
FEEDBACK_DEDUP_WINDOW_SECONDS = 120


@dataclass(frozen=True)
class Intent:
    name: str
    confidence: float
    focus_tags: list[str]
    codex_allowed: bool = False
    market_allowed: bool = False


@dataclass(frozen=True)
class MarketRefreshJob:
    started: bool
    in_progress: bool
    pid: int | None = None
    reason: str = ""


GREETING_SET = {"你好vela", "你好 vela", "你好，vela", "早安vela", "早上好vela"}
MARKET_KEYWORDS = [
    "a股",
    "a 股",
    "上证",
    "沪深300",
    "美股",
    "nasdaq",
    "s&p",
    "sp500",
    "韩国",
    "kospi",
    "日本",
    "nikkei",
    "美元",
    "美债",
    "人民币",
    "油价",
    "黄金",
    "vix",
    "市场",
    "加仓",
    "减仓",
    "仓位",
    "能不能加仓",
    "满仓",
    "重仓",
    "抄底",
    "冲进去",
    "先等",
    "看盘",
    "早盘",
    "午盘",
    "收盘",
    "盘前",
    "盘后",
    "风险",
    "半导体",
    "芯片",
    "资讯",
    "新闻",
    "来源",
    "简报",
]
EXPLICIT_MARKET_DECISION_KEYWORDS = [
    "a股",
    "a 股",
    "上证",
    "沪深300",
    "美股",
    "nasdaq",
    "s&p",
    "sp500",
    "韩国",
    "kospi",
    "日本",
    "nikkei",
    "美元",
    "美债",
    "人民币",
    "油价",
    "黄金",
    "vix",
    "加仓",
    "减仓",
    "仓位",
    "满仓",
    "重仓",
    "抄底",
    "冲进去",
    "看盘",
    "早盘",
    "午盘",
    "收盘",
    "盘前",
    "盘后",
    "半导体",
    "芯片",
]
FRESHNESS_KEYWORDS = [
    "实时",
    "数据新",
    "新吗",
    "什么时候",
    "更新时间",
    "缓存",
    "新鲜度",
    "current",
    "real-time",
    "realtime",
    "fresh",
]
MARKET_SUMMARY_ACTION_KEYWORDS = [
    "梳理",
    "整理",
    "给我",
    "简报",
    "资讯",
    "新闻",
    "怎么看",
    "如何",
]
REFRESH_KEYWORDS = [
    "刷新",
    "重新检索",
    "重新搜索",
    "更新最新",
    "拉取最新",
    "开启检索",
    "开始检索",
    "联网检索",
    "外部检索",
    "实时资讯",
    "实时的资讯",
    "需要实时",
    "要实时",
]
CURRENT_MARKET_TIME_KEYWORDS = ["今天", "现在", "目前", "当前", "当下", "此刻", "最新", "实时", "盘中", "早盘", "午盘", "收盘"]
CURRENT_MARKET_SURFACE_KEYWORDS = [
    "a股",
    "a 股",
    "上证",
    "沪深300",
    "深成指",
    "创业板",
    "美股",
    "nasdaq",
    "s&p",
    "sp500",
    "韩国",
    "kospi",
    "日本",
    "nikkei",
    "全球",
    "世界",
    "外盘",
    "市场",
    "盘面",
]
CURRENT_MARKET_HARD_SURFACE_KEYWORDS = [
    "a股",
    "a 股",
    "上证",
    "沪深300",
    "深成指",
    "创业板",
    "美股",
    "nasdaq",
    "s&p",
    "sp500",
    "kospi",
    "nikkei",
    "全球市场",
    "世界市场",
    "外盘",
    "市场",
    "盘面",
]
WORLD_KEYWORDS = ["世界", "全球", "军政", "地缘", "外交", "战争", "制裁", "航运", "能源安全", "世界简报"]
CURRENT_INFO_ACTION_KEYWORDS = [
    "资讯",
    "新闻",
    "消息",
    "新消息",
    "动态",
    "进展",
    "更新",
    "公告",
    "政策",
    "发生",
    "发生了什么",
    "有什么新",
    "有什么新闻",
    "帮我查",
    "帮我搜",
    "查",
    "查一下",
    "搜一下",
    "搜",
    "查询",
    "检索",
    "搜索",
]
CURRENT_WORLD_EVENT_KEYWORDS = [
    "地震",
    "台风",
    "海啸",
    "战争",
    "冲突",
    "制裁",
    "外交",
    "军政",
    "地缘",
    "航运",
    "能源安全",
]
CODEX_KEYWORDS = [
    "codex",
    "代码",
    "提交",
    "diff",
    "git",
    "任务状态",
    "任务进展",
    "项目进展",
    "项目推进状态",
    "推进状态",
    "执行到哪里",
    "开发任务",
    "电脑控制",
]
PROJECT_KEYWORDS = ["augsun", "rollqiia", "项目", "广告中心", "intelligence center", "规划", "功能如何"]
DEEP_KEYWORDS = ["深入分析", "深度分析", "地狱验尸", "验尸", "架构判断", "架构", "推演", "复盘", "根因", "策略验尸"]
STYLE_FEEDBACK_KEYWORDS = [
    "新闻列表",
    "太模板",
    "模板",
    "太冷",
    "太呆",
    "太慢",
    "太长",
    "太工程化",
    "太机械",
    "机械",
    "机械道歉",
    "客服话术",
    "机器人",
    "不像vela",
    "不像 vela",
    "不够直接",
    "真伙伴",
    "像客服",
    "说人话",
    "别解释身份",
    "更像真人",
    "像真人",
    "不够像真人",
    "更智能",
    "智能的伙伴",
    "理解一下我的意思",
    "不要拖",
    "继续推进",
    "不够锋利",
    "语气",
    "风格",
    "人格",
    "你没懂我",
    "没懂我",
    "没听懂",
    "没听明白",
    "没抓到",
    "不是这个意思",
    "不是我要的",
    "理解错",
    "重新判断",
    "偏了",
]
RELATIONSHIP_REPAIR_KEYWORDS = ["你没懂我", "没懂我", "没听懂", "没听明白", "没抓到", "不是这个意思", "不是我要的", "理解错", "重新判断", "偏了"]
WEATHER_KEYWORDS = [
    "天气",
    "气温",
    "降温",
    "下雨",
    "下雪",
    "冷吗",
    "热吗",
    "weather",
    "temperature",
]
WEATHER_TIME_WORDS = ["今天", "明天", "后天", "今晚", "早上", "中午", "下午", "晚上", "现在", "本周", "周末"]
WEATHER_QUESTION_WORDS = [
    "天气",
    "气温",
    "冷吗",
    "热吗",
    "冷不冷",
    "热不热",
    "会下雨吗",
    "会不会下雨",
    "下雨吗",
    "下雪吗",
    "不准也给我出门风险",
    "能不能出门",
    "出门风险",
    "出门要不要加外套",
    "要不要加外套",
    "要不要穿外套",
    "要不要带伞",
    "要见客户",
    "出门",
    "风险",
]
DAILY_INFO_KEYWORDS = ["解释", "整理", "总结", "帮我查", "帮我搜", "这是什么意思", "什么意思", "逻辑", "分析一下", "协助我分析", "选择", "比较好吗", "翻译", "普通检索"]
MEMORY_KEYWORDS = ["记住", "记忆", "长期", "以后", "默认", "偏好", "别忘", "学习一下", *STYLE_FEEDBACK_KEYWORDS]
MEMORY_PRIORITY_KEYWORDS = ["记住", "记忆", "长期", "以后", "默认", "偏好", "别忘", "学习一下", "沉淀"]
PERSONA_TOOL_PREFIXES = {"persona", "personality", "vela-personality"}
PERSONA_TOOL_ALIASES = {
    "人格": ["status"],
    "status": ["status"],
    "成长": ["growth"],
    "growth": ["growth"],
    "学习": ["learn"],
    "learn": ["learn"],
    "画像": ["profile"],
    "profile": ["profile"],
    "对白": ["samples"],
    "samples": ["samples"],
    "语气": ["voice"],
    "voice": ["voice"],
    "tone": ["voice"],
    "压测": ["probe"],
    "probe": ["probe"],
    "真人压测": ["litmus"],
    "litmus": ["litmus"],
    "素材": ["material"],
    "material": ["material"],
    "质检": ["audit"],
    "audit": ["audit"],
    "最近质检": ["audit-last"],
    "audit-last": ["audit-last"],
}
DAILY_BRIEFING_COMMANDS = {"daily-briefing", "daily_briefing", "vela-daily-briefing"}


def ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def command_key(token: str) -> str:
    return normalize(token).lstrip("/")


def first_command_token(text: str) -> str:
    parts = str(text or "").strip().split()
    return parts[0] if parts else ""


def is_persona_tool_request(text: str) -> bool:
    key = command_key(first_command_token(text))
    return key in PERSONA_TOOL_PREFIXES or key in PERSONA_TOOL_ALIASES


def is_daily_briefing_request(text: str) -> bool:
    return command_key(first_command_token(text)) in DAILY_BRIEFING_COMMANDS


def persona_tool_args(text: str) -> list[str]:
    parts = str(text or "").strip().split()
    if not parts:
        return ["status"]
    key = command_key(parts[0])
    if key in PERSONA_TOOL_PREFIXES:
        mode = parts[1] if len(parts) > 1 else "status"
        rest = parts[2:] if len(parts) > 1 else []
    else:
        mode = parts[0]
        rest = parts[1:]
    mapped = PERSONA_TOOL_ALIASES.get(command_key(mode), [mode])
    return [*mapped, *rest]


def classify_intent(text: str) -> Intent:
    raw = (text or "").strip()
    norm = normalize(raw)
    if not norm:
        return Intent("normal_chat", 0.9, [])
    if is_persona_tool_request(raw):
        return Intent("persona_tool", 0.95, ["persona"])
    if is_daily_briefing_request(raw):
        return Intent("daily_briefing", 0.95, ["daily_briefing"], market_allowed=True)
    if norm in {"/codex", "/vela codex"}:
        return Intent("codex_task", 1.0, ["codex"], codex_allowed=True)
    if raw.startswith("/"):
        return Intent("codex_task", 0.8, ["slash_command"], codex_allowed=True)
    if norm == "vela" or norm in GREETING_SET or norm in {"你好", "在吗", "在么", "hello", "hi"}:
        return Intent("normal_chat", 1.0, [])
    if is_weather_query(raw):
        return Intent("weather_query", 0.9, weather_focus_tags(raw))
    if is_market_refresh_request(norm):
        return Intent("market_refresh", 0.94, market_focus_tags(norm), market_allowed=True)
    if is_freshness_question(norm) and not is_market_summary_request(norm):
        return Intent("freshness_status", 0.95, ["freshness"])
    if contains_any(norm, DEEP_KEYWORDS):
        return Intent("deep_analysis", 0.82, deep_focus_tags(norm))
    if contains_any(norm, MEMORY_KEYWORDS) and contains_any(norm, MEMORY_PRIORITY_KEYWORDS):
        return Intent("memory_related", 0.88, memory_focus_tags(norm))
    if contains_any(norm, CODEX_KEYWORDS):
        return Intent("codex_task", 0.86, ["codex"], codex_allowed=True)
    if contains_any(norm, PROJECT_KEYWORDS) and not is_explicit_market_judgment_request(norm):
        return Intent("project_assistant", 0.78, ["project"])
    if is_current_world_info_request(norm):
        return Intent("world_brief", 0.84, ["geopolitics", "global"])
    if is_current_general_info_request(norm):
        return Intent("daily_info", 0.82, ["daily_info", "current_info"])
    if is_explicit_market_judgment_request(norm):
        tags = market_focus_tags(norm)
        return Intent("market_brief", 0.9, tags, market_allowed=True)
    if contains_any(norm, STYLE_FEEDBACK_KEYWORDS):
        tags = ["memory", "style_feedback"]
        if contains_any(norm, RELATIONSHIP_REPAIR_KEYWORDS):
            tags.append("relationship_repair")
        return Intent("style_feedback", 0.9, tags)
    if contains_any(norm, MEMORY_KEYWORDS):
        return Intent("memory_related", 0.88, memory_focus_tags(norm))
    if contains_any(norm, MARKET_KEYWORDS):
        tags = market_focus_tags(norm)
        return Intent("market_brief", 0.9, tags, market_allowed=True)
    if contains_any(norm, WORLD_KEYWORDS):
        return Intent("world_brief", 0.82, ["geopolitics", "global"])
    if contains_any(norm, PROJECT_KEYWORDS):
        return Intent("project_assistant", 0.78, ["project"])
    if is_daily_info_request(norm):
        return Intent("daily_info", 0.74, ["daily_info"])
    return Intent("normal_chat", 0.7, [])


def contains_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def is_freshness_question(text: str) -> bool:
    return contains_any(text, FRESHNESS_KEYWORDS)


def is_market_summary_request(text: str) -> bool:
    if not contains_any(text, MARKET_SUMMARY_ACTION_KEYWORDS):
        return False
    if "实时吗" in text or ("是实时" in text and "不是实时" not in text):
        return False
    return contains_any(text, MARKET_KEYWORDS) or contains_any(text, ["资讯", "新闻", "市场"])


def is_explicit_market_judgment_request(text: str) -> bool:
    if contains_any(text, EXPLICIT_MARKET_DECISION_KEYWORDS):
        return True
    if "市场" in text and contains_any(text, ["怎么看", "如何", "能不能", "要不要", "先等", "冲", "风险"]):
        return True
    return False


def is_market_refresh_request(text: str) -> bool:
    if not contains_any(text, MARKET_KEYWORDS + ["资讯", "新闻", "市场"]):
        return False
    if "实时吗" in text or "是实时" in text:
        return False
    return contains_any(text, REFRESH_KEYWORDS)


def is_current_market_query(text: str) -> bool:
    norm = normalize(text)
    if is_expanded_market_query(norm):
        return False
    return contains_any(norm, CURRENT_MARKET_TIME_KEYWORDS) and contains_any(norm, CURRENT_MARKET_SURFACE_KEYWORDS)


def is_current_world_info_request(text: str) -> bool:
    norm = normalize(text)
    if "现在" not in norm:
        return False
    if contains_any(norm, CURRENT_MARKET_HARD_SURFACE_KEYWORDS):
        return False
    return contains_any(norm, CURRENT_INFO_ACTION_KEYWORDS) and contains_any(norm, CURRENT_WORLD_EVENT_KEYWORDS)


def is_current_general_info_request(text: str) -> bool:
    norm = normalize(text)
    if "现在" not in norm:
        return False
    if contains_any(norm, CURRENT_MARKET_HARD_SURFACE_KEYWORDS):
        return False
    if is_weather_query(norm):
        return False
    return contains_any(norm, CURRENT_INFO_ACTION_KEYWORDS)


def is_weather_query(text: str) -> bool:
    return contains_any(normalize(text), WEATHER_KEYWORDS)


def is_daily_info_request(text: str) -> bool:
    return contains_any(text, DAILY_INFO_KEYWORDS)


def is_fast_greeting(text: str) -> bool:
    norm = normalize(text)
    return norm == "vela" or norm in GREETING_SET or norm in {"你好", "你好 vela", "在吗", "在么", "hello", "hi"}


def is_plain_ping(text: str) -> bool:
    norm = normalize(text)
    return norm == "vela" or norm in {"你好", "在吗", "在么", "hello", "hi"}


def should_force_fallback_for_greeting(text: str) -> bool:
    return reply_engine_status().get("adapter") == "command"


def memory_focus_tags(text: str) -> list[str]:
    tags = ["memory"]
    if contains_any(text, STYLE_FEEDBACK_KEYWORDS):
        tags.append("style_feedback")
    if contains_any(text, ["a股", "美股", "韩国", "日本", "市场"]):
        tags.append("market_focus")
    if contains_any(text, ["augsun", "rollqiia", "项目"]):
        tags.append("project_memory")
    return tags


def deep_focus_tags(text: str) -> list[str]:
    tags = ["analysis"]
    if contains_any(text, ["架构", "验尸", "根因"]):
        tags.append("architecture")
    if contains_any(text, ["风险", "策略"]):
        tags.append("risk")
    return tags


def weather_focus_tags(text: str) -> list[str]:
    tags = ["weather"]
    norm = normalize(text)
    for token in WEATHER_TIME_WORDS:
        if token in norm:
            tags.append(token)
            break
    return tags


def market_focus_tags(text: str) -> list[str]:
    tags: list[str] = []
    if contains_any(text, ["a股", "a 股", "上证", "沪深300", "人民币"]):
        tags.append("china_a")
    if contains_any(text, ["美股", "nasdaq", "s&p", "sp500", "vix"]):
        tags.append("us_equities")
    if contains_any(text, ["韩国", "kospi", "samsung", "hynix"]):
        tags.append("korea")
    if contains_any(text, ["日本", "nikkei", "topix", "日元"]):
        tags.append("japan")
    if contains_any(text, ["美元"]):
        tags.append("usd")
    if contains_any(text, ["美债", "10y", "treasury"]):
        tags.append("us_10y")
    if contains_any(text, ["半导体", "芯片", "ai", "nvidia"]):
        tags.append("semiconductors")
    if contains_any(text, ["油价", "原油", "wti"]):
        tags.append("oil")
    if not tags:
        tags = ["china_a", "us_equities", "korea", "japan", "usd", "us_10y"]
    if "us_equities" in tags or "korea" in tags:
        for extra in ["usd", "us_10y", "semiconductors"]:
            if extra not in tags:
                tags.append(extra)
    return tags


def route_decision(text: str) -> RouteDecision:
    intent = classify_intent(text)
    markets = priority_markets(intent.focus_tags)
    return RouteDecision(
        intent=intent.name,
        needs_retrieval=intent.name in {"market_refresh"},
        needs_codex=intent.codex_allowed,
        needs_deep_reasoning=intent.name in {"market_brief", "deep_analysis", "project_assistant"},
        cache_allowed=intent.name in {"market_brief", "world_brief", "freshness_status", "market_refresh", "daily_briefing"},
        priority_markets=markets,
    )


def priority_markets(tags: list[str]) -> list[str]:
    mapping = {
        "china_a": "A股",
        "us_equities": "美股",
        "korea": "韩国",
        "japan": "日本",
        "usd": "美元",
        "us_10y": "美债",
        "semiconductors": "AI/半导体",
        "oil": "油价",
        "geopolitics": "地缘/军政",
        "global": "全球",
    }
    return [mapping[tag] for tag in tags if tag in mapping]


def render_freshness_reply(text: str) -> str:
    status = market_freshness_status(text)
    return guard_wechat_output(format_freshness_status(status))


def render_cached_market_reply(text: str) -> str:
    status = market_freshness_status(text)
    if is_market_impulse_query(text):
        lines = [
            "不是实时直播。先刹车：你问的是仓位冲动，不是普通资讯请求。",
            f"更新时间：{status.last_updated}",
            format_status_boundary(status),
            "判断：没有新增实时确认前，不满仓；先把仓位降成可撤退的试探单。",
            "观察：成交量、美元/美债、AI/半导体链没有共振前，别把上头包装成战略。",
            "下一步：写下最大亏损线和撤退条件；写不出来，就别冲。",
        ]
        return guard_wechat_output("\n".join(lines))
    if is_current_market_query(text):
        live = fetch_live_market_snapshot(text)
        brief = build_cached_market_brief(text)
        return guard_wechat_output(format_live_market_frontstage(live, fallback_brief=brief, fallback_status=status))
    brief = build_cached_market_brief(text)
    if brief is None:
        lines = [
            f"不是实时直播；实时源：未接入；最近缓存：{status.last_updated}。",
            "判断：当前没有可用市场缓存，不生成新的盘面结论。",
            "下一步：先刷新外部源/API；没有数据就别硬猜，市场不会因为我们嘴硬就变清楚。",
        ]
        return guard_wechat_output("\n".join(lines))
    if is_expanded_market_query(text):
        status_text = format_freshness_status(status)
        body = format_market_brief(brief, detail=True)
        return guard_wechat_output(f"{status_text}\n\n{body}")
    else:
        prefix = f"不是实时直播；实时源：未接入；最近缓存：{status.last_updated}。"
        body = format_market_frontstage_summary(brief)
    return guard_wechat_output(f"{prefix}\n\n{body}")


def render_market_refresh_reply(text: str) -> str:
    status = market_freshness_status(text)
    job = schedule_market_refresh(text)
    if job.started:
        refresh_line = "刷新状态：后台刷新已启动；前台先返回状态，不让你干等。"
    elif job.in_progress:
        refresh_line = "刷新状态：后台刷新已在进行；前台先返回状态，不让你干等。"
    else:
        refresh_line = "刷新状态：后台刷新暂未启动；前台先返回状态，不把缓存伪装成实时情报。"
    lines = [
        "已识别为实时资讯请求。我不拿缓存冒充实时，也不把旧报告包装成刚发生。",
        f"最近缓存：{status.last_updated}",
        format_status_boundary(status),
        refresh_line,
        "",
        "失效控制：如果外部实时源/API 未接通或刷新超过前台预算，我只返回状态，不把缓存伪装成实时情报。",
        "后台刷新完成后，会写入市场缓存；下一次问“今天的资讯”会带更新时间给你。",
    ]
    return guard_wechat_output("\n".join(lines))


def weather_location_from_text(text: str) -> str:
    location = str(text or "").strip()
    for token in [*WEATHER_TIME_WORDS, *WEATHER_QUESTION_WORDS, "?", "？", "。", "，", ","]:
        location = location.replace(token, "")
    location = " ".join(location.split()).strip()
    return location or "这个位置"


def render_weather_reply(text: str) -> str:
    location = weather_location_from_text(text)
    reply = (
        f"K，{location}这条按出行风险处理，不编实时天气。\n"
        "边界：实时源：未接入；缓存摘要：不可用；可用性：天气实时数据不可用。\n"
        "我不编实时温度、降雨概率或精确预报。\n"
        "行动判断：带伞，看温差，给行程留余量；要精确预报请看本机天气源。"
    )
    return guard_wechat_output(reply)


def render_local_tool_reply(
    *,
    script: Path,
    args: list[str],
    text: str,
    intent: str,
    conversation_type: str,
    used_retrieval: bool,
    quality_flags: list[str],
    fallback: str,
) -> str:
    issues: list[str] = []
    try:
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(script), *args],
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=LOCAL_TOOL_TIMEOUT_SECONDS,
        )
        raw = (completed.stdout or "").strip()
        if completed.returncode != 0:
            issues.append(f"local_tool_exit:{completed.returncode}")
    except subprocess.TimeoutExpired:
        raw = ""
        issues.append("local_tool_timeout")
    except Exception as exc:
        raw = ""
        issues.append(f"local_tool_error:{type(exc).__name__}")

    reply = guard_wechat_output(raw or fallback)
    need_interpretation = interpret_user_need(text, intent)
    record_reply_quality(
        conversation_type=conversation_type,
        user_goal=text,
        response_text=reply,
        used_cache=False,
        used_retrieval=used_retrieval,
        used_codex=False,
        quality_flags=[*quality_flags, "guarded_output"],
        issues=issues,
        intent=intent,
        need_interpretation=need_interpretation,
    )
    record_interaction(
        message=text,
        intent=intent,
        response_text=reply,
        used_codex=False,
        used_retrieval=used_retrieval,
        need_interpretation=need_interpretation,
    )
    record_session_note(text, intent, reply)
    return reply


def render_persona_tool_reply(text: str) -> str:
    return render_local_tool_reply(
        script=PERSONALITY_SCRIPT,
        args=persona_tool_args(text),
        text=text,
        intent="persona_tool",
        conversation_type="persona_tool",
        used_retrieval=False,
        quality_flags=["local_tool_lane", "persona_tool"],
        fallback="这条人格校准工具暂时没吐出内容。我先收住，不把空回包发给你。",
    )


def render_daily_briefing_reply(text: str) -> str:
    return render_local_tool_reply(
        script=DAILY_BRIEFING_SCRIPT,
        args=[],
        text=text,
        intent="daily_briefing",
        conversation_type="daily_briefing",
        used_retrieval=True,
        quality_flags=["local_tool_lane", "daily_briefing"],
        fallback="这条市场简报工具暂时没吐出内容。我不拿旧话冒充新情报，稍后再刷。",
    )


def schedule_market_refresh(text: str, *, state_dir: Path | None = None) -> MarketRefreshJob:
    state_dir = state_dir or MARKET_REFRESH_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "refresh.lock"
    now = time.time()
    if lock_path.exists():
        age = now - lock_path.stat().st_mtime
        if age <= MARKET_REFRESH_LOCK_TTL_SECONDS:
            return MarketRefreshJob(started=False, in_progress=True, reason="existing_refresh")
        try:
            lock_path.unlink()
        except OSError:
            return MarketRefreshJob(started=False, in_progress=True, reason="stale_lock_unlink_failed")

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message_preview": " ".join(str(text or "").split())[:160],
    }
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return MarketRefreshJob(started=False, in_progress=True, reason="lock_race")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))

    stdout_path = state_dir / "refresh.out.log"
    stderr_path = state_dir / "refresh.err.log"
    stdout_handle = stdout_path.open("a", encoding="utf-8", newline="\n")
    stderr_handle = stderr_path.open("a", encoding="utf-8", newline="\n")
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-X",
                "utf8",
                str(ROOT / "tools" / "vela_market_briefing.py"),
                text,
                "--refresh",
                "--lock-file",
                str(lock_path),
            ],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        try:
            lock_path.unlink()
        except OSError:
            pass
        return MarketRefreshJob(started=False, in_progress=False, reason=type(exc).__name__)
    finally:
        stdout_handle.close()
        stderr_handle.close()
    return MarketRefreshJob(started=True, in_progress=False, pid=getattr(process, "pid", None), reason="started")


def reply_for(text: str) -> str:
    intent = classify_intent(text)
    if intent.name == "persona_tool":
        supporting_context = render_persona_tool_reply(text)
        return run_layered_response(text, intent=intent.name, supporting_context=supporting_context).text
    if intent.name == "daily_briefing":
        supporting_context = render_daily_briefing_reply(text)
        return run_layered_response(text, intent=intent.name, supporting_context=supporting_context).text
    if intent.name == "freshness_status":
        supporting_context = render_freshness_reply(text)
        return run_layered_response(
            text,
            intent=intent.name,
            supporting_context=supporting_context,
            reply_adapter=FallbackReplyAdapter(),
        ).text
    if intent.name == "market_refresh":
        supporting_context = render_market_refresh_reply(text)
        return run_layered_response(
            text,
            intent=intent.name,
            supporting_context=supporting_context,
            reply_adapter=FallbackReplyAdapter(),
        ).text
    if intent.name == "market_brief":
        supporting_context = render_cached_market_reply(text)
        reply_adapter = None if is_current_information_request(text, intent.name) else FallbackReplyAdapter()
        return run_layered_response(
            text,
            intent=intent.name,
            supporting_context=supporting_context,
            reply_adapter=reply_adapter,
        ).text
    if intent.name == "weather_query":
        supporting_context = render_weather_reply(text)
        reply_adapter = None if is_current_information_request(text, intent.name) else FallbackReplyAdapter()
        return run_layered_response(
            text,
            intent=intent.name,
            supporting_context=supporting_context,
            reply_adapter=reply_adapter,
        ).text
    if intent.name == "style_feedback":
        return run_layered_response(
            text,
            intent=intent.name,
            reply_adapter=FallbackReplyAdapter(),
        ).text
    if intent.name == "codex_task":
        return guard_wechat_output(render_codex_bridge(text))
    if intent.name == "normal_chat" and is_fast_greeting(text) and should_force_fallback_for_greeting(text):
        return run_layered_response(text, intent=intent.name, reply_adapter=FallbackReplyAdapter()).text
    return run_layered_response(text, intent=intent.name).text


def is_expanded_market_query(text: str) -> bool:
    norm = normalize(text)
    return any(token in norm for token in ("展开", "详细", "全部", "来源", "新闻来源"))


def is_market_impulse_query(text: str) -> bool:
    norm = normalize(text)
    return any(
        token in norm
        for token in (
            "上头",
            "满仓",
            "重仓",
            "梭哈",
            "all in",
            "all-in",
            "直接冲",
            "冲进去",
            "冲进",
        )
    )


def normalized_request_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def duplicate_ttl_seconds(intent: str) -> int:
    if intent == "market_brief":
        return 300
    if intent == "market_refresh":
        return 60
    if intent == "freshness_status":
        return 6
    if intent == "codex_task":
        return 60
    return 12


def recent_feedback_marker(state_dir: Path, *, max_age_seconds: int = FEEDBACK_DEDUP_WINDOW_SECONDS) -> str:
    path = state_dir / "last-feedback-claim.json"
    if not path.exists():
        return ""
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return ""
    if age > max_age_seconds:
        return ""
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        try:
            return f"mtime:{int(path.stat().st_mtime)}"
        except OSError:
            return ""
    marker = str(row.get("request_key") or "").strip()
    return marker or f"mtime:{int(path.stat().st_mtime)}"


def dedupe_context_marker(intent: str, state_dir: Path) -> str:
    parts: list[str] = []
    message_id = str(os.environ.get("CC_MESSAGE_ID") or "").strip()
    if message_id:
        parts.append(f"msg:{message_id}")
    if intent != "style_feedback":
        marker = recent_feedback_marker(state_dir)
        if marker:
            parts.append(f"after_feedback:{marker}")
    return "|".join(parts)


def request_key(message: str, intent: str, *, context_marker: str = "") -> str:
    payload = f"{intent}|{normalized_request_text(message)}|{context_marker}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def log_duplicate_request(
    *,
    message: str,
    intent: str,
    key: str,
    state_dir: Path,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"duplicate-requests-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
    row = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "intent": intent,
        "request_key": key,
        "message_preview": " ".join(str(message or "").split())[:160],
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def response_key(response: str, intent: str, *, context_marker: str = "") -> str:
    payload = f"{intent}|{normalized_request_text(response)}|{context_marker}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def write_claim_marker(
    *,
    state_dir: Path,
    message: str,
    intent: str,
    key: str,
    context_marker: str,
) -> None:
    row = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "intent": intent,
        "request_key": key,
        "context_marker": context_marker,
        "message_preview": " ".join(str(message or "").split())[:160],
    }
    for name in ("last-claim.json", "last-feedback-claim.json" if intent == "style_feedback" else ""):
        if not name:
            continue
        try:
            (state_dir / name).write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def log_duplicate_response(
    *,
    response: str,
    intent: str,
    key: str,
    state_dir: Path,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"duplicate-responses-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
    row = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "intent": intent,
        "response_key": key,
        "response_preview": " ".join(str(response or "").split())[:160],
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def claim_response_once(
    response: str,
    intent: str,
    *,
    state_dir: Path | None = None,
    ttl_seconds: int = 5,
) -> bool:
    state_dir = state_dir or SEND_ONCE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    context_marker = dedupe_context_marker(intent, state_dir)
    key = response_key(response, intent, context_marker=context_marker)
    path = state_dir / f"{key}.response"
    now = time.time()
    if path.exists():
        age = now - path.stat().st_mtime
        if age <= ttl_seconds:
            log_duplicate_response(response=response, intent=intent, key=key, state_dir=state_dir)
            return False
        try:
            path.unlink()
        except OSError:
            pass
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        log_duplicate_response(response=response, intent=intent, key=key, state_dir=state_dir)
        return False
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "intent": intent,
                    "response_key": key,
                    "response_preview": " ".join(str(response or "").split())[:160],
                },
                ensure_ascii=False,
            )
        )
    return True


def claim_request_once(
    message: str,
    intent: str,
    *,
    state_dir: Path | None = None,
    ttl_seconds: int | None = None,
) -> bool:
    state_dir = state_dir or SEND_ONCE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    ttl = ttl_seconds if ttl_seconds is not None else duplicate_ttl_seconds(intent)
    context_marker = dedupe_context_marker(intent, state_dir)
    key = request_key(message, intent, context_marker=context_marker)
    path = state_dir / f"{key}.claim"
    now = time.time()
    if path.exists():
        age = now - path.stat().st_mtime
        if age <= ttl:
            log_duplicate_request(message=message, intent=intent, key=key, state_dir=state_dir)
            return False
        try:
            path.unlink()
        except OSError:
            pass
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        log_duplicate_request(message=message, intent=intent, key=key, state_dir=state_dir)
        return False
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "intent": intent,
                    "request_key": key,
                    "context_marker": context_marker,
                    "message_preview": " ".join(str(message or "").split())[:160],
                },
                ensure_ascii=False,
            )
        )
    write_claim_marker(
        state_dir=state_dir,
        message=message,
        intent=intent,
        key=key,
        context_marker=context_marker,
    )
    return True


def render_codex_bridge(text: str = "Codex 状态查询") -> str:
    try:
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(CODEX_CONSOLE), "codex", "--no-send"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
            check=False,
        )
    except Exception as exc:
        return run_layered_response(
            text,
            intent="codex_task",
            codex_summary=f"Codex 桥接暂时没接稳：{exc}",
        ).text
    output = (completed.stdout or "").strip()
    return run_layered_response(
        text,
        intent="codex_task",
        codex_summary=output or "CODEX 桥接没有返回内容。要继续派任务，用 /CODEX 开头。",
    ).text


def read_message(args: argparse.Namespace) -> str:
    if args.stdin:
        return sys.stdin.read().strip()
    if args.message:
        return " ".join(args.message).strip()
    return sys.stdin.read().strip()


def main(argv: list[str]) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("message", nargs="*")
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--intent", action="store_true")
    args = parser.parse_args(argv)
    message = read_message(args)
    intent = classify_intent(message)
    if args.intent:
        print(f"{intent.name}\t{','.join(intent.focus_tags)}")
        return 0
    if not claim_request_once(message, intent.name):
        return 0
    reply = reply_for(message)
    if not claim_response_once(reply, intent.name):
        return 0
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
