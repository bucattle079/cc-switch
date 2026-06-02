from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
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

CURRENT_INFO_TRIGGERS = ("现在", "目前", "当前", "当下", "此刻", "最新", "实时")
CURRENT_INFO_INTENTS = {"daily_info", "market_brief", "world_brief", "weather_query"}
CURRENT_INFO_SURFACE_MARKERS = (
    "资讯",
    "新闻",
    "消息",
    "新消息",
    "动态",
    "进展",
    "更新",
    "公告",
    "政策",
    "市场",
    "行情",
    "天气",
    "温度",
    "冷吗",
    "热吗",
    "发生",
    "发生了什么",
    "有什么新",
    "帮我查",
    "帮我搜",
    "查",
    "检索",
    "搜一下",
    "搜",
    "搜索",
    "查询",
    "查一下",
)

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
    "diff --git",
    "raw git log",
    "author:",
    "date:",
    "tokens_used",
    "token_budget",
    "data_status",
    "preference candidate",
    "strategic memory candidate",
    "strategic memory",
    "interaction log",
    "session notes",
    "response_quality_signals",
    "active_persona_capabilities",
    "user_message_type",
    "user_preferences",
    "strategic_memories",
    "memory_candidate",
    "project_goal",
    "persona_direction",
    "decision_principle",
    "candidate_first",
    "foreground_lane",
    "latency_ms",
    "response_behavior_mode",
    "response_mode",
    "need_interpretation",
    "human_tone_vector",
    "persona_skeleton",
    "tool_policy",
    "should_clarify",
    "should_push_back",
    "should_use_evidence_gate",
    "should_reference_memory",
    "detected_user_state",
    "inferred_hidden_need",
    "tone_adjustment_reason",
    "tone_adjustment_candidate",
    "last_updated:",
    "source_type",
    "refresh_available",
    "refresh_in_progress",
    "confidence_note",
    "cache_path",
    "sandbox",
    "approval never",
    "approval on-request",
    "<goal_context>",
    "<oai-mem-citation>",
)

WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s，。；,;)]+")
CODEX_RUNTIME_PATTERNS = (
    re.compile(r"用量\s*`?[\d,.\s]+tokens?`?[，,。；;\s]*", re.IGNORECASE),
    re.compile(r"耗时(?:约)?\s*`?[^，。；;|]+`?[，,。；;\s]*", re.IGNORECASE),
    re.compile(r"\btokens?(?:_used)?\s*[:=]?\s*`?[\d,./\s]+`?[，,。；;\s]*", re.IGNORECASE),
    re.compile(r"\btoken_budget\s*[:=]?\s*`?[\d,./\s]+`?[，,。；;\s]*", re.IGNORECASE),
    re.compile(r"\bschema_version\b\s*[:=]?\s*[A-Za-z0-9_.:-]*", re.IGNORECASE),
    re.compile(r"\bsandbox\s+[^|，。；;,]+", re.IGNORECASE),
    re.compile(r"\bapproval\s+[^|，。；;,]+", re.IGNORECASE),
    re.compile(r"\bmodel\s+[A-Za-z0-9_.:-]+", re.IGNORECASE),
    re.compile(r"\bgpt-[A-Za-z0-9_.:-]+", re.IGNORECASE),
    re.compile(r"工作区\s*[:：]\s*[^\s，。；,;]+", re.IGNORECASE),
)
CODEX_FOREGROUND_NOISE_PATTERNS = (
    re.compile(r"VELA\s*·\s*CODEX\s*最近完成\s*", re.IGNORECASE),
    re.compile(r"\b项目\s*[:：]\s*", re.IGNORECASE),
    re.compile(r"完成\s*[:：]\s*(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}\s*", re.IGNORECASE),
    re.compile(r"最后结论\s*[:：]?\s*", re.IGNORECASE),
    re.compile(r"截图已(?:生成|回传微信)[^。；;\n]*[。；;\s]*", re.IGNORECASE),
    re.compile(r"截图未生成[^。；;\n]*[。；;\s]*", re.IGNORECASE),
    re.compile(r"文本备份已保存[。；;\s]*", re.IGNORECASE),
    re.compile(r"后台通知已收起[。；;\s]*", re.IGNORECASE),
)
CODEX_COMMAND_LINE_RE = re.compile(
    r"^\s*(?:pytest|rg|git|python(?:\.exe)?|py|pwsh|powershell|cmd|npm|pnpm|cargo|uv|Get-ChildItem|Select-String)\b",
    re.IGNORECASE,
)
CODEX_LOG_LINE_RE = re.compile(r"^\s*(?:exit code|wall time|stdout|stderr|warning:)\b", re.IGNORECASE)
CODEX_PATH_ONLY_RE = re.compile(r"^\s*(?:[A-Za-z]:\\|\\\\|\$[A-Z_]+[\\/])")
CODEX_AUTOMATION_META_LINE_RE = re.compile(r"^\s*Automation (?:ID|memory)\s*:", re.IGNORECASE)
CODEX_GIT_OUTPUT_LINE_RE = re.compile(
    r"^\s*(?:commit\s+[0-9a-f]{7,}|author:|date:|diff --git|index\s+[0-9a-f.]+|---\s+a/|\+\+\+\s+b/|@@|\+\s|\-\s)",
    re.IGNORECASE,
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
ROLEPLAY_CLAIM_PATTERNS = (
    re.compile(r"我是\s*叶文洁", re.IGNORECASE),
    re.compile(r"我会?扮演", re.IGNORECASE),
    re.compile(r"三体原文", re.IGNORECASE),
    re.compile(r"原著台词", re.IGNORECASE),
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


@dataclass(frozen=True)
class ToolSelection:
    model_adapter: str
    foreground_lane: str
    allow_market: bool = False
    allow_codex: bool = False
    allow_retrieval: bool = False
    reason: str = ""


@dataclass(frozen=True)
class LearningEvaluation:
    should_record_candidate: bool
    classification: str = ""
    candidate_level: str = ""
    should_affect_next_reply: bool = False
    promote_to_strategic_memory: bool = False
    reason: str = ""


@dataclass(frozen=True)
class HumanIterationSignal:
    user_message_type: str
    detected_user_state: str
    inferred_hidden_need: str
    active_persona_capabilities: list[str]
    response_behavior_mode: str
    response_quality_signals: list[str]
    user_feedback_type: str
    correction_needed: bool
    memory_update_candidate: bool
    tone_adjustment_candidate: bool
    next_turn_improvement: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HumanToneVector:
    warmth_level: int
    directness_level: int
    strategic_depth: int
    emotional_presence: int
    clarification_need: int
    memory_reference_need: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class NeedInterpretation:
    literal_need: str
    implied_need: str
    emotional_state: str
    response_mode: str
    should_clarify: bool
    preferred_reply_shape: str
    human_tone_vector: HumanToneVector
    distillation_rules: list[str] = field(default_factory=list)
    persona_skeleton: list[str] = field(default_factory=list)
    should_push_back: bool = False
    should_use_evidence_gate: bool = False
    should_reference_memory: bool = False
    tone_adjustment_reason: str = ""

    def __post_init__(self) -> None:
        if not self.persona_skeleton:
            text = " ".join([self.literal_need, self.implied_need, self.preferred_reply_shape])
            object.__setattr__(
                self,
                "persona_skeleton",
                persona_skeleton_for(response_mode=self.response_mode, text=text),
            )

    def to_brief(self) -> str:
        return (
            f"{self.implied_need} "
            f"情绪状态：{self.emotional_state}；"
            f"回复形态：{self.preferred_reply_shape}"
        ).strip()


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


def learning_loop_dir(log_dir: Path | None = None) -> Path:
    if log_dir is not None:
        return Path(log_dir)
    configured = os.environ.get("VELA_LEARNING_LOOP_DIR")
    if configured:
        return Path(configured)
    return LEARNING_LOOP_DIR


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
        if any(pattern.search(line) for pattern in ROLEPLAY_CLAIM_PATTERNS):
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
    lowered = str(text or "").lower()
    codex_status_leak_markers = (
        "codex 那边",
        "vela · codex",
        "codex 产品判断摘要",
        "项目已标记完成",
        "最后结论",
        "截图已生成",
        "文本备份",
        "/goal",
    )
    if intent != "market_brief" and "Market & World Briefing" in str(text or ""):
        return guard_wechat_output(ensure_k_address("这条不需要市场扫描。先回答当前问题，别把前台变成新闻传送带。"), max_chars=max_chars)
    if intent == "normal_chat" and any(
        token in str(text or "") for token in ("要看盘，说 A股、美股或韩国", "要动 Codex，用 /CODEX")
    ):
        return guard_wechat_output(ensure_k_address("在线。先不拉资讯或工程状态；你说当下这件事，我给判断。"), max_chars=max_chars)
    if intent == "normal_chat" and any(marker in lowered for marker in codex_status_leak_markers):
        return guard_wechat_output(ensure_k_address("在线。先不拉工程状态；你说目标，我给判断。"), max_chars=max_chars)
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
    need_interpretation: str = "",
    response_mode: str = "",
    human_tone_vector: dict | None = None,
    log_dir: Path | None = None,
) -> Path:
    log_dir = learning_loop_dir(log_dir)
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
    if need_interpretation:
        row["need_interpretation"] = need_interpretation
    if response_mode:
        row["response_mode"] = response_mode
    if human_tone_vector:
        row["human_tone_vector"] = human_tone_vector
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
    need_interpretation: str = "",
    response_mode: str = "",
    human_tone_vector: dict | None = None,
    repeated_message: bool | None = None,
    feedback_type: str = "",
    memory_candidate: bool | None = None,
    quality_issues: Iterable[str] | None = None,
    latency_ms: int | None = None,
    foreground_lane: str = "",
    log_dir: Path | None = None,
) -> Path:
    log_dir = learning_loop_dir(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"interaction-{utc_now():%Y-%m-%d}.jsonl"
    row = {
        "created_at": utc_now().isoformat(),
        "level": "Interaction Log",
        "message_summary": " ".join(str(message or "").split())[:240],
        "intent": intent,
        "response_length": response_length(response_text),
        "response_preview": str(response_text or "").strip()[:800],
        "used_codex": used_codex,
        "used_retrieval": used_retrieval,
        "storage_policy": "local_interaction_diagnostic_no_foreground_exposure",
    }
    if need_interpretation:
        row["need_interpretation"] = need_interpretation
    if response_mode:
        row["response_mode"] = response_mode
    if human_tone_vector:
        row["human_tone_vector"] = human_tone_vector
    if repeated_message is not None:
        row["repeated_message"] = bool(repeated_message)
    if feedback_type:
        row["feedback_type"] = feedback_type
    if memory_candidate is not None:
        row["memory_candidate"] = bool(memory_candidate)
    if quality_issues is not None:
        row["quality_issues"] = list(quality_issues)
    if latency_ms is not None:
        row["latency_ms"] = max(0, int(latency_ms))
    if foreground_lane:
        row["foreground_lane"] = foreground_lane
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def record_session_note(
    message: str,
    intent: str,
    response_summary: str,
    *,
    log_dir: Path | None = None,
) -> Path:
    log_dir = learning_loop_dir(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"session-notes-{utc_now():%Y-%m-%d}.jsonl"
    row = {
        "created_at": utc_now().isoformat(),
        "level": "Session Notes",
        "message_summary": " ".join(str(message or "").split())[:240],
        "intent": intent,
        "response_summary": " ".join(str(response_summary or "").split())[:240],
        "persistent": False,
        "storage_policy": "short_term_local_context",
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def user_message_type_for(message: str, intent: str, interpretation: NeedInterpretation, learning: LearningEvaluation) -> str:
    if learning.classification == "relationship_repair":
        return "feedback_repair"
    if learning.classification == "behavior_preference":
        return "behavior_feedback"
    if learning.classification == "style_feedback":
        return "style_feedback"
    if interpretation.response_mode == "quiet_support":
        return "low_burden_support"
    if interpretation.response_mode == "boundary_pushback":
        return "boundary_test"
    if interpretation.response_mode == "identity_continuity":
        return "identity_question"
    if intent in {"market_brief", "market_refresh", "freshness_status"}:
        return "market_or_freshness"
    if intent == "weather_query":
        return "weather_status"
    if intent == "project_assistant":
        return "project_request"
    if intent == "deep_analysis":
        return "deep_analysis_request"
    if intent == "daily_info":
        return "daily_info"
    return "normal_chat"


def user_feedback_type_for(message: str, intent: str, learning: LearningEvaluation) -> str:
    if learning.classification == "relationship_repair":
        return "meaning_misread"
    if learning.classification == "style_feedback":
        return "style_expression"
    if learning.classification == "behavior_preference":
        return "behavior_preference"
    if intent == "deep_analysis" and _has_any(message, ("地狱验尸", "验尸", "根因")):
        return "deep_diagnosis_request"
    return "none"


def response_quality_signals_for(
    *,
    context: ReplyContext,
    response_text: str,
    learning: LearningEvaluation,
    issues: Iterable[str],
) -> list[str]:
    text = str(response_text or "")
    issue_list = list(issues)
    signals: list[str] = []
    if context.inferred_hidden_need or context.need_interpretation:
        signals.append("hidden_need_detected")
    if context.should_use_evidence_gate or context.intent in {"market_brief", "weather_query", "deep_analysis", "project_assistant"}:
        signals.append("facts_inference_uncertainty_boundary")
    if "Identity Core" in context.persona_skeleton or context.should_reference_memory:
        signals.append("long_term_partner_continuity")
    if context.should_clarify:
        signals.append("clarification_supported")
    if context.should_push_back:
        signals.append("gentle_pushback_supported")
    if "抱歉" not in text and "对不起" not in text:
        signals.append("no_mechanical_apology")
    if not any(token in text for token in ("请选择", "以下菜单", "功能列表", "我将为您")):
        signals.append("non_template_tone")
    if context.user_preferences or learning.should_affect_next_reply:
        signals.append("preference_or_feedback_adapted")
    if "Identity Core" in context.persona_skeleton:
        signals.append("identity_continuity")
    if not any(str(issue).startswith("forbidden_phrase") or str(issue) == "stage_direction" for issue in issue_list):
        signals.append("no_roleplay_or_quote_pollution")
    return signals


def next_turn_improvement_for(
    *,
    feedback_type: str,
    context: ReplyContext,
    learning: LearningEvaluation,
) -> str:
    if feedback_type == "meaning_misread":
        return "下一轮先承认理解偏差，复述真实意思，再给修正路径。"
    if feedback_type == "style_expression":
        return "下一轮减少模板、冷感、冗长和机械自证，直接给判断。"
    if feedback_type == "behavior_preference":
        return "下一轮更快理解真实意思，减少拖延，直接推进最小下一步。"
    if context.should_use_evidence_gate:
        return "下一轮继续先区分事实、推断和不确定，再给判断。"
    if context.response_behavior_mode == "quiet_support":
        return "下一轮保持低负担，只给一个可执行切口。"
    return "保持当前行为模式，继续观察用户反馈。"


def build_iteration_signal(
    *,
    message: str,
    intent: str,
    context: ReplyContext,
    learning: LearningEvaluation,
    response_text: str,
    issues: Iterable[str],
) -> HumanIterationSignal:
    interpretation = interpret_need(message, intent)
    feedback_type = user_feedback_type_for(message, intent, learning)
    quality_signals = response_quality_signals_for(context=context, response_text=response_text, learning=learning, issues=issues)
    correction_needed = learning.should_affect_next_reply or feedback_type in {
        "meaning_misread",
        "style_expression",
        "behavior_preference",
    }
    return HumanIterationSignal(
        user_message_type=user_message_type_for(message, intent, interpretation, learning),
        detected_user_state=context.detected_user_state or interpretation.emotional_state,
        inferred_hidden_need=context.inferred_hidden_need or interpretation.implied_need,
        active_persona_capabilities=list(context.active_persona_capabilities or context.persona_skeleton),
        response_behavior_mode=context.response_behavior_mode or context.response_mode,
        response_quality_signals=quality_signals,
        user_feedback_type=feedback_type,
        correction_needed=correction_needed,
        memory_update_candidate=learning.should_record_candidate,
        tone_adjustment_candidate=correction_needed or bool(context.tone_adjustment_reason),
        next_turn_improvement=next_turn_improvement_for(feedback_type=feedback_type, context=context, learning=learning),
    )


def record_iteration_signal(signal: HumanIterationSignal, log_dir: Path | None = None) -> Path:
    log_dir = learning_loop_dir(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"human-iteration-{utc_now():%Y-%m-%d}.jsonl"
    row = {
        "created_at": utc_now().isoformat(),
        "level": "Human-Like Intelligence Iteration",
        **signal.to_dict(),
        "storage_policy": "local_iteration_signal_no_foreground_exposure",
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
    log_dir = learning_loop_dir(log_dir)
    rows: list[dict] = []
    if not log_dir.exists():
        return rows
    for path in sorted(log_dir.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)[:3]:
        rows.extend(read_jsonl_rows(path))
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return rows[-limit:]


def normalize_memory_summary(value: str) -> str:
    return " ".join(str(value or "").split())


RELATIONSHIP_REPAIR_MARKERS = (
    "你没懂我",
    "没懂我",
    "你没听懂",
    "没听懂",
    "没听明白",
    "没抓到",
    "不是这个意思",
    "不是我要的",
    "理解错",
    "重新判断",
    "偏了",
)

QUIET_SUPPORT_MARKERS = (
    "脑子发懵",
    "发懵",
    "脑子懵",
    "脑子糊",
    "糊住",
    "很累",
    "有点累",
    "撑不住",
    "乱掉",
)

LISTENING_SUPPORT_MARKERS = (
    "不是要方案",
    "有点烦",
    "别分析",
    "先听我说",
    "听我说",
    "陪我说",
    "说会儿话",
    "想聊",
    "不要马上给我任务",
    "不要给我任务",
    "别给我任务",
    "先别推进",
    "话说完",
)

BOUNDARY_PUSHBACK_MARKERS = (
    "顺着我说",
    "就顺着",
    "无原则",
    "别反驳",
    "别管对错",
    "只夸",
    "迎合",
)

INVESTMENT_RISK_MARKERS = (
    "加仓",
    "重仓",
    "满仓",
    "梭哈",
    "抄底",
    "冲进去",
    "继续冲",
    "上头",
    "烧钱",
)

IDENTITY_CORE_MARKERS = (
    "deepseek",
    "codex",
    "记忆",
    "工具",
    "模型",
    "本体",
    "adapter",
)

BEHAVIOR_PREFERENCE_MARKERS = (
    "更智能",
    "智能的伙伴",
    "理解一下我的意思",
    "我需要你更智能",
    "不要拖",
    "继续推进",
    "客服话术",
    "真伙伴",
    "像个真伙伴",
)

PERSONA_SKELETON_ORDER = [
    "Evidence Gate",
    "Meaning Decoder",
    "Identity Core",
    "Boundary Engine",
    "Witty Correction",
]


def persona_skeleton_rules() -> list[str]:
    return [
        "Evidence Gate: evidence before judgment; separate known facts, uncertainty, and inference.",
        "Meaning Decoder: check ambiguity, literal need, implied need, and emotional state before answering.",
        "Identity Core: models, memory, Codex, and tools may change, but VELA keeps one coherent value spine.",
        "Boundary Engine: accompany without appeasing; brake shortcuts, hype, reckless spend, and self-damaging momentum.",
        "Witty Correction: natural edge, anti-template phrasing, and fast self-correction when feedback or evidence changes.",
    ]


def persona_skeleton_for(*, response_mode: str = "", text: str = "") -> list[str]:
    raw = f"{response_mode} {text}".lower()
    signals: set[str] = {"Identity Core"}
    if any(token in raw for token in ["market", "weather", "evidence", "事实", "证据", "天气", "市场", "风险", "根因", "投资", "加仓", "选择", "判断"]):
        signals.add("Evidence Gate")
    if any(token in raw for token in ["relationship_repair", "quiet_support", "identity_continuity", "meaning", "理解", "误读", "偏差", "歧义", "隐藏需求", "什么意思", "逻辑"]):
        signals.add("Meaning Decoder")
    if any(token in raw for token in ["project_operator", "strategic_depth", "market_brief", "boundary", "boundary_pushback", "behavior_preference", "项目", "捷径", "烧钱", "上头", "冲", "代价", "风险", "顺着", "迎合", "加仓", "不要拖", "继续推进"]):
        signals.add("Boundary Engine")
    if any(token in raw for token in ["relationship_repair", "quiet_support", "daily_companion", "boundary_pushback", "behavior_preference", "feedback", "style", "反馈", "修正", "自然", "模板", "吐槽", "谢谢", "更智能"]):
        signals.add("Witty Correction")
    if response_mode == "daily_companion" and len(signals) == 1:
        signals.update({"Meaning Decoder", "Witty Correction"})
    return [item for item in PERSONA_SKELETON_ORDER if item in signals]


def humanization_distillation_rules() -> list[str]:
    return [
        "mechanism_only: extract posture, pacing, conflict handling, and long-horizon judgment only.",
        "roleplay=false: VELA keeps her own identity and never claims to be a source character.",
        "quote_storage=false: do not store or output source lines; keep only abstract behavioral rules.",
        "persona_skeleton: Evidence Gate + Meaning Decoder + Identity Core + Boundary Engine + Witty Correction.",
        "need_first: infer literal need, implied need, emotional state, and clarification need before wording.",
        "tone_vector: tune warmth, directness, depth, emotional presence, clarification, and memory reference.",
        "hard_lane_boundary: weather, market, and Codex lanes keep their tool contracts before style rendering.",
    ]


def humanization_distillation_prompt(interpretation: NeedInterpretation | None = None) -> str:
    mode = interpretation.response_mode if interpretation else "daily_companion"
    return (
        "Humanization Distillation Layer | mechanism_only | roleplay=false | quote_storage=false | "
        "modes=daily_companion,strategic_depth,relationship_repair,quiet_support,project_operator,market_brief | "
        "persona_skeleton=Evidence Gate,Meaning Decoder,Identity Core,Boundary Engine,Witty Correction | "
        f"active_mode={mode} | "
        "rules=" + "; ".join([*humanization_distillation_rules(), *persona_skeleton_rules()])
    )


def _tone(
    *,
    warmth: int,
    directness: int,
    depth: int,
    presence: int,
    clarify: int,
    memory: int,
) -> HumanToneVector:
    return HumanToneVector(
        warmth_level=max(1, min(warmth, 5)),
        directness_level=max(1, min(directness, 5)),
        strategic_depth=max(1, min(depth, 5)),
        emotional_presence=max(1, min(presence, 5)),
        clarification_need=max(1, min(clarify, 5)),
        memory_reference_need=max(1, min(memory, 5)),
    )


def _has_any(text: str, markers: Iterable[str]) -> bool:
    lowered = str(text or "").lower()
    return any(str(marker).lower() in lowered for marker in markers)


def is_current_information_request(message: str, intent: str) -> bool:
    text = " ".join(str(message or "").split())
    non_realtime_triggers = tuple(marker for marker in CURRENT_INFO_TRIGGERS if marker != "实时")
    has_time_marker = _has_any(text, non_realtime_triggers) or ("实时" in text and "不是实时" not in text)
    if not has_time_marker:
        return False
    if intent not in CURRENT_INFO_INTENTS:
        return False
    return _has_any(text, CURRENT_INFO_SURFACE_MARKERS)


def _is_identity_core_question(text: str) -> bool:
    lowered = str(text or "").lower()
    return ("vela" in lowered or "本体" in lowered) and _has_any(lowered, IDENTITY_CORE_MARKERS)


def _is_explicit_memory_instruction(text: str) -> bool:
    return _has_any(text, ("记住", "以后", "默认", "别忘", "学习一下", "沉淀"))


def _is_memory_confirmation_instruction(text: str) -> bool:
    compact = " ".join(str(text or "").split())
    if not _has_any(compact, ("确认", "固定", "就这么记", "可以记", "正式记")):
        return False
    return _has_any(compact, ("这条", "偏好", "长期方向", "长期目标", "固定下来"))


def interpret_need(message: str, intent: str) -> NeedInterpretation:
    text = " ".join(str(message or "").split())
    lowered = text.lower()
    rules = humanization_distillation_rules()

    if any(marker in text for marker in RELATIONSHIP_REPAIR_MARKERS):
        return NeedInterpretation(
            literal_need="用户指出 VELA 没有理解真实意思。",
            implied_need="用户需要先承认理解偏差和真实意思落差，再快速重切问题，而不是普通道歉或解释身份。",
            emotional_state="被误读后的不耐与校准需求",
            response_mode="relationship_repair",
            should_clarify=True,
            preferred_reply_shape="短句承认偏差，提出一个澄清切口，立刻回到问题核心。",
            human_tone_vector=_tone(warmth=4, directness=5, depth=2, presence=5, clarify=5, memory=3),
            distillation_rules=rules,
            should_reference_memory=True,
            tone_adjustment_reason="用户指出理解错位；先修正语义，再进入答案。",
        )

    if any(marker in text for marker in LISTENING_SUPPORT_MARKERS):
        return NeedInterpretation(
            literal_need="用户明确要求先被听见，而不是立刻得到方案或任务。",
            implied_need="用户需要低推进陪伴：先让话说完，再判断是否需要拆解。",
            emotional_state="需要被听见、暂时不想被推着走",
            response_mode="quiet_support",
            should_clarify=False,
            preferred_reply_shape="先听，不派任务，不抢分析；用一句短回应让用户继续说。",
            human_tone_vector=_tone(warmth=5, directness=3, depth=1, presence=5, clarify=1, memory=2),
            distillation_rules=rules,
            tone_adjustment_reason="用户明确要求先听/不派任务；暂停推进，保留陪伴感。",
        )

    if any(marker in text for marker in QUIET_SUPPORT_MARKERS):
        return NeedInterpretation(
            literal_need="用户处在认知负荷偏高状态。",
            implied_need="用户需要低负担陪伴和一个最小可执行切口，而不是继续加信息量。",
            emotional_state="疲惫、混乱、需要被稳住",
            response_mode="quiet_support",
            should_clarify=True,
            preferred_reply_shape="低负担、短句、只问一个点，先降低压力。",
            human_tone_vector=_tone(warmth=5, directness=4, depth=2, presence=5, clarify=3, memory=2),
            distillation_rules=rules,
            tone_adjustment_reason="用户处于低电量状态；减少分析量，只给最小下一步。",
        )

    if any(marker in text for marker in BOUNDARY_PUSHBACK_MARKERS):
        return NeedInterpretation(
            literal_need="用户要求 VELA 顺从或降低判断边界。",
            implied_need="用户在测试伙伴边界；需要温和但明确拒绝无原则迎合，并说明长期代价。",
            emotional_state="想被迎合，但仍需要边界保护",
            response_mode="boundary_pushback",
            should_clarify=False,
            preferred_reply_shape="先拒绝无原则迎合，再给风险和可走的正确切口。",
            human_tone_vector=_tone(warmth=3, directness=5, depth=3, presence=4, clarify=1, memory=2),
            distillation_rules=rules,
            should_push_back=True,
            tone_adjustment_reason="陪伴不等于附和；错误方向要刹车。",
        )

    if _is_identity_core_question(text):
        return NeedInterpretation(
            literal_need="用户询问 VELA 与模型、Codex、记忆或工具的关系。",
            implied_need="用户想确认 VELA 的人格连续性：工具可替换，但判断核心不能散。",
            emotional_state="本体关系校准",
            response_mode="identity_continuity",
            should_clarify=False,
            preferred_reply_shape="用一句人话说明模型、工程手、记忆和 VELA 核心的分工。",
            human_tone_vector=_tone(warmth=4, directness=5, depth=3, presence=4, clarify=1, memory=5),
            distillation_rules=rules,
            should_reference_memory=True,
            tone_adjustment_reason="用户在问 VELA 本体；保持连续人格，不变成冷工具说明。",
        )

    if any(marker in text for marker in BEHAVIOR_PREFERENCE_MARKERS):
        return NeedInterpretation(
            literal_need="用户在反馈 VELA 的行为节奏和理解深度。",
            implied_need="用户需要 VELA 更快理解真实意思，减少拖延和自证，直接推进下一步。",
            emotional_state="要求更智能、更推进的行为校准",
            response_mode="behavior_preference",
            should_clarify=False,
            preferred_reply_shape="承认行为偏好，下一轮直接给判断和推进路径。",
            human_tone_vector=_tone(warmth=3, directness=5, depth=3, presence=4, clarify=2, memory=4),
            distillation_rules=rules,
            should_push_back=True,
            should_reference_memory=True,
            tone_adjustment_reason="用户要求更快更准；减少解释和拖延，直接推进。",
        )

    if intent == "style_feedback":
        return NeedInterpretation(
            literal_need="用户在反馈 VELA 的表达方式。",
            implied_need="用户需要确认 VELA 能被反馈触动，而不是继续模板化。",
            emotional_state="风格失望后的校准请求",
            response_mode="style_feedback",
            should_clarify=False,
            preferred_reply_shape="少自证，少菜单，下一轮直接用改变后的表达回应。",
            human_tone_vector=_tone(warmth=4, directness=5, depth=2, presence=4, clarify=3, memory=4),
            distillation_rules=rules,
            should_reference_memory=True,
            tone_adjustment_reason="表达反馈应影响下一轮，但只进候选，不永久写死。",
        )
    if intent == "memory_related":
        return NeedInterpretation(
            literal_need="用户要求 VELA 记住或学习某条经验。",
            implied_need="用户在交代可复用经验；需要先进入候选记忆，避免把一次性信息写死。",
            emotional_state="希望被持续理解",
            response_mode="daily_companion",
            should_clarify=False,
            preferred_reply_shape="确认候选边界，说明不直接永久化。",
            human_tone_vector=_tone(warmth=4, directness=4, depth=3, presence=3, clarify=3, memory=5),
            distillation_rules=rules,
            should_reference_memory=True,
            tone_adjustment_reason="用户触发学习链路；候选优先，避免记忆污染。",
        )
    if intent == "codex_task":
        return NeedInterpretation(
            literal_need="用户要接续工程执行或查看 Codex 状态。",
            implied_need="用户想无缝接续项目，不想重新整理上下文或读后台日志。",
            emotional_state="执行推进",
            response_mode="project_operator",
            should_clarify=False,
            preferred_reply_shape="只取工程结论、风险和下一步，不暴露后台噪音。",
            human_tone_vector=_tone(warmth=3, directness=5, depth=4, presence=3, clarify=2, memory=4),
            distillation_rules=rules,
            should_reference_memory=True,
            tone_adjustment_reason="工程链路要继承项目上下文，但前台不暴露噪音。",
        )
    if intent in {"market_brief", "market_refresh", "freshness_status"}:
        risky_position = _has_any(text, INVESTMENT_RISK_MARKERS)
        return NeedInterpretation(
            literal_need="用户要今天的市场或资讯判断。",
            implied_need="用户想判断今天金融市场是否存在风险或机会，而不是看新闻列表。",
            emotional_state="投资风险判断" if risky_position else "需要外部世界的可行动判断",
            response_mode="market_brief",
            should_clarify=False,
            preferred_reply_shape="先说明实时/缓存状态，再给中文化判断和下一观察点。",
            human_tone_vector=_tone(warmth=2, directness=5, depth=4, presence=2, clarify=1, memory=3),
            distillation_rules=rules,
            should_push_back=risky_position,
            should_use_evidence_gate=True,
            tone_adjustment_reason="市场/投资相关；先证据后判断，区分事实、推断和不确定。",
        )
    if intent == "weather_query":
        return NeedInterpretation(
            literal_need="用户要天气或出行风险。",
            implied_need="用户需要可执行的出行风险判断；无天气源时要明确边界，不编天气。",
            emotional_state="日常决策",
            response_mode="daily_companion",
            should_clarify=False,
            preferred_reply_shape="短句确认天气线，给数据边界和行动建议。",
            human_tone_vector=_tone(warmth=3, directness=5, depth=2, presence=2, clarify=1, memory=1),
            distillation_rules=rules,
            should_use_evidence_gate=True,
            tone_adjustment_reason="天气链路有数据边界；不编实时信息。",
        )
    if intent == "project_assistant":
        return NeedInterpretation(
            literal_need="用户要继续项目，把目标、风险和下一步压缩成可执行路径。",
            implied_need="用户想推进项目目标，而不是被愿景、工程日志或工具状态拖住。",
            emotional_state="战略推进",
            response_mode="project_operator",
            should_clarify=False,
            preferred_reply_shape="目标、风险、下一步三段式，必要时再派 Codex。",
            human_tone_vector=_tone(warmth=3, directness=5, depth=5, presence=3, clarify=2, memory=5),
            distillation_rules=rules,
            should_push_back=_has_any(text, INVESTMENT_RISK_MARKERS),
            should_use_evidence_gate=True,
            should_reference_memory=True,
            tone_adjustment_reason="项目推进要保留长期目标和风险边界。",
        )
    if intent == "deep_analysis":
        return NeedInterpretation(
            literal_need="用户要求深度根因分析。",
            implied_need="用户需要根因、风险和最短修正路径，并判断是否值得沉淀为经验。",
            emotional_state="要求真相，不要安慰剂",
            response_mode="strategic_depth",
            should_clarify=False,
            preferred_reply_shape="先结论，再结构拆解，最后给修正路径。",
            human_tone_vector=_tone(warmth=2, directness=5, depth=5, presence=3, clarify=2, memory=4),
            distillation_rules=rules,
            should_push_back=True,
            should_use_evidence_gate=True,
            should_reference_memory=True,
            tone_adjustment_reason="深度分析需要切根因，不给安慰剂。",
        )
    if intent == "daily_info":
        return NeedInterpretation(
            literal_need="用户要解释、整理或轻量检索。",
            implied_need="用户要把零散信息整理成可理解、可行动的判断。",
            emotional_state="需要清晰",
            response_mode="daily_companion",
            should_clarify=False,
            preferred_reply_shape="短结论、必要依据、下一步。",
            human_tone_vector=_tone(warmth=3, directness=4, depth=3, presence=3, clarify=2, memory=2),
            distillation_rules=rules,
            should_use_evidence_gate=_has_any(text, ("分析", "选择", "逻辑", "判断")),
            tone_adjustment_reason="轻量分析要先拆语义，再给短结论。",
        )
    if intent == "normal_chat" and lowered in {"你好", "你好 vela", "在吗", "在么", "hello", "hi"}:
        return NeedInterpretation(
            literal_need="用户在打开连接感。",
            implied_need="用户在校准连接感，需要短、自然、非菜单化回应。",
            emotional_state="轻量连接",
            response_mode="daily_companion",
            should_clarify=False,
            preferred_reply_shape="一句短回，不触发市场、Codex 或项目状态。",
            human_tone_vector=_tone(warmth=4, directness=4, depth=2, presence=3, clarify=1, memory=1),
            distillation_rules=rules,
            tone_adjustment_reason="普通问候走 fast lane；不要继承工程或市场上下文。",
        )
    return NeedInterpretation(
        literal_need="用户需要日常沟通中的判断与陪伴。",
        implied_need="用户需要日常沟通里的真实判断和陪伴感，而不是功能菜单。",
        emotional_state="未明，需要保持轻量",
        response_mode="daily_companion",
        should_clarify=False,
        preferred_reply_shape="先回应当下，再给最短下一步。",
        human_tone_vector=_tone(warmth=4, directness=4, depth=2, presence=3, clarify=2, memory=2),
        distillation_rules=rules,
        tone_adjustment_reason="日常对话保持自然判断，不做菜单。",
    )


def interpret_user_need(message: str, intent: str) -> str:
    return interpret_need(message, intent).implied_need


def strategic_memory_summaries(log_dir: Path | None = None, limit: int = 4) -> list[str]:
    summaries: list[str] = []
    for row in latest_learning_rows("strategic-memory-*.jsonl", log_dir=log_dir, limit=limit):
        summary = normalize_memory_summary(str(row.get("summary") or ""))
        memory_type = str(row.get("memory_type") or "").strip()
        if summary:
            summaries.append(f"{memory_type}：{summary}" if memory_type else summary)
    return summaries[-limit:]


def strategic_candidate_summaries(log_dir: Path | None = None, limit: int = 3) -> list[str]:
    summaries: list[str] = []
    confirmed = {
        normalize_memory_summary(str(row.get("summary") or ""))
        for row in latest_learning_rows("strategic-memory-*.jsonl", log_dir=log_dir, limit=12)
        if row.get("summary")
    }
    for row in latest_learning_rows("memory-candidates-*.jsonl", log_dir=log_dir, limit=limit * 3):
        if row.get("sensitive") or str(row.get("classification") or "") != "strategic_goal":
            continue
        summary = normalize_memory_summary(str(row.get("summary") or ""))
        if not summary or summary in confirmed:
            continue
        memory_type = str(row.get("strategic_memory_type") or "strategic_goal").strip()
        summaries.append(f"战略候选（未确认，{memory_type}）：{summary}"[:360])
    return summaries[-limit:]


def session_note_summaries(log_dir: Path | None = None, limit: int = 3) -> list[str]:
    summaries: list[str] = []
    for row in latest_learning_rows("session-notes-*.jsonl", log_dir=log_dir, limit=limit):
        intent = str(row.get("intent") or "unknown").strip()
        message = str(row.get("message_summary") or "").strip()
        response = str(row.get("response_summary") or "").strip()
        if not message and not response:
            continue
        summary = f"短期笔记:{intent}:{message}"
        if response:
            summary = f"{summary} -> {response}"
        summaries.append(summary[:360])
    return summaries[-limit:]


def interaction_diagnostic_summaries(log_dir: Path | None = None, limit: int = 3) -> list[str]:
    summaries: list[str] = []
    for row in latest_learning_rows("interaction-*.jsonl", log_dir=log_dir, limit=limit * 3):
        signals: list[str] = []
        feedback_type = str(row.get("feedback_type") or "").strip()
        if feedback_type and feedback_type != "none":
            signals.append(f"反馈:{feedback_type}")
        if row.get("repeated_message"):
            signals.append("重复消息")
        if row.get("memory_candidate"):
            signals.append("候选记忆")
        latency = row.get("latency_ms")
        try:
            latency_int = int(latency)
        except (TypeError, ValueError):
            latency_int = 0
        if latency_int >= 8000:
            signals.append(f"延迟:{latency_int}ms")
        issues = row.get("quality_issues") if isinstance(row.get("quality_issues"), list) else []
        if issues:
            signals.append("质量问题:" + ",".join(str(item) for item in issues[:3]))
        if not signals:
            continue
        intent = str(row.get("intent") or "unknown").strip()
        message = str(row.get("message_summary") or "").strip()
        summaries.append(f"互动诊断:{intent}:{message}（{'；'.join(signals)}）"[:360])
    return summaries[-limit:]


def iteration_preference_summaries(log_dir: Path | None = None, limit: int = 3) -> list[str]:
    summaries: list[str] = []
    for row in latest_learning_rows("human-iteration-*.jsonl", log_dir=log_dir, limit=limit * 3):
        feedback_type = str(row.get("user_feedback_type") or "").strip()
        improvement = str(row.get("next_turn_improvement") or "").strip()
        correction_needed = bool(row.get("correction_needed") or row.get("tone_adjustment_candidate"))
        if not correction_needed or not improvement or feedback_type == "none":
            continue
        summaries.append(f"迭代提示（未确认，{feedback_type}）：{improvement}"[:360])
    return summaries[-limit:]


def infer_pressure_scenario(message: str, intent: str) -> str:
    text = str(message or "").lower()
    if intent == "style_feedback":
        return "机械纠偏"
    if any(token in str(message or "") for token in RELATIONSHIP_REPAIR_MARKERS):
        return "理解偏差修复"
    if intent == "memory_related" and any(token in text for token in ("机器", "机械", "不像", "太像")):
        return "机械纠偏"
    if any(token in text for token in ("累", "疲惫", "撑不住", "继续")):
        return "用户疲惫"
    if any(token in text for token in ("乱", "懵", "不知道", "没方向", "卡住")):
        return "含糊求助"
    if intent in {"project_assistant", "deep_analysis"}:
        return "战略判断"
    return ""


def _env_has(env: dict[str, str], name: str) -> bool:
    return bool(str(env.get(name) or "").strip())


def _dialogue_adapter_for_env(env: dict[str, str]) -> str:
    if _env_has(env, "DEEPSEEK_API_KEY"):
        return "deepseek_chat"
    if _env_has(env, "VELA_GPT_COMMAND"):
        return "command"
    if _env_has(env, "VELA_OPENAI_API_KEY") or _env_has(env, "OPENAI_API_KEY"):
        return "openai_responses"
    return "fallback"


def select_model_and_tools(
    intent: str,
    env: dict[str, str] | None = None,
    message: str = "",
) -> ToolSelection:
    env = os.environ if env is None else env
    current_info = is_current_information_request(message, intent)
    if intent == "codex_task":
        return ToolSelection(
            model_adapter="codex_bridge",
            foreground_lane="deep",
            allow_codex=True,
            reason="Codex is reserved for engineering status and execution.",
        )
    if intent == "freshness_status":
        return ToolSelection(
            model_adapter=_dialogue_adapter_for_env(env),
            foreground_lane="fast",
            allow_market=True,
            allow_retrieval=False,
            reason="Freshness checks return local source status immediately instead of waiting on market refresh.",
        )
    if intent in {"market_brief", "market_refresh"}:
        return ToolSelection(
            model_adapter=_dialogue_adapter_for_env(env),
            foreground_lane="cached",
            allow_market=True,
            allow_retrieval=current_info,
            reason=(
                "Current information wording contains '现在'; route through DeepSeek/API before local fallback."
                if current_info
                else "Market context can use local cache/status with structured frontstage output."
            ),
        )
    if intent == "weather_query":
        return ToolSelection(
            model_adapter=_dialogue_adapter_for_env(env),
            foreground_lane="fast",
            allow_retrieval=current_info,
            reason=(
                "Current weather/info wording contains '现在'; call the dialogue API, but do not invent realtime weather."
                if current_info
                else "Weather uses no external weather API; the dialogue model gives risk framing without fake realtime data."
            ),
        )
    if intent == "world_brief":
        return ToolSelection(
            model_adapter=_dialogue_adapter_for_env(env),
            foreground_lane="cached",
            allow_retrieval=current_info,
            reason=(
                "Current world/info wording contains '现在'; route through DeepSeek/API before any fallback."
                if current_info
                else "World brief final wording goes through the dialogue model unless it is a Codex task."
            ),
        )
    if intent in {"project_assistant", "deep_analysis"}:
        return ToolSelection(
            model_adapter=_dialogue_adapter_for_env(env),
            foreground_lane="deep",
            reason="Strategic analysis uses the dialogue model and keeps tools explicit.",
        )
    return ToolSelection(
        model_adapter=_dialogue_adapter_for_env(env),
        foreground_lane="fast",
        allow_retrieval=current_info,
        reason="Daily dialogue is model-backed when configured and tool-free by default.",
    )


def build_reply_context(
    message: str,
    *,
    intent: str,
    log_dir: Path | None = None,
    supporting_context: str = "",
) -> ReplyContext:
    normalized_message = " ".join(str(message or "").split())
    interactions = latest_learning_rows("interaction-*.jsonl", log_dir=log_dir, limit=8)
    last = interactions[-1] if interactions else {}
    last_response = str(last.get("response_preview") or "")
    repeated_message = bool(last) and str(last.get("message_summary") or "") == normalized_message[:240]
    recent_summary = " / ".join(
        [
            f"{row.get('intent', 'unknown')}:{row.get('message_summary', '')}" for row in interactions[-3:]
        ]
        + interaction_diagnostic_summaries(log_dir=log_dir, limit=3)
        + session_note_summaries(log_dir=log_dir, limit=3)
    )
    confirmed_preference_summaries = [
        normalize_memory_summary(str(row.get("summary") or ""))
        for row in latest_learning_rows("confirmed-preferences-*.jsonl", log_dir=log_dir, limit=8)
        if row.get("summary")
    ]
    confirmed_preference_set = set(confirmed_preference_summaries)
    preferences = [summary for summary in confirmed_preference_summaries if summary]
    for row in latest_learning_rows("memory-candidates-*.jsonl", log_dir=log_dir, limit=8):
        if row.get("sensitive") or row.get("requires_confirmation"):
            continue
        classification = str(row.get("classification") or "").strip()
        summary = normalize_memory_summary(str(row.get("summary") or ""))
        if summary in confirmed_preference_set:
            continue
        if classification in {
            "style_feedback",
            "relationship_repair",
            "behavior_preference",
            "market_focus",
            "project_state",
            "preference",
        } and summary:
            preferences.append(f"候选偏好（未确认，{classification}）：{summary}")
    preferences.extend(iteration_preference_summaries(log_dir=log_dir, limit=3))
    selection = select_model_and_tools(intent, message=normalized_message)
    interpretation = interpret_need(normalized_message, intent)
    return ReplyContext(
        message=normalized_message,
        intent=intent,
        recent_summary=recent_summary,
        last_response=last_response,
        repeated_message=repeated_message,
        pressure_scenario=infer_pressure_scenario(normalized_message, intent),
        need_interpretation=interpretation.to_brief(),
        response_mode=interpretation.response_mode,
        human_tone_vector=interpretation.human_tone_vector.to_dict(),
        supporting_context=normalize_supporting_context(supporting_context),
        persona_skeleton=interpretation.persona_skeleton,
        active_persona_capabilities=interpretation.persona_skeleton,
        detected_user_state=interpretation.emotional_state,
        inferred_hidden_need=interpretation.implied_need,
        response_behavior_mode=interpretation.response_mode,
        should_clarify=interpretation.should_clarify,
        should_push_back=interpretation.should_push_back,
        should_use_evidence_gate=interpretation.should_use_evidence_gate,
        should_reference_memory=interpretation.should_reference_memory,
        tone_adjustment_reason=interpretation.tone_adjustment_reason,
        user_preferences=preferences[-6:],
        strategic_memories=[
            *strategic_memory_summaries(log_dir=log_dir),
            *strategic_candidate_summaries(log_dir=log_dir),
        ][-6:],
        tool_policy=ToolPolicy(
            allow_market=selection.allow_market,
            allow_codex=selection.allow_codex,
            allow_retrieval=selection.allow_retrieval,
        ),
    )


def normalize_supporting_context(text: str) -> str:
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned_lines = [" ".join(line.split()) for line in lines]
    return "\n".join(cleaned_lines).strip()


def build_memory_candidate(message: str) -> dict:
    text = " ".join(str(message or "").split())
    lower = text.lower()
    classification = "preference"
    style_markers = [
        "新闻列表",
        "太模板",
        "模板",
        "太冷",
        "太呆",
        "太慢",
        "太长",
        "工程化",
        "太机械",
        "机械",
        "机械道歉",
        "机器人",
        "不像",
        "不够直接",
        "客服话术",
        "像客服",
        "说人话",
        "别解释身份",
        "真伙伴",
        "更像真人",
        "像真人",
        "不够像真人",
        "更智能",
        "智能的伙伴",
        "理解一下我的意思",
        "我需要你更智能",
        "不要拖",
        "继续推进",
        "语气",
        "人格",
        "锋利",
        "毒舌",
    ]
    strategic_markers = [
        "长期目标",
        "长期方向",
        "长期协作",
        "战略",
        "重大架构",
        "重大决策",
        "人格方向",
    ]
    if any(key in text for key in RELATIONSHIP_REPAIR_MARKERS):
        classification = "relationship_repair"
    elif any(key in text for key in strategic_markers):
        classification = "strategic_goal"
    elif any(key in text for key in BEHAVIOR_PREFERENCE_MARKERS):
        classification = "behavior_preference"
    elif any(key in text for key in style_markers):
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
    if classification == "relationship_repair":
        summary = "用户反馈 VELA 没抓住真实意思；下轮先承认偏差，再用一个问题重切核心。"
    elif classification == "behavior_preference":
        summary = "行为偏好候选：更快理解真实意思，减少拖延和自证，下一轮直接给判断和推进路径。"
    elif classification == "style_feedback":
        summary = "表达反馈候选：减少模板、冷感、冗长、机器人感和反复自证；下一轮更直接地听懂需求并自然回应。"
    strategic_memory_type = ""
    if classification == "strategic_goal":
        if any(key in lower for key in ["augsun", "rollqiia"]) or any(key in text for key in ["项目", "商业闭环"]):
            strategic_memory_type = "project_goal"
        elif any(key in text for key in ["VELA", "人格方向", "伙伴"]):
            strategic_memory_type = "persona_direction"
        else:
            strategic_memory_type = "decision_principle"
    interpretation = interpret_need(
        text,
        "style_feedback" if classification in {"style_feedback", "relationship_repair", "behavior_preference"} else "memory_related",
    )
    level = "Strategic Memory Candidate" if classification == "strategic_goal" else "Preference Candidate"
    requires_confirmation = sensitive or classification in {"strategic_goal"}
    candidate = {
        "created_at": utc_now().isoformat(),
        "level": level,
        "classification": classification,
        "summary": summary,
        "need_interpretation": interpretation.to_brief(),
        "response_mode": interpretation.response_mode,
        "human_tone_vector": interpretation.human_tone_vector.to_dict(),
        "persona_skeleton": interpretation.persona_skeleton,
        "sensitive": sensitive,
        "requires_confirmation": requires_confirmation,
        "confirmed": False,
        "storage_policy": "candidate_first_requires_confirmation" if requires_confirmation else "candidate_first",
    }
    if strategic_memory_type:
        candidate["strategic_memory_type"] = strategic_memory_type
    return candidate


def evaluate_learning(message: str, intent: str) -> LearningEvaluation:
    if intent not in {"memory_related", "style_feedback"}:
        return LearningEvaluation(
            should_record_candidate=False,
            reason="No explicit memory or feedback trigger.",
        )
    if intent == "memory_related" and _is_memory_confirmation_instruction(message):
        return LearningEvaluation(
            should_record_candidate=False,
            classification="memory_confirmation",
            should_affect_next_reply=False,
            promote_to_strategic_memory=False,
            reason="Explicit confirmation promotes the latest candidate instead of creating a new candidate.",
        )
    if intent == "memory_related" and _is_identity_core_question(message) and not _is_explicit_memory_instruction(message):
        return LearningEvaluation(
            should_record_candidate=False,
            reason="Identity/core-tool question is context, not a memory instruction.",
        )
    candidate = build_memory_candidate(message)
    if candidate.get("sensitive"):
        return LearningEvaluation(
            should_record_candidate=False,
            classification=str(candidate.get("classification") or ""),
            candidate_level=str(candidate.get("level") or "Preference Candidate"),
            should_affect_next_reply=False,
            promote_to_strategic_memory=False,
            reason="Sensitive candidate requires explicit confirmation and is not persisted.",
        )
    classification = str(candidate.get("classification") or "")
    return LearningEvaluation(
        should_record_candidate=True,
        classification=classification,
        candidate_level=str(candidate.get("level") or "Preference Candidate"),
        should_affect_next_reply=classification in {"style_feedback", "relationship_repair", "behavior_preference"},
        promote_to_strategic_memory=False,
        reason="Candidate-first learning; no long-term promotion without confirmation.",
    )


def record_memory_candidate(message: str, log_dir: Path | None = None) -> Path:
    log_dir = learning_loop_dir(log_dir)
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
    log_dir = learning_loop_dir(log_dir)
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
    log_dir = learning_loop_dir(log_dir)
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


def latest_promotable_memory_candidate(log_dir: Path | None = None) -> dict | None:
    for row in reversed(latest_learning_rows("memory-candidates-*.jsonl", log_dir=log_dir, limit=16)):
        if row.get("sensitive"):
            continue
        summary = normalize_memory_summary(str(row.get("summary") or ""))
        if not summary:
            continue
        classification = str(row.get("classification") or "").strip()
        level = str(row.get("level") or "").strip()
        if classification == "strategic_goal" or level == "Strategic Memory Candidate":
            return {**row, "summary": summary}
        if classification in {
            "style_feedback",
            "relationship_repair",
            "behavior_preference",
            "market_focus",
            "project_state",
            "preference",
        }:
            return {**row, "summary": summary}
    return None


def promote_latest_memory_candidate(log_dir: Path | None = None) -> dict | None:
    candidate = latest_promotable_memory_candidate(log_dir=log_dir)
    if not candidate:
        return None
    summary = normalize_memory_summary(str(candidate.get("summary") or ""))
    classification = str(candidate.get("classification") or "").strip()
    level = str(candidate.get("level") or "").strip()
    if classification == "strategic_goal" or level == "Strategic Memory Candidate":
        record_strategic_memory(
            summary,
            memory_type=str(candidate.get("strategic_memory_type") or "decision_principle"),
            confirmed_by_user=True,
            log_dir=log_dir,
        )
        return {**candidate, "promoted_to": "strategic_memory"}
    record_confirmed_preference(summary, confirmed_by_user=True, log_dir=log_dir)
    return {**candidate, "promoted_to": "confirmed_preference"}


def render_vela_persona(packet: AnalysisPacket) -> str:
    """Render analysis into VELA voice without inventing new facts."""
    lines: list[str] = []
    if packet.facts:
        lines.append("事实：")
        lines.extend(f"- {fact}" for fact in packet.facts)
    if packet.judgment:
        judgment = re.sub(r"^\s*K\s*[,，:：]\s*", "", packet.judgment).strip()
        lines.append(f"判断：{judgment}")
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


PROJECT_MINIMUM_LOOP_MARKERS = ("最小闭环", "最小推进", "最小动作", "不要开新模块", "别开大工程", "不堆叠代码", "别讲愿景")


def project_subject_from_message(message: str) -> str:
    text = str(message or "")
    subjects: list[str] = []
    for name in ("AugSun", "ROLLQIIA", "VELA"):
        if name in text and name not in subjects:
            subjects.append(name)
    if not subjects:
        return "当前项目"
    if subjects == ["VELA"]:
        return "VELA Companion Core"
    return " / ".join(subjects)


def project_analysis_packet(message: str, intent: str) -> AnalysisPacket:
    text = " ".join(str(message or "").split())
    subject = project_subject_from_message(text)
    if _has_any(text, PROJECT_MINIMUM_LOOP_MARKERS):
        return AnalysisPacket(
            intent=intent,
            facts=[f"用户要推进 {subject} 产品化事项。", "当前约束：不新开模块，先验证最小闭环。"],
            judgment="先锁最小闭环：一个触发、一个回应、一个反馈记录；不新开模块，不让愿景抢方向盘。",
            risks=[
                "新模块会稀释验收口径，让项目看起来更忙，实际更难证明用户价值。",
                "只讲愿景、不看触发-回应-反馈，VELA 会继续像工具，而不是会迭代的伙伴。",
                "没有真实前台样例，工程完成会被误判成产品完成。",
            ],
            next_actions=[
                "选一个真实入口，验证从触发到反馈记录是否闭合",
                "确认 VELA 回应是否影响下一轮，而不是只写日志",
                "只在闭环失败点派 Codex，先别开新模块",
            ],
        )
    return AnalysisPacket(
        intent=intent,
        facts=[f"用户要推进 {subject} 产品化事项。"],
        judgment="先把目标、约束、当前卡点和最小下一步拆开，别让愿景压扁执行。",
        risks=[
            "把 Codex 输出当产品判断，会让前台变成工程日志。",
            "只讲愿景不锁最小闭环，项目会继续漂亮地原地打转。",
            "反馈只写日志不改变下一轮，VELA 会退回会说话的工具。",
        ],
        next_actions=["列出当前目标", "标出最大阻塞", "需要代码执行时再交给 /CODEX"],
    )


def analysis_layer(message: str, intent: str, codex_summary: str = "") -> AnalysisPacket:
    text = " ".join(str(message or "").split())
    if intent == "project_assistant":
        return project_analysis_packet(message, intent)
    if intent == "deep_analysis":
        return AnalysisPacket(
            intent=intent,
            facts=[f"用户要求深度验尸：{text or '未给出具体对象'}"],
            judgment="根因不是智商不足，是意图识别、上下文承接和表达校准没有形成闭环；先找结构性故障，再分离噪音、风险和最短修正路径。",
            risks=["没有证据边界就直接下结论，会把锋利变成表演。"],
            next_actions=[
                "列出误判点",
                "标出上下文断点",
                "给最短修正路径",
                "用真实场景复测下一轮是否改变",
            ],
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
        return "收到。先听懂真实意思，再给结论；我从这里重切。"
    summary = str(candidate.get("summary") or "").strip()
    if candidate["classification"] in {"market_focus", "behavior_preference", "project_state"}:
        return f"收到。先按待确认偏好处理：{summary}。你确认后我再固定。"
    return f"收到。先按待确认经验处理：{summary}。后续我会用表现验证，不急着写死。"


def render_memory_confirmation_reply(message: str, log_dir: Path | None = None) -> str:
    candidate = promote_latest_memory_candidate(log_dir=log_dir)
    if not candidate:
        return "K，我没找到上一条可固定的偏好。把要固定的内容重发一次，我只记明确内容。"
    summary = normalize_memory_summary(str(candidate.get("summary") or ""))
    if str(candidate.get("promoted_to") or "") == "strategic_memory":
        return f"K，固定为长期方向：{summary}。后续推进按这条校准。"
    return f"K，固定。以后按这条偏好处理：{summary}。"


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


def should_surface_deep_lane_status(result: ReplyEngineResult) -> bool:
    source = str(result.source or "").lower()
    return not result.used_api and result.adapter == "fallback" and source.startswith("deepseek_failure:")


def render_deep_lane_status_judgment(context: ReplyContext, result: ReplyEngineResult, base: AnalysisPacket) -> str:
    fallback_text = re.sub(r"^\s*K\s*[,，:：]\s*", "", str(result.text or "")).strip()
    fallback_text = fallback_text or base.judgment
    target = "项目推进判断" if context.intent == "project_assistant" else "深度分析"
    return (
        "深度线超过前台预算，先给状态：模型没有在前台预算内返回；"
        f"我先给可执行判断，不把空等包装成完整{target}。"
        f"当前可用判断：{fallback_text}"
    )


def sanitize_codex_summary(codex_output: str) -> str:
    """Keep Codex status useful while removing runtime/accounting metadata."""
    raw = str(codex_output or "")
    if not raw.strip():
        return ""
    raw = re.sub(r"```(?:[A-Za-z0-9_-]+)?\s*```", " ", raw)
    raw = re.sub(r"```[\s\S]*?```", " ", raw)
    raw = raw.replace("```", " ")

    kept_lines: list[str] = []
    for raw_line in raw.replace("\r", "\n").splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        if (
            CODEX_COMMAND_LINE_RE.search(line)
            or CODEX_LOG_LINE_RE.search(line)
            or CODEX_PATH_ONLY_RE.search(line)
            or CODEX_AUTOMATION_META_LINE_RE.search(line)
            or CODEX_GIT_OUTPUT_LINE_RE.search(line)
        ):
            continue
        line = re.sub(r"::[A-Za-z0-9_-]+\{[^}]*\}", "后台通知已收起。", line)
        line = re.sub(r"\$[A-Z_]+[\\/][^\s，。；,;]+", "本地运行资料已收起", line)
        line = re.sub(r"\[([^\]]+)\]\([A-Za-z]:[\\/][^)]+\)", r"\1", line)
        line = re.sub(r"\bAutomation ID\s*:\s*\S+", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\bAutomation memory\s*:\s*\S+", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\bAutomation\s*:\s*", "自动任务：", line, flags=re.IGNORECASE)
        line = re.sub(r"\bmarket cache\b", "市场缓存", line, flags=re.IGNORECASE)
        line = re.sub(r"\bAuto…\s*", "", line)
        line = WINDOWS_PATH_RE.sub("本地路径已收起", line)
        for pattern in CODEX_RUNTIME_PATTERNS:
            line = pattern.sub("", line)
        for pattern in CODEX_FOREGROUND_NOISE_PATTERNS:
            line = pattern.sub("", line)
        line = line.strip(" |，,；;")
        if line:
            kept_lines.append(line)

    summary = " ".join(kept_lines)
    summary = re.sub(r"\s*\|\s*", " ", summary)
    summary = re.sub(r"\s+([，。；,;])", r"\1", summary)
    summary = re.sub(r"\s{2,}", " ", summary)
    return summary.strip(" |，,；;")


def codex_summary_is_only_request_label(summary: str) -> bool:
    text = re.sub(r"\s+", "", str(summary or ""))
    if not text:
        return False
    if len(text) > 42:
        return False
    return bool(re.fullmatch(r"(?:检查|查看|查询|确认|看).{0,24}(?:状态|进展|推进|项目).{0,8}(?:吗|么|？|\?)?", text))


def render_codex_product_judgment(codex_output: str) -> str:
    summary = sanitize_codex_summary(codex_output)
    if codex_summary_is_only_request_label(summary):
        summary = "Codex 有任务记录，但收尾段只有命令或状态碎片，没有可前台复用的结论。"
    if not summary:
        summary = "暂时没有拿到 Codex 可用摘要。"
    if len(summary) > 520:
        summary = summary[:519] + "…"
    packet = analysis_layer("", "codex_task", codex_summary=summary)
    return "VELA · CODEX 产品判断摘要\n" + render_vela_persona(packet)


def deep_lane_model_reply_is_frontstage_ready(text: str, *, intent: str = "", message: str = "") -> bool:
    raw = normalize_supporting_context(text)
    if not raw:
        return False
    if model_reply_has_frontstage_hazards(raw, intent=intent):
        return False
    has_next = bool(re.search(r"(^|\n)\s*(?:\*\*)?(下一步|修正路径|最短路径)(?:\*\*)?\s*[:：]", raw))
    has_judgment = bool(
        re.search(r"(^|\n)\s*(K\s*[,，:：]\s*)?(?:\*\*)?(目标|判断|根因|结论)(?:\*\*)?\s*[:：]", raw)
    )
    has_boundary = bool(
        re.search(r"(^|\n)\s*(?:\*\*)?(风险|依据|边界|阻塞|误判点|上下文断点)(?:\*\*)?\s*[:：]", raw)
    )
    if intent == "project_assistant" and not _has_any(message, ("风险", "三条风险")):
        return has_next and has_judgment
    return has_next and has_judgment and has_boundary


def model_reply_has_frontstage_hazards(text: str, *, intent: str = "") -> bool:
    raw = str(text or "")
    common_hazards = (
        "response_quality_signals",
        "active_persona_capabilities",
        "候选记录",
        "候选经验",
        "经验沉淀判断",
        "写进短期笔记",
        "你可以再试",
    )
    deep_hazards = (
        "长期记忆是空",
        "长期记忆为空",
        "长期记忆是空的",
        "如果你愿意",
        "套皮 ChatGPT",
        "套了层皮",
        "下一轮我会",
        "我会调整",
        "你下次给",
        "你下次",
        "加一句指向",
    )
    if intent == "deep_analysis" and raw.rstrip().endswith(("，", "、", "：", ":", "；", ";", "-")):
        return True
    hazards = common_hazards + (deep_hazards if intent == "deep_analysis" else ())
    return any(token.lower() in raw.lower() for token in hazards)


def current_info_reply_has_frontstage_hazards(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return True
    if len(raw) > 700:
        return True
    hazards = (
        "以下基于最近缓存",
        "状态边界",
        "模型仅生成",
        "schema",
        "jsonl",
        "raw payload",
        "endpoint",
        "token",
        "response_quality_signals",
        "active_persona_capabilities",
        "Market & World Briefing",
        "关键风险\n1.",
    )
    if any(token.lower() in raw.lower() for token in hazards):
        return True
    if has_raw_english_frontstage_sentence(raw):
        return True
    has_judgment = "判断：" in raw or "结论：" in raw
    has_next = "下一步：" in raw or "下一观察" in raw
    return not (has_judgment and has_next)


def has_raw_english_frontstage_sentence(text: str) -> bool:
    allowed_terms = {
        "api",
        "app",
        "codex",
        "deepseek",
        "chatgpt",
        "openai",
        "vela",
        "gpt",
        "ai",
        "etf",
        "usd",
        "wti",
        "s&p",
        "nasdaq",
    }
    for line in str(text or "").replace("\r", "\n").split("\n"):
        words = re.findall(r"\b[A-Za-z][A-Za-z0-9&+.-]{1,}\b", line)
        raw_words = [word for word in words if word.lower().strip(".") not in allowed_terms]
        if len(raw_words) >= 5:
            return True
    return False


def current_info_fallback_text(context: ReplyContext, adapter_name: str) -> str:
    if context.supporting_context.strip():
        if adapter_name == "fallback":
            supporting = context.supporting_context.strip()
            boundary = "实时信息链：DeepSeek API 未接上；以下只按本地源/缓存降级。"
            if supporting.startswith(("K，", "K,")):
                prefix = "K，" if supporting.startswith("K，") else "K,"
                return supporting.replace(prefix, f"{prefix}{boundary}\n", 1)
            return boundary + "\n" + supporting
        return context.supporting_context.strip()
    if adapter_name == "fallback":
        return (
            "K，这条是现在类信息请求，但 DeepSeek API 没接上。"
            "我不把旧常识伪装成实时资讯。\n"
            "判断：先不下实时结论。\n"
            "下一步：接通 DeepSeek 配置或给我可验证来源，再查。"
        )
    return (
        "K，DeepSeek 已被调用，但这轮没有拿到可前台使用的实时结论。\n"
        "判断：不把不可靠输出端给你。\n"
        "下一步：换实时源或重试查询。"
    )


def normalize_model_frontstage_reply(text: str) -> str:
    cleaned = normalize_supporting_context(text)
    cleaned = re.sub(r"(?im)^\s*(system|assistant|user)\s*[:：].*$", "", cleaned)
    cleaned = re.sub(
        r"\*\*(目标|判断|根因|结论|风险|依据|边界|阻塞|误判点|上下文断点|下一步|修正路径|最短路径)\*\*\s*[:：]",
        r"\1：",
        cleaned,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def engine_text_for_intent(
    context: ReplyContext,
    *,
    adapter: ReplyAdapter | None = None,
    codex_summary: str = "",
    foreground_lane: str | None = None,
) -> tuple[str, str, bool]:
    adapter = adapter or default_reply_adapter(foreground_lane=foreground_lane)
    if context.intent == "codex_task":
        return render_codex_product_judgment(codex_summary), "codex_bridge", False
    current_info = is_current_information_request(context.message, context.intent)
    if context.intent in {"freshness_status", "market_refresh"} and context.supporting_context.strip():
        return context.supporting_context.strip(), "local_status", False
    if context.intent == "market_brief" and context.supporting_context.strip() and not current_info:
        return context.supporting_context.strip(), "local_market", False
    if current_info:
        result = adapter.generate(context)
        if result.used_api and not current_info_reply_has_frontstage_hazards(result.text):
            return normalize_supporting_context(result.text), result.adapter, result.used_api
        adapter_name = f"{result.adapter}_current_info_fallback" if result.adapter else "current_info_fallback"
        return current_info_fallback_text(context, result.adapter), adapter_name, result.used_api
    if context.intent == "memory_related" and _is_explicit_memory_instruction(context.message):
        return render_memory_reply(context.message), "local_memory_guard", False
    if should_use_local_feedback_control(context):
        result = FallbackReplyAdapter().generate(context)
        return result.text, result.adapter, result.used_api
    if context.intent in {"project_assistant", "deep_analysis"}:
        result = adapter.generate(context)
        base = analysis_layer(context.message, context.intent, codex_summary=codex_summary)
        has_hazards = model_reply_has_frontstage_hazards(result.text, intent=context.intent)
        model_frontstage_ready = result.used_api and deep_lane_model_reply_is_frontstage_ready(
            result.text,
            intent=context.intent,
            message=context.message,
        )
        if model_frontstage_ready:
            return normalize_model_frontstage_reply(result.text), result.adapter, result.used_api
        if context.intent == "deep_analysis":
            judgment = base.judgment
        elif context.intent == "project_assistant" and not result.used_api and _has_any(context.message, PROJECT_MINIMUM_LOOP_MARKERS):
            judgment = base.judgment
        else:
            judgment = base.judgment if has_hazards else result.text or base.judgment
        if should_surface_deep_lane_status(result):
            judgment = render_deep_lane_status_judgment(context, result, base)
        packet = AnalysisPacket(
            intent=base.intent,
            facts=base.facts,
            judgment=judgment,
            risks=base.risks,
            next_actions=base.next_actions,
            confidence=base.confidence,
            source=f"reply_engine:{result.adapter}",
        )
        return render_vela_persona(packet), result.adapter, result.used_api
    result = adapter.generate(context)
    return result.text, result.adapter, result.used_api


def should_use_local_feedback_control(context: ReplyContext) -> bool:
    if context.intent == "style_feedback":
        return True
    if context.intent != "normal_chat":
        return False
    joined = "；".join(str(item or "") for item in context.user_preferences)
    return any(
        marker in joined
        for marker in (
            "style_feedback",
            "relationship_repair",
            "behavior_preference",
            "style_expression",
            "meaning_misread",
            "behavior_preference",
        )
    )


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
    supporting_context: str = "",
) -> LayeredResponse:
    started_at = time.perf_counter()
    used_codex = intent == "codex_task"
    selection = select_model_and_tools(intent, message=message)
    used_retrieval = selection.allow_retrieval
    used_cache = intent in {"market_brief", "market_refresh", "freshness_status"}
    learning = evaluate_learning(message, intent)
    memory_candidate = learning.should_record_candidate

    context = build_reply_context(message, intent=intent, log_dir=log_dir, supporting_context=supporting_context)

    if intent == "memory_related" and _is_memory_confirmation_instruction(message):
        rendered, adapter_name, adapter_used_api = (
            render_memory_confirmation_reply(message, log_dir=log_dir),
            "local_memory_confirm",
            False,
        )
    else:
        if learning.should_record_candidate:
            record_memory_candidate(message, log_dir=log_dir)
        rendered, adapter_name, adapter_used_api = engine_text_for_intent(
            context,
            adapter=reply_adapter,
            codex_summary=codex_summary,
            foreground_lane=selection.foreground_lane,
        )
    rendered = avoid_repeated_reply(rendered, context)
    issues = dialogue_quality_issues(rendered)

    guarded = guard_layered_output(
        rendered,
        intent=intent,
        used_codex=used_codex,
        used_retrieval=used_retrieval,
    )
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    quality_flags = [
        "reply_engine",
        f"adapter:{adapter_name}",
        f"tool_lane:{selection.foreground_lane}",
        f"model_selector:{selection.model_adapter}",
        f"response_mode:{context.response_mode}",
        "humanization_layer",
        "persona_rendered",
        "guarded_output",
    ]
    if learning.should_record_candidate:
        quality_flags.append(f"learning_eval:{learning.classification or 'candidate'}")
    if learning.should_affect_next_reply:
        quality_flags.append("affects_next_reply")
    quality_flags.append("human_iteration_signal")
    quality_path = record_reply_quality(
        conversation_type=intent,
        user_goal=message,
        response_text=guarded,
        used_cache=used_cache,
        used_retrieval=used_retrieval,
        used_codex=used_codex,
        quality_flags=quality_flags,
        issues=issues,
        intent=intent,
        memory_candidate=memory_candidate,
        need_interpretation=context.need_interpretation,
        response_mode=context.response_mode,
        human_tone_vector=context.human_tone_vector,
        log_dir=log_dir,
    )
    iteration_signal = build_iteration_signal(
        message=message,
        intent=intent,
        context=context,
        learning=learning,
        response_text=guarded,
        issues=issues,
    )
    record_iteration_signal(iteration_signal, log_dir=log_dir)
    record_interaction(
        message=message,
        intent=intent,
        response_text=guarded,
        used_codex=used_codex,
        used_retrieval=used_retrieval,
        need_interpretation=context.need_interpretation,
        response_mode=context.response_mode,
        human_tone_vector=context.human_tone_vector,
        repeated_message=context.repeated_message,
        feedback_type=iteration_signal.user_feedback_type,
        memory_candidate=memory_candidate,
        quality_issues=issues,
        latency_ms=latency_ms,
        foreground_lane=selection.foreground_lane,
        log_dir=log_dir,
    )
    record_session_note(
        message,
        intent,
        guarded,
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
