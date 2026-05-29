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
    format_freshness_status,
    format_market_brief,
    market_freshness_status,
)
from vela_product_layers import (
    RouteDecision,
    guard_wechat_output,
    record_reply_quality,
    run_layered_response,
)
from vela_reply_engine import FallbackReplyAdapter, reply_engine_status


ROOT = Path(__file__).resolve().parents[1]
CODEX_CONSOLE = ROOT / "tools" / "clawbot_codex_console.py"
SEND_ONCE_DIR = ROOT / "VELA" / "send-once"


@dataclass(frozen=True)
class Intent:
    name: str
    confidence: float
    focus_tags: list[str]
    codex_allowed: bool = False
    market_allowed: bool = False


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
WORLD_KEYWORDS = ["世界", "全球", "军政", "地缘", "外交", "战争", "制裁", "航运", "能源安全", "世界简报"]
CODEX_KEYWORDS = ["codex", "代码", "提交", "diff", "git", "任务状态", "开发任务", "电脑控制"]
PROJECT_KEYWORDS = ["augsun", "rollqiia", "项目", "广告中心", "intelligence center", "规划", "功能如何"]
DEEP_KEYWORDS = ["深入分析", "深度分析", "地狱验尸", "验尸", "架构判断", "架构", "推演", "复盘", "根因", "策略验尸"]
STYLE_FEEDBACK_KEYWORDS = [
    "新闻列表",
    "太呆",
    "太慢",
    "太长",
    "太工程化",
    "太机械",
    "机械",
    "机器人",
    "不像vela",
    "不像 vela",
    "不够锋利",
    "语气",
    "风格",
    "人格",
]
MEMORY_KEYWORDS = ["记住", "记忆", "长期", "以后", "默认", "偏好", "别忘", "学习一下", *STYLE_FEEDBACK_KEYWORDS]


def ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def classify_intent(text: str) -> Intent:
    raw = (text or "").strip()
    norm = normalize(raw)
    if not norm:
        return Intent("normal_chat", 0.9, [])
    if norm in {"/codex", "/vela codex"}:
        return Intent("codex_task", 1.0, ["codex"], codex_allowed=True)
    if raw.startswith("/"):
        return Intent("codex_task", 0.8, ["slash_command"], codex_allowed=True)
    if norm == "vela" or norm in GREETING_SET or norm in {"你好", "在吗", "在么", "hello", "hi"}:
        return Intent("normal_chat", 1.0, [])
    if is_market_refresh_request(norm):
        return Intent("market_refresh", 0.94, market_focus_tags(norm), market_allowed=True)
    if is_freshness_question(norm) and not is_market_summary_request(norm):
        return Intent("freshness_status", 0.95, ["freshness"])
    if contains_any(norm, MEMORY_KEYWORDS):
        return Intent("memory_related", 0.88, memory_focus_tags(norm))
    if contains_any(norm, CODEX_KEYWORDS):
        return Intent("codex_task", 0.86, ["codex"], codex_allowed=True)
    if contains_any(norm, MARKET_KEYWORDS):
        tags = market_focus_tags(norm)
        return Intent("market_brief", 0.9, tags, market_allowed=True)
    if contains_any(norm, WORLD_KEYWORDS):
        return Intent("world_brief", 0.82, ["geopolitics", "global"])
    if contains_any(norm, PROJECT_KEYWORDS):
        return Intent("project_assistant", 0.78, ["project"])
    if contains_any(norm, DEEP_KEYWORDS):
        return Intent("deep_analysis", 0.82, deep_focus_tags(norm))
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


def is_market_refresh_request(text: str) -> bool:
    if not contains_any(text, MARKET_KEYWORDS + ["资讯", "新闻", "市场"]):
        return False
    if "实时吗" in text or "是实时" in text:
        return False
    return contains_any(text, REFRESH_KEYWORDS)


def is_fast_greeting(text: str) -> bool:
    norm = normalize(text)
    return norm == "vela" or norm in GREETING_SET or norm in {"你好", "你好 vela", "在吗", "在么", "hello", "hi"}


def is_plain_ping(text: str) -> bool:
    norm = normalize(text)
    return norm == "vela" or norm in {"你好", "在吗", "在么", "hello", "hi"}


