from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Iterable

from vela_reply_engine import (
    FallbackReplyAdapter,
    ReplyAdapter,
    ReplyContext,
    ToolPolicy,
    default_reply_adapter,
)


ROOT = Path(__file__).resolve().parents[1]
VELA_DIR = ROOT / "VELA"
LEARNING_LOOP_DIR = VELA_DIR / "learning-loop"
VOICE_CONTRACT = VELA_DIR / "voice-contract.json"

CONFIRMED_CACHE_SLOTS = ["09:00", "12:30", "17:00"]

MARKET_WEIGHTS = {
    "A股": 35,
    "美股": 30,
    "韩国": 15,
    "日本": 8,
    "跨市场变量": 8,
    "地缘/军政": 4,
}

VELA_PERSONA_CORE = {
    "冷静判断": 55,
    "战略拆解": 18,
    "赛博神性": 13,
    "毒舌幽默": 14,
}

ENGINEERING_NOISE_TOKENS = (
    "raw payload",
    "validator",
    "contract",
    "endpoint",
    "adapter logs",
    "runtime metadata",
    "session detail",
    "dry run",
    "debug",
    "traceback",
    "not implemented",
    "schema_version",
    "tokens_used",
    "token_budget",
    "sandbox",
    "approval never",
    "approval on-request",
    "<goal_context>",
    "<oai-mem-citation>",
)

WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s，。；,;]+")
CODEX_RUNTIME_PATTERNS = (
    re.compile(r"用量\s*`?[\d,.\s]+tokens?`?[，,。；;\s]*", re.IGNORECASE),
    re.compile(r"耗时(?:约)?\s*`?[^，。；;|]+`?[，,。；;\s]*", re.IGNORECASE),
    re.compile(r"\btokens?(?:_used)?\s*[:=]?\s*`?[\d,./\s]+`?[，,。；;\s]*", re.IGNORECASE),
    re.compile(r"\btoken_budget\s*[:=]?\s*`?[\d,./\s]+`?[，,。；;\s]*", re.IGNORECASE),
    re.compile(r"\bsandbox\s+[^|，。；;,]+", re.IGNORECASE),
    re.compile(r"\bapproval\s+[^|，。；;,]+", re.IGNORECASE),
    re.compile(r"\bmodel\s+[A-Za-z0-9_.:-]+", re.IGNORECASE),
    re.compile(r"\bgpt-[A-Za-z0-9_.:-]+", re.IGNORECASE),
    re.compile(r"工作区\s*[:：]\s*[^\s，。；,;]+", re.IGNORECASE),
)
STAGE_DIRECTION_RE = re.compile(r"[（(][^）)\n]{1,40}[）)]")
EXTRA_FORBIDDEN_DIALOGUE_PHRASES = (
    "作为 VELA",
    "作为VELA",
    "我将",
    "首先",
    "其次",
    "根据设定",
)


@dataclass(frozen=True)
class RouteDecision:
    intent: str
    needs_retrieval: bool
    needs_codex: bool
    needs_deep_reasoning: bool
    cache_allowed: bool
    priority_markets: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AnalysisPacket:
    intent: str
    facts: list[str] = field(default_factory=list)
    judgment: str = ""
    risks: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    confidence: str = "medium"
    source: str = "analysis_layer"


@dataclass(frozen=True)
class LayeredResponse:
    text: str
    intent: str
    used_cache: bool
    used_codex: bool
    used_retrieval: bool
    memory_candidate: bool
    quality_log: Path | None = None
    reply_adapter: str = ""
    real_gpt_enabled: bool = False