def should_force_fallback_for_greeting(text: str) -> bool:
    if is_plain_ping(text):
        return True
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
        needs_retrieval=intent.name in {"market_brief", "world_brief", "market_refresh"},
        needs_codex=intent.codex_allowed,
        needs_deep_reasoning=intent.name in {"market_brief", "deep_analysis", "project_assistant"},
        cache_allowed=intent.name in {"market_brief", "world_brief", "freshness_status", "market_refresh"},
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
    brief = build_cached_market_brief(text)
    status_text = format_freshness_status(status)
    if brief is None:
        return guard_wechat_output(status_text + "\n\n当前没有可用市场缓存；需要刷新链路接入外部检索/API 后再生成报告。")
    prefix = "以下基于最近缓存，先给可用判断；这不是实时直播。"
    body = format_market_brief(brief, detail=is_expanded_market_query(text))
    return guard_wechat_output(f"{prefix}\n{status_text}\n\n{body}")


def render_market_refresh_reply(text: str) -> str:
    status = market_freshness_status(text)
    lines = [
        "实时检索链路：已识别你要的是实时资讯，本次不返回缓存简报。",
        f"last_updated: {status.last_updated}",
        "source_type: live_refresh_required",
        "data_status: refresh_required",
        "refresh_available: true",
        "refresh_in_progress: false",
        "",
        "失效控制：如果外部实时源/API 未接通或刷新超过前台预算，我只返回状态，不把缓存伪装成实时情报。",
        "下一步需要由独立刷新任务接入外部搜索/API，完成后再生成实时简报。",
    ]
    return guard_wechat_output("\n".join(lines))


def reply_for(text: str) -> str:
    intent = classify_intent(text)
    if intent.name == "freshness_status":
        reply = render_freshness_reply(text)
        record_reply_quality(
            conversation_type="freshness_status",
            user_goal=text,
            response_text=reply,
            used_cache=True,
            used_retrieval=False,
            used_codex=False,
            quality_flags=["fast_lane", "freshness_status", "guarded_output"],
            issues=[],
            intent="freshness_status",
        )
        return reply
    if intent.name == "market_refresh":
        reply = render_market_refresh_reply(text)
        record_reply_quality(
            conversation_type="market_refresh",
            user_goal=text,
            response_text=reply,
            used_cache=True,
            used_retrieval=False,
            used_codex=False,
            quality_flags=["refresh_lane_status_first", "guarded_output"],
            issues=[],
            intent="market_refresh",
        )
        return reply
    if intent.name == "market_brief":
        reply = render_cached_market_reply(text)
        guarded = guard_wechat_output(reply)
        record_reply_quality(
            conversation_type="market_brief",
            user_goal=text,
            response_text=guarded,
            used_cache=True,
            used_retrieval=False,
            used_codex=False,
            quality_flags=["market_weight_aligned", "guarded_output"],
            issues=[],
            intent="market_brief",
        )
        return guarded
    if intent.name == "codex_task":
        return guard_wechat_output(render_codex_bridge())
    if intent.name == "normal_chat" and is_fast_greeting(text) and should_force_fallback_for_greeting(text):
        return run_layered_response(text, intent=intent.name, reply_adapter=FallbackReplyAdapter()).text
    return run_layered_response(text, intent=intent.name).text


def is_expanded_market_query(text: str) -> bool:
    norm = normalize(text)
    return any(token in norm for token in ("展开", "详细", "全部", "来源", "新闻来源"))


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


def request_key(message: str, intent: str) -> str:
    payload = f"{intent}|{normalized_request_text(message)}"
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


def response_key(response: str, intent: str) -> str:
    payload = f"{intent}|{normalized_request_text(response)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


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
    key = response_key(response, intent)
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
    key = request_key(message, intent)
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
                    "message_preview": " ".join(str(message or "").split())[:160],
                },
                ensure_ascii=False,
            )
        )
    return True


def render_codex_bridge() -> str:
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
            "Codex 桥接异常",
            intent="codex_task",
            codex_summary=f"Codex 桥接暂时没接稳：{exc}",
        ).text
    output = (completed.stdout or "").strip()
    return run_layered_response(
        "Codex 状态查询",
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