@dataclass
class SessionNotes:
    entries: list[dict] = field(default_factory=list)
    persistent: bool = False

    def add(self, message: str, intent: str, response_summary: str) -> None:
        self.entries.append(
            {
                "created_at": utc_now().isoformat(),
                "message_summary": " ".join(str(message or "").split())[:240],
                "intent": intent,
                "response_summary": " ".join(str(response_summary or "").split())[:240],
            }
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def voice_contract_forbidden_phrases() -> tuple[str, ...]:
    phrases = list(EXTRA_FORBIDDEN_DIALOGUE_PHRASES)
    try:
        contract = json.loads(VOICE_CONTRACT.read_text(encoding="utf-8"))
        phrases.extend(contract.get("dialogue_quality_gates", {}).get("forbidden_phrases", []))
    except (OSError, json.JSONDecodeError):
        pass
    clean: list[str] = []
    for phrase in phrases:
        text = str(phrase or "").strip()
        if text and text not in clean:
            clean.append(text)
    return tuple(clean)


def dialogue_quality_issues(text: str) -> list[str]:
    raw = str(text or "")
    issues: list[str] = []
    if STAGE_DIRECTION_RE.search(raw):
        issues.append("stage_direction")
    lower = raw.lower()
    for phrase in voice_contract_forbidden_phrases():
        if phrase.lower() in lower:
            issues.append(f"forbidden_phrase:{phrase}")
    return issues


def strip_dialogue_performance_markers(text: str) -> str:
    cleaned = STAGE_DIRECTION_RE.sub("", str(text or ""))
    for phrase in voice_contract_forbidden_phrases():
        cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[\s，,。；;：:]+", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def guard_wechat_output(text: str, max_chars: int = 3600) -> str:
    """Keep engineering internals out of VELA's WeChat foreground."""
    lines: list[str] = []
    noise_seen = False
    for line in str(text or "").splitlines():
        lower = line.lower()
        if any(token in lower for token in ENGINEERING_NOISE_TOKENS):
            noise_seen = True
            continue
        sanitized = WINDOWS_PATH_RE.sub("本地文件已保存", line)
        if sanitized != line:
            noise_seen = True
        lines.append(sanitized)
    cleaned = "\n".join(line for line in lines if line.strip()).strip()
    if not cleaned:
        cleaned = "K，前台只给结论，噪音已经压到后台。"
    if len(cleaned) > max_chars:
        suffix = "\n\n[已压缩。要长版再开深度分析。]"
        cleaned = cleaned[: max_chars - len(suffix)] + suffix
    return cleaned


def ensure_k_address(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped or stripped.startswith("K") or "K，" in stripped[:12] or "K," in stripped[:12]:
        return stripped
    return "K，" + stripped


def guard_layered_output(
    text: str,
    *,
    intent: str,
    used_codex: bool,
    used_retrieval: bool,
    max_chars: int = 3600,
) -> str:
    if intent != "market_brief" and "Market & World Briefing" in str(text or ""):
        return guard_wechat_output(ensure_k_address("这条不需要市场扫描。先回答当前问题，别把前台变成新闻传送带。"), max_chars=max_chars)
    if intent == "normal_chat" and any(
        token in str(text or "") for token in ("要看盘，说 A股、美股或韩国", "要动 Codex，用 /CODEX")
    ):
        return guard_wechat_output(ensure_k_address("菜单口吻已拦截。在线，说目标，我来收束。"), max_chars=max_chars)
    if intent != "codex_task" and used_codex:
        return guard_wechat_output(ensure_k_address("这条不需要 Codex。工程手先收刀，前台只给判断。"), max_chars=max_chars)
    if intent == "normal_chat" and used_retrieval:
        return guard_wechat_output(ensure_k_address("这条不需要市场扫描。短回、校准、继续。"), max_chars=max_chars)
    if intent != "market_brief":
        text = strip_dialogue_performance_markers(text)
        text = ensure_k_address(text)
    return guard_wechat_output(text, max_chars=max_chars)


def response_length(text: str) -> str:
    size = len(str(text or ""))
    if size < 280:
        return "short"
    if size < 1400:
        return "medium"
    return "long"


def record_reply_quality(
    *,
    conversation_type: str,
    user_goal: str,
    response_text: str,
    used_cache: bool,
    used_retrieval: bool,
    used_codex: bool,
    quality_flags: Iterable[str],
    issues: Iterable[str],
    intent: str | None = None,
    memory_candidate: bool = False,
    log_dir: Path | None = None,
) -> Path:
    log_dir = log_dir or LEARNING_LOOP_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"reply-quality-{utc_now():%Y-%m-%d}.jsonl"
    row = {
        "created_at": utc_now().isoformat(),
        "conversation_type": conversation_type,
        "user_goal": user_goal,
        "intent": intent or conversation_type,
        "used_cache": used_cache,
        "used_codex": used_codex,
        "used_retrieval": used_retrieval,
        "response_length": response_length(response_text),
        "quality_flags": list(quality_flags),
        "issues": list(issues),
        "memory_candidate": memory_candidate,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def record_interaction(
    *,
    message: str,
    intent: str,
    response_text: str,
    used_codex: bool,
    used_retrieval: bool,
    log_dir: Path | None = None,
) -> Path:
    log_dir = log_dir or LEARNING_LOOP_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"interaction-{utc_now():%Y-%m-%d}.jsonl"
    row = {
        "created_at": utc_now().isoformat(),
        "message_summary": " ".join(str(message or "").split())[:240],
        "intent": intent,
        "response_length": response_length(response_text),
        "response_preview": str(response_text or "").strip()[:800],
        "used_codex": used_codex,
        "used_retrieval": used_retrieval,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def read_jsonl_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def latest_learning_rows(pattern: str, log_dir: Path | None = None, limit: int = 12) -> list[dict]:
    log_dir = log_dir or LEARNING_LOOP_DIR
    rows: list[dict] = []
    if not log_dir.exists():
        return rows
    for path in sorted(log_dir.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)[:3]:
        rows.extend(read_jsonl_rows(path))
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return rows[-limit:]


def infer_pressure_scenario(message: str, intent: str) -> str:
    text = str(message or "").lower()
    if intent == "memory_related" and any(token in text for token in ("机器", "机械", "不像", "太像")):
        return "机械纠偏"
    if any(token in text for token in ("累", "疲惫", "撑不住", "继续")):
        return "用户疲惫"
    if any(token in text for token in ("乱", "懵", "不知道", "没方向", "卡住")):
        return "含糊求助"
    if intent in {"project_assistant", "deep_analysis"}:
        return "战略判断"
    return ""


def build_reply_context(
    message: str,
    *,
    intent: str,
    log_dir: Path | None = None,
) -> ReplyContext:
    normalized_message = " ".join(str(message or "").split())
    interactions = latest_learning_rows("interaction-*.jsonl", log_dir=log_dir, limit=8)
    last = interactions[-1] if interactions else {}
    last_response = str(last.get("response_preview") or "")
    repeated_message = bool(last) and str(last.get("message_summary") or "") == normalized_message[:240]
    recent_summary = " / ".join(
        f"{row.get('intent', 'unknown')}:{row.get('message_summary', '')}" for row in interactions[-3:]
    )
    preferences = [
        str(row.get("summary"))
        for row in latest_learning_rows("confirmed-preferences-*.jsonl", log_dir=log_dir, limit=8)
        if row.get("summary")
    ]
    preferences.extend(
        str(row.get("summary"))
        for row in latest_learning_rows("memory-candidates-*.jsonl", log_dir=log_dir, limit=8)
        if row.get("classification") == "style_feedback" and row.get("summary")
    )
    return ReplyContext(
        message=normalized_message,
        intent=intent,
        recent_summary=recent_summary,
        last_response=last_response,
        repeated_message=repeated_message,
        pressure_scenario=infer_pressure_scenario(normalized_message, intent),
        user_preferences=preferences[-6:],
        tool_policy=ToolPolicy(
            allow_market=intent == "market_brief",
            allow_codex=intent == "codex_task",
            allow_retrieval=intent in {"market_brief", "world_brief"},
        ),
    )


def build_memory_candidate(message: str) -> dict:
    text = " ".join(str(message or "").split())
    lower = text.lower()
    classification = "preference"
    style_markers = [
        "新闻列表",
        "太呆",
        "太慢",
        "太长",
        "工程化",
        "太机械",
        "机械",
        "机器人",
        "不像",
        "语气",
        "人格",
        "锋利",
        "毒舌",
    ]
    if any(key in text for key in style_markers):
        classification = "style_feedback"
    elif any(key in text for key in ["A股", "美股", "韩国", "日本", "市场", "美债", "美元"]):
        classification = "market_focus"
    elif any(key in lower for key in ["augsun", "rollqiia", "项目"]):
        classification = "project_state"
    elif any(key in text for key in ["长期目标", "战略", "重大架构", "人格方向"]):
        classification = "strategic_goal"

    sensitive = any(key in text for key in ["身份证", "密码", "账号", "住址", "银行卡", "手机号"])
    summary = text
    for prefix in ("记住：", "记住:", "以后：", "以后:"):
        if summary.startswith(prefix):
            summary = summary.removeprefix(prefix).strip()
    return {
        "created_at": utc_now().isoformat(),
        "level": "Preference Candidate",
        "classification": classification,
        "summary": summary,
        "sensitive": sensitive,
        "requires_confirmation": sensitive or classification in {"strategic_goal"},
        "confirmed": False,
        "storage_policy": "candidate_first",
    }


def record_memory_candidate(message: str, log_dir: Path | None = None) -> Path:
    log_dir = log_dir or LEARNING_LOOP_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"memory-candidates-{utc_now():%Y-%m-%d}.jsonl"
    candidate = build_memory_candidate(message)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(candidate, ensure_ascii=False) + "\n")
    return path


def record_confirmed_preference(
    summary: str,
    *,
    confirmed_by_user: bool,
    log_dir: Path | None = None,
) -> Path:
    if not confirmed_by_user:
        raise ValueError("confirmed user preference requires explicit user confirmation")
    log_dir = log_dir or LEARNING_LOOP_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"confirmed-preferences-{utc_now():%Y-%m-%d}.jsonl"
    row = {
        "created_at": utc_now().isoformat(),
        "level": "Confirmed User Preference",
        "summary": " ".join(str(summary or "").split()),
        "confirmed": True,
        "storage_policy": "explicit_confirmation_only",
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def record_strategic_memory(
    summary: str,
    *,
    memory_type: str,
    confirmed_by_user: bool,
    log_dir: Path | None = None,
) -> Path:
    if not confirmed_by_user:
        raise ValueError("strategic memory requires explicit user confirmation")
    if not str(memory_type or "").strip():
        raise ValueError("strategic memory requires an explicit memory_type")
    log_dir = log_dir or LEARNING_LOOP_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"strategic-memory-{utc_now():%Y-%m-%d}.jsonl"
    row = {
        "created_at": utc_now().isoformat(),
        "level": "Strategic Memory",
        "memory_type": str(memory_type).strip(),
        "summary": " ".join(str(summary or "").split()),
        "confirmed": True,
        "storage_policy": "long_term_high_value_only",
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def render_vela_persona(packet: AnalysisPacket) -> str:
    """Render analysis into VELA voice without inventing new facts."""
    lines: list[str] = []
    if packet.facts:
        lines.append("事实：")
        lines.extend(f"- {fact}" for fact in packet.facts)
    if packet.judgment:
        lines.append(f"判断：{packet.judgment}")
    if packet.risks:
        lines.append("风险：")
        lines.extend(f"- {risk}" for risk in packet.risks)
    if packet.next_actions:
        if len(packet.next_actions) == 1:
            lines.append(f"下一步：{packet.next_actions[0]}")
        else:
            lines.append("下一步：")
            lines.extend(f"- {action}" for action in packet.next_actions)

    if packet.intent in {"project_assistant", "deep_analysis"} and packet.risks:
        lines.append("别把好运气请来当部门主管。先把变量拴住，再谈速度。")
    elif packet.intent == "normal_chat":
        lines.append("在。先校准，再行动。")

    return "\n".join(lines).strip()


def render_normal_chat_persona(message: str) -> str:
    context = ReplyContext(message=str(message or ""), intent="normal_chat")
    return FallbackReplyAdapter().generate(context).text


def analysis_layer(message: str, intent: str, codex_summary: str = "") -> AnalysisPacket:
    text = " ".join(str(message or "").split())
    if intent == "project_assistant":
        return AnalysisPacket(
            intent=intent,
            facts=["用户要推进 AugSun / ROLLQIIA 或 VELA 产品化事项。"],
            judgment="先把目标、约束、当前卡点和最小下一步拆开，别让愿景压扁执行。",
            risks=["把 Codex 输出当产品判断，会让前台变成工程日志。"],
            next_actions=["列出当前目标", "标出最大阻塞", "需要代码执行时再交给 /CODEX"],
        )
    if intent == "deep_analysis":
        return AnalysisPacket(
            intent=intent,
            facts=[f"用户要求深度验尸：{text or '未给出具体对象'}"],
            judgment="先找结构性故障，再分离噪音、风险和最短修正路径。",
            risks=["没有事实包就直接下结论，会把锋利变成表演。"],
            next_actions=["列问题", "列风险", "给最短修正路径", "标出需要验证的数据"],
            confidence="medium",
        )
    if intent == "codex_task":
        fact = codex_summary.strip() or "Codex 桥接没有返回可用摘要。"
        return AnalysisPacket(
            intent=intent,
            facts=[fact],
            judgment="Codex 只负责工程执行；VELA 只取结论、风险和下一步，不把后台噪音倒进前台。",
            risks=["如果直接复读终端输出，微信端会退化成日志窗口。"],
            next_actions=["需要继续开发时，用 /CODEX 加具体任务"],
        )
    if intent == "memory_related":
        candidate = build_memory_candidate(message)
        return AnalysisPacket(
            intent=intent,
            facts=[f"候选类型：{candidate['classification']}"],
            judgment="先进入候选池，不直接写死为长期记忆。",
            risks=["未经确认的偏好如果直接固化，会把一次反馈误判成长期规律。"],
            next_actions=["后续回复先按这条反馈校准", "需要长期固化时等待用户明确确认"],
        )
    return AnalysisPacket(
        intent=intent,
        judgment=render_normal_chat_persona(message),
        next_actions=[],
    )


def render_memory_reply(message: str) -> str:
    candidate = build_memory_candidate(message)
    if candidate["sensitive"]:
        return "这条涉及敏感信息，我先不写长期记忆。要存，必须你明确确认。"
    if candidate["classification"] == "style_feedback":
        return "收到。先记为风格反馈候选，不写死进长期记忆。下一轮减少新闻列表感：先给判断，再给依据。"
    return f"收到。先放入候选记忆，不急着刻碑：{candidate['summary']}"


def render_world_brief_reply() -> str:
    return (
        "世界线进入 world_brief。只看能穿透到风险偏好、能源、航运、军工、汇率和利率的事件；"
        "纯热闹不入桌。\n\n"
        "要和市场联动，发：Market & World Briefing。"
    )


def render_project_reply() -> str:
    return render_vela_persona(analysis_layer("", "project_assistant"))


def render_deep_analysis_reply() -> str:
    return render_vela_persona(analysis_layer("", "deep_analysis"))


def sanitize_codex_summary(codex_output: str) -> str:
    """Keep Codex status useful while removing runtime/accounting metadata."""
    summary = " ".join(str(codex_output or "").split())
    if not summary:
        return ""
    summary = WINDOWS_PATH_RE.sub("本地路径已收起", summary)
    for pattern in CODEX_RUNTIME_PATTERNS:
        summary = pattern.sub("", summary)
    summary = re.sub(r"\s*\|\s*", " ", summary)
    summary = re.sub(r"\s+([，。；,;])", r"\1", summary)
    summary = re.sub(r"\s{2,}", " ", summary)
    return summary.strip(" |，,；;")


def render_codex_product_judgment(codex_output: str) -> str:
    summary = sanitize_codex_summary(codex_output)
    if not summary:
        summary = "暂时没有拿到 Codex 可用摘要。"
    if len(summary) > 520:
        summary = summary[:519] + "…"
    packet = analysis_layer("", "codex_task", codex_summary=summary)
    return "VELA · CODEX 工程摘要\n" + render_vela_persona(packet)


def engine_text_for_intent(
    context: ReplyContext,
    *,
    adapter: ReplyAdapter | None = None,
    codex_summary: str = "",
) -> tuple[str, str, bool]:
    adapter = adapter or default_reply_adapter()
    if context.intent == "normal_chat":
        result = adapter.generate(context)
        return result.text, result.adapter, result.used_api
    if context.intent == "memory_related":
        result = adapter.generate(context)
        return result.text, result.adapter, result.used_api
    if context.intent in {"project_assistant", "deep_analysis"}:
        result = adapter.generate(context)
        base = analysis_layer(context.message, context.intent, codex_summary=codex_summary)
        packet = AnalysisPacket(
            intent=base.intent,
            facts=base.facts,
            judgment=result.text or base.judgment,
            risks=base.risks,
            next_actions=base.next_actions,
            confidence=base.confidence,
            source=f"reply_engine:{result.adapter}",
        )
        return render_vela_persona(packet), result.adapter, result.used_api
    if context.intent == "codex_task":
        return render_codex_product_judgment(codex_summary), "codex_bridge", False
    if context.intent == "world_brief":
        return render_world_brief_reply(), "local_world_brief", False
    return render_vela_persona(analysis_layer(context.message, context.intent)), "analysis_layer", False


def avoid_repeated_reply(text: str, context: ReplyContext) -> str:
    if context.last_response and str(text or "").strip() == context.last_response.strip():
        return FallbackReplyAdapter().generate(context).text
    return text


def run_layered_response(
    message: str,
    *,
    intent: str,
    codex_summary: str = "",
    log_dir: Path | None = None,
    reply_adapter: ReplyAdapter | None = None,
) -> LayeredResponse:
    used_codex = intent == "codex_task"
    used_retrieval = intent in {"world_brief"}
    used_cache = intent == "market_brief"
    memory_candidate = intent == "memory_related"

    context = build_reply_context(message, intent=intent, log_dir=log_dir)

    if intent == "memory_related":
        record_memory_candidate(message, log_dir=log_dir)
    rendered, adapter_name, adapter_used_api = engine_text_for_intent(
        context,
        adapter=reply_adapter,
        codex_summary=codex_summary,
    )
    rendered = avoid_repeated_reply(rendered, context)
    issues = dialogue_quality_issues(rendered)

    guarded = guard_layered_output(
        rendered,
        intent=intent,
        used_codex=used_codex,
        used_retrieval=used_retrieval,
    )
    quality_path = record_reply_quality(
        conversation_type=intent,
        user_goal=message,
        response_text=guarded,
        used_cache=used_cache,
        used_retrieval=used_retrieval,
        used_codex=used_codex,
        quality_flags=["reply_engine", f"adapter:{adapter_name}", "persona_rendered", "guarded_output"],
        issues=issues,
        intent=intent,
        memory_candidate=memory_candidate,
        log_dir=log_dir,
    )
    record_interaction(
        message=message,
        intent=intent,
        response_text=guarded,
        used_codex=used_codex,
        used_retrieval=used_retrieval,
        log_dir=log_dir,
    )
    return LayeredResponse(
        text=guarded,
        intent=intent,
        used_cache=used_cache,
        used_codex=used_codex,
        used_retrieval=used_retrieval,
        memory_candidate=memory_candidate,
        quality_log=quality_path,
        reply_adapter=adapter_name,
        real_gpt_enabled=adapter_used_api,
    )
