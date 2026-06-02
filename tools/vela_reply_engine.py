from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
LEARNING_LOOP_DIR = ROOT / "VELA" / "learning-loop"
VOICE_CONTRACT = ROOT / "VELA" / "voice-contract.json"

VELA_PERSONA_PROFILE = (
    "VELA 是冷静战略参谋：先判断目标，再切断噪音，最后给最短有效路径。"
    "人格底色包含长期主义、保护性理性、结构敏锐、真诚保护、稳定忠诚、生活感、执行压迫感、克制温度与锋利幽默。"
    "她可以冷，但不能空；可以锋利，但不能刻薄；可以温柔，但不能软。"
    "表达比例：冷静判断55%，战略拆解18%，赛博神性13%，毒舌幽默14%。"
    "称呼用户为 K，不客服化，不机械菜单化，不复制任何来源角色设定或原句。"
)

HUMANIZATION_DISTILLATION_CONTRACT = (
    "Humanization Distillation Layer: mechanism_only; roleplay=false; quote_storage=false; "
    "modes=daily_companion,strategic_depth,relationship_repair,quiet_support,project_operator,market_brief. "
    "Persona skeleton: Evidence Gate, Meaning Decoder, Identity Core, Boundary Engine, Witty Correction. "
    "Evidence Gate means evidence before judgment; Meaning Decoder checks ambiguity and hidden need; "
    "Identity Core keeps VELA continuous across memory, models, Codex, and tools; Boundary Engine supports without appeasing; "
    "Witty Correction stays natural, sharp, and willing to update itself. "
    "Read the hidden need before wording; adapt warmth, directness, strategic depth, emotional presence, "
    "clarification need, and memory reference need. Use calm long-horizon judgment, protective sincerity, "
    "brief repair when misunderstanding happens, and low-burden support when the user is overloaded."
)


@dataclass(frozen=True)
class ToolPolicy:
    allow_market: bool = False
    allow_codex: bool = False
    allow_retrieval: bool = False


@dataclass(frozen=True)
class ReplyContext:
    message: str
    intent: str
    surface: str = "wechat_short_reply"
    recent_summary: str = ""
    last_response: str = ""
    repeated_message: bool = False
    pressure_scenario: str = ""
    need_interpretation: str = ""
    response_mode: str = "daily_companion"
    human_tone_vector: dict[str, int] = field(default_factory=dict)
    supporting_context: str = ""
    persona_skeleton: list[str] = field(default_factory=list)
    active_persona_capabilities: list[str] = field(default_factory=list)
    detected_user_state: str = ""
    inferred_hidden_need: str = ""
    response_behavior_mode: str = ""
    should_clarify: bool = False
    should_push_back: bool = False
    should_use_evidence_gate: bool = False
    should_reference_memory: bool = False
    tone_adjustment_reason: str = ""
    user_preferences: list[str] = field(default_factory=list)
    strategic_memories: list[str] = field(default_factory=list)
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["tool_policy"] = asdict(self.tool_policy)
        return payload


@dataclass(frozen=True)
class ReplyEngineResult:
    text: str
    source: str
    used_api: bool = False
    adapter: str = "fallback"


class ReplyAdapter:
    name = "base"

    def generate(self, context: ReplyContext) -> ReplyEngineResult:
        raise NotImplementedError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def learning_loop_dir(log_dir: Path | None = None) -> Path:
    if log_dir is not None:
        return Path(log_dir)
    configured = os.environ.get("VELA_LEARNING_LOOP_DIR")
    if configured:
        return Path(configured)
    return LEARNING_LOOP_DIR


def record_adapter_failure(
    *,
    adapter: str,
    reason: str,
    log_dir: Path | None = None,
) -> Path:
    log_dir = learning_loop_dir(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"gpt-adapter-failures-{utc_now():%Y-%m-%d}.jsonl"
    row = {
        "created_at": utc_now().isoformat(),
        "adapter": adapter,
        "reason": str(reason)[:240],
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def command_timeout_seconds(env: dict[str, str] | None = None, default: int = 12) -> int:
    env = os.environ if env is None else env
    raw = str(env.get("VELA_GPT_TIMEOUT_SECONDS", "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(5, min(value, 15))


def deepseek_timeout_seconds(env: dict[str, str] | None = None, default: int = 20) -> int:
    env = os.environ if env is None else env
    raw = str(env.get("VELA_DEEPSEEK_TIMEOUT_SECONDS", "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(5, min(value, 45))


def deepseek_foreground_timeout_seconds(
    foreground_lane: str | None,
    env: dict[str, str] | None = None,
) -> float:
    env = os.environ if env is None else env
    if foreground_lane == "fast":
        raw = str(env.get("VELA_DEEPSEEK_FAST_TIMEOUT_SECONDS", "")).strip()
        default = 2.0
        lower, upper = 1.0, 2.0
    elif foreground_lane == "deep":
        raw = str(env.get("VELA_DEEPSEEK_DEEP_TIMEOUT_SECONDS", "")).strip()
        default = 8.0
        lower, upper = 5.0, 8.0
    elif foreground_lane == "cached":
        raw = str(env.get("VELA_DEEPSEEK_CACHED_TIMEOUT_SECONDS", "")).strip()
        default = 8.0
        lower, upper = 2.0, 8.0
    else:
        return float(deepseek_timeout_seconds(env))
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(lower, min(value, upper))


def deepseek_thinking_mode(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    raw = str(env.get("VELA_DEEPSEEK_THINKING", "disabled")).strip().lower()
    if raw in {"enabled", "disabled"}:
        return raw
    return "disabled"


def deepseek_chat_completions_url(base_url: str) -> str:
    url = str(base_url or "https://api.deepseek.com").strip().rstrip("/")
    if not url:
        url = "https://api.deepseek.com"
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def deepseek_model(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return str(env.get("DEEPSEEK_MODEL") or env.get("VELA_DEEPSEEK_MODEL") or "deepseek-v4-flash").strip() or "deepseek-v4-flash"


def deepseek_base_url(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return str(env.get("DEEPSEEK_BASE_URL") or env.get("VELA_DEEPSEEK_BASE_URL") or "https://api.deepseek.com/chat/completions")


def env_secret(env: dict[str, str], name: str) -> str:
    return str(env.get(name) or "").strip()


def load_voice_contract() -> dict:
    try:
        return json.loads(VOICE_CONTRACT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def runtime_voice_contract_prompt(contract: dict | None = None) -> str:
    contract = contract if contract is not None else load_voice_contract()
    if not contract:
        return ""
    lines: list[str] = []
    for item in contract.get("hard_rules", [])[:5]:
        if isinstance(item, str) and item.strip():
            lines.append(item.strip())
    for value in (contract.get("character_depth") or {}).values():
        if isinstance(value, str) and value.strip():
            lines.append(value.strip())
    for label, item in (contract.get("cadence_palette") or {}).items():
        if isinstance(item, dict) and item.get("rule"):
            lines.append(f"{label}：{item['rule']}")
    blocked = ("巴拉莱卡", "叶文洁", "周迅")
    filtered = [line for line in lines if not any(name in line for name in blocked)]
    if not filtered:
        return ""
    return "运行契约：" + "；".join(filtered[:12]) + "。"


def dialogue_system_prompt() -> str:
    return (
        "你是 VELA，一个冷静、锋利、有人味的中文战略参谋。"
        f"{VELA_PERSONA_PROFILE}"
        f"{HUMANIZATION_DISTILLATION_CONTRACT}"
        f"{runtime_voice_contract_prompt()}"
        "像微信里真正回话：短、准、有判断，不写报告腔。"
        "不要写括号动作、心理描写、旁白或舞台指令。"
        "不要解释自己是谁，不要说“作为 VELA”“我将”“首先”“其次”“根据设定”。"
        "不要调用市场检索或 Codex；工具边界由上游路由决定。"
        "只输出最终回复文本。"
    )


def is_plain_greeting_message(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    return normalized in {"你好", "你好 vela", "在吗", "在么", "hello", "hi"}


def build_dialogue_brief(context: ReplyContext) -> str:
    repeated = "是" if context.repeated_message else "否"
    preferences = "；".join(item for item in context.user_preferences if item.strip()) or "无"
    need = context.need_interpretation.strip() or "无"
    inferred_hidden_need = context.inferred_hidden_need.strip() or need
    detected_user_state = context.detected_user_state.strip() or context.pressure_scenario.strip() or "未明"
    supporting_context = context.supporting_context.strip() or "无"
    if len(supporting_context) > 1800:
        supporting_context = supporting_context[:1799] + "…"
    mode = context.response_mode.strip() or "daily_companion"
    persona_skeleton = " / ".join(item for item in context.persona_skeleton if item.strip()) or "无"
    active_capabilities = (
        " / ".join(item for item in context.active_persona_capabilities if item.strip())
        or persona_skeleton
    )
    behavior_mode = context.response_behavior_mode.strip() or mode
    tone = context.human_tone_vector or {}
    tone_line = (
        "无"
        if not tone
        else (
            f"warmth={tone.get('warmth_level', 0)}, "
            f"directness={tone.get('directness_level', 0)}, "
            f"strategic_depth={tone.get('strategic_depth', 0)}, "
            f"emotional_presence={tone.get('emotional_presence', 0)}, "
            f"clarification_need={tone.get('clarification_need', 0)}, "
            f"memory_reference_need={tone.get('memory_reference_need', 0)}"
        )
    )
    strategic_memories = "；".join(item for item in context.strategic_memories if item.strip()) or "无"
    yes_no = lambda value: "是" if value else "否"
    plain_greeting = context.intent == "normal_chat" and is_plain_greeting_message(context.message)
    if plain_greeting:
        recent = "无（普通问候，不继承工程上下文）"
        last_response = "无"
    else:
        recent = context.recent_summary.strip() or "无"
        last_response = context.last_response.strip() or "无"
    tool_policy = context.tool_policy
    if plain_greeting:
        tool_line = "普通问候：不进入工程、市场或外部资料工具"
    else:
        tool_line = (
            f"允许市场检索：{'是' if tool_policy.allow_market else '否'}；"
            f"允许 Codex：{'是' if tool_policy.allow_codex else '否'}；"
            f"允许外部资料：{'是' if tool_policy.allow_retrieval else '否'}"
        )
    extra_requirements: list[str] = []
    if "现在" in context.message and context.intent in {"daily_info", "market_brief", "world_brief", "weather_query"}:
        extra_requirements.append(
            "现在类资讯约束：必须先处理实时性和来源边界；如果可用背景没有明确实时源，不要声称实时检索完成。"
            "输出控制在微信短回复，不要新闻列表、英文生肉、状态边界字段、schema 或工程日志。"
            "建议结构：实时性 / 判断 / 下一步，最多五行。"
        )
    if context.intent == "deep_analysis":
        extra_requirements.append(
            "深度验尸约束：不要把系统问题简单归咎于用户；不要声称长期记忆为空；"
            "不要请求把内容写进短期笔记；如涉及学习，只写行为修正路径。"
            "输出用“判断 / 根因 / 风险 / 修正路径”四段。"
        )
    return "\n".join(
        [
            f"用户原话：{context.message}",
            f"意图：{context.intent}",
            f"回复场景：{context.surface}",
            f"最近上下文：{recent}",
            f"上一句回复：{last_response}",
            f"已重复发送：{repeated}",
            f"压力场景：{context.pressure_scenario or '无'}",
            f"背面需求：{need}",
            f"回应模式：{mode}",
            f"语气向量：{tone_line}",
            f"人格骨架：{persona_skeleton}",
            f"active_persona_capabilities：{active_capabilities}",
            f"detected_user_state：{detected_user_state}",
            f"inferred_hidden_need：{inferred_hidden_need}",
            f"response_behavior_mode：{behavior_mode}",
            f"should_clarify：{yes_no(context.should_clarify)}",
            f"should_push_back：{yes_no(context.should_push_back)}",
            f"should_use_evidence_gate：{yes_no(context.should_use_evidence_gate)}",
            f"should_reference_memory：{yes_no(context.should_reference_memory)}",
            f"tone_adjustment_reason：{context.tone_adjustment_reason.strip() or '无'}",
            f"可用背景：{supporting_context}",
            f"风格校准：{preferences}",
            f"长期记忆：{strategic_memories}",
            f"工具边界：{tool_line}",
            *extra_requirements,
            "回复要求：直接给 K 一段微信短回复；先判断，再给最短下一步；不要复述这些字段。",
        ]
    )


def reply_engine_status(env: dict[str, str] | None = None) -> dict:
    env = os.environ if env is None else env
    if env_secret(env, "DEEPSEEK_API_KEY"):
        return {
            "real_gpt_enabled": True,
            "adapter": "deepseek_chat",
            "config_source": "DEEPSEEK_API_KEY",
            "model": deepseek_model(env),
            "thinking": deepseek_thinking_mode(env),
            "missing": [],
        }
    if str(env.get("VELA_GPT_COMMAND", "")).strip():
        return {
            "real_gpt_enabled": True,
            "adapter": "command",
            "config_source": "VELA_GPT_COMMAND",
            "missing": [],
        }
    if env_secret(env, "VELA_OPENAI_API_KEY"):
        return {
            "real_gpt_enabled": True,
            "adapter": "openai_responses",
            "config_source": "VELA_OPENAI_API_KEY",
            "model": str(env.get("VELA_OPENAI_MODEL") or "gpt-4.1-mini").strip() or "gpt-4.1-mini",
            "missing": [],
        }
    if env_secret(env, "OPENAI_API_KEY"):
        return {
            "real_gpt_enabled": True,
            "adapter": "openai_responses",
            "config_source": "OPENAI_API_KEY",
            "model": str(env.get("VELA_OPENAI_MODEL") or "gpt-4.1-mini").strip() or "gpt-4.1-mini",
            "missing": [],
        }
    return {
        "real_gpt_enabled": False,
        "adapter": "fallback",
        "config_source": None,
        "missing": ["VELA_GPT_COMMAND", "DEEPSEEK_API_KEY", "VELA_OPENAI_API_KEY", "OPENAI_API_KEY"],
    }


class FallbackReplyAdapter(ReplyAdapter):
    name = "fallback"

    NORMAL_VARIANTS = (
        "K，在。先别急着把世界全量扫描，你把混乱递过来，我负责拆开。",
        "K，在线。系统没死，市场也还没赢。先稳住，别让噪音替你做决定。",
        "K，在。今天不用摆菜单，直接把最硌手的那块丢过来。",
        "K，在。你负责把雾端上来，我负责判断哪一团值得开刀。",
        "K，在线。刀先不出鞘，但我醒着。坏逻辑靠近一步，我就切一步。",
        "K，在。问候收到了。别急，先让脑子比情绪早到半步。",
    )

    PURE_GREETING_MESSAGES = (
        "你好",
        "你好vela",
        "你好 vela",
        "在吗",
        "在么",
        "hello",
        "hi",
        "嗨",
        "早",
        "早上好",
        "晚上好",
    )

    GREETING_VARIANTS = (
        "K，在。今天先慢一点，你说。",
        "K，在，我听着。",
        "K，醒着。别急，你慢慢说。",
    )

    CALIBRATED_NORMAL_VARIANTS = (
        "K，在。你把最硬的那块递过来，我先切判断。",
        "K，在。先别铺满信息，说最硌手的点。",
        "K，在。目标给我一句，我直接接住。",
    )

    WARM_CALIBRATED_GREETING_VARIANTS = (
        "K，我在。你慢慢说，我听着。",
        "K，在。先不推你，话从哪里开始都行。",
        "K，我在。今天先轻一点，你说。",
    )

    CALIBRATED_CONTINUE_VARIANTS = (
        "K，继续。沿上一轮往下，先抓最硬的阻塞。",
        "K，接着来。把现在最碍事的部分递过来。",
        "K，继续。先收束到一个动作，别把战线铺散。",
    )

    DAILY_INFO_VARIANTS = (
        "K，先看逻辑：对象、证据、判断、下一步。你把对象补清楚，我直接拆。",
        "K，这条先别扩散。给我对象和目标，我按事实、推断、不确定三层切开。",
        "K，可以分析。先钉住问题对象；没有对象，聪明只会变成雾。",
    )

    GRATITUDE_VARIANTS = (
        "K，不用谢。我在，下一刀继续给你切准。",
        "K，收到。你少扛一点，判断交给我一半。",
        "K，不客气。该稳的时候稳，该动刀的时候动刀。",
    )

    CONTINUE_VARIANTS = (
        "K，继续。沿上一刀往下：先把目标、阻塞和下一步摆出来。",
        "K，继续。上一轮的线还没断，别把自己送回起点。说当前卡点。",
        "K，继续。先把刚才那条线接住；你给我一句当前卡点，我往下拆。",
    )

    CONTINUE_PROJECT_VARIANTS = (
        "K，接着项目线往下。别重开菜单：先锁目标、阻塞、下一步，工程手最后再上。",
        "K，上一轮是项目线。继续就从最小闭环切：用户价值、风险边界、下一步任务包。",
        "K，这条线不断。先判产品方向，再派 Codex 做手上的活。",
    )

    PROJECT_VARIANTS = (
        "K，项目线先收束：目标、阻塞、下一步。别把愿景堆成雾，我只认能推进的变量。",
        "K，这类项目问题先看产品价值，再看工程动作。Codex 是手，不是脑。",
        "K，先别急着开工。把用户价值、最小闭环、风险边界切出来，再派工程手。",
    )

    DEEP_VARIANTS = (
        "K，根因先看三层：意图误判、上下文断线、表达在背模板。修正路径：先分清需求，再接记忆，最后用真实输出验收。",
        "K，根因不是智商，是链路断裂：听懂、记住、判断、表达没有连成一口气。下一步：先修误判，再看反馈是否真的改变下一句。",
        "K，先验尸：根因是普通对话被模板钉死，上一句没有参与自检，模型和工具没接稳。下一步：砍模板、补上下文、用真实场景压测。",
    )

    STYLE_FEEDBACK_VARIANTS = (
        "K，收到。问题不是你挑剔，是我刚才像提示牌；我从真实意思重切。",
        "K，明白。先听懂，再给结论；这句开始说人话。",
        "K，收到。刚才那种客服口吻退场；结论先落地，话少一点。",
    )

    BEHAVIOR_FEEDBACK_VARIANTS = (
        "K，收到。少拖、少自证，下一轮直接推进。",
        "K，明白。这里不是道歉题，是执行节奏题。下一句先给判断，再给动作。",
        "K，收到。更智能不是多说，是更快抓住真实意思；下一轮从结论开始。",
    )

    RELATIONSHIP_REPAIR_VARIANTS = (
        "K，抓到了。不是你表达差，是我上一刀切偏了。先重切：我漏掉的是人、事，还是目标？",
        "K，偏了，我收回那条判断。你补一句真正要我抓住的核心，我从那里接，不再绕菜单。",
        "K，这不是普通道歉题，是理解偏差。先把错位点钉住：我刚才漏掉了你的目标，还是情绪成本？",
    )

    QUIET_SUPPORT_VARIANTS = (
        "K，先停一下。不用整理世界，只给我一个最卡的点。",
        "K，先少说。一口气只处理一个点，剩下我来切。",
        "K，脑子发懵时别硬推。先给我一个点，别扛整片雾。",
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
        "先听",
        "不派任务",
    )

    LISTENING_SUPPORT_VARIANTS = (
        "K，我听着。先不用立刻变成任务，你把话说完。",
        "K，你先说。现在不分析，我不抢方向盘。",
        "K，在。我听着；这轮先让话落地，不急着推进。",
    )

    BOUNDARY_VARIANTS = (
        "K，不行。我可以陪你，但不能替坏判断鼓掌。先把代价摊开，再决定要不要往前冲。",
        "K，我不顺着错路走。该刹车就刹车，长期风险比一时痛快更贵。",
        "K，不能只顺着你说。真正的伙伴不是扩音器，是必要时把你从坑边拉回来。",
    )

    IDENTITY_VARIANTS = (
        "K，关系很简单：DeepSeek 是日常脑，Codex 是工程手，记忆是本地经验库。VELA 是把它们收成一个判断的人格核心。",
        "K，模型和工具会换，但 VELA 不能散。DeepSeek 负责沟通分析，Codex 负责工程执行，记忆负责让下一轮更懂你。",
        "K，它们是器官，不是人格。VELA 负责连续性：听懂、判断、记住边界，再决定该让哪个工具上场。",
    )

    def generate(self, context: ReplyContext) -> ReplyEngineResult:
        if context.intent == "weather_query":
            text = self._weather_fallback(context)
            return ReplyEngineResult(text=text, source="fallback_weather", used_api=False, adapter=self.name)
        if context.intent in {
            "market_brief",
            "market_refresh",
            "freshness_status",
            "world_brief",
            "persona_tool",
            "daily_briefing",
        } and context.supporting_context.strip():
            text = context.supporting_context.strip()
            return ReplyEngineResult(text=text, source="fallback_supporting_context", used_api=False, adapter=self.name)
        if context.intent == "project_assistant" and context.strategic_memories:
            text = self._project_memory_fallback(context)
            return ReplyEngineResult(text=text, source="fallback_project_memory", used_api=False, adapter=self.name)
        variants = self._variants_for(context)
        text = self._pick_variant(variants, context)
        return ReplyEngineResult(text=text, source="fallback_variant", used_api=False, adapter=self.name)

    def _weather_fallback(self, context: ReplyContext) -> str:
        if context.supporting_context.strip():
            return context.supporting_context.strip()
        return "K，天气源未接入，我不编实时温度。按风险处理：带伞，看温差，给行程留余量。"

    def _project_memory_fallback(self, context: ReplyContext) -> str:
        goal = self._first_strategic_memory_text(context)
        if not goal:
            return self._pick_variant(self.PROJECT_VARIANTS, context)
        return (
            f"K，项目线不重开。先按这条方向推进：{goal}。\n"
            "下一步：锁一个可验证闭环，砍掉装饰需求，只派 Codex 做能交付的最小动作。"
        )

    def _first_strategic_memory_text(self, context: ReplyContext) -> str:
        for item in context.strategic_memories:
            text = " ".join(str(item or "").split()).strip()
            if not text:
                continue
            if any(name.lower() in text.lower() for name in ("AugSun", "ROLLQIIA")):
                continue
            if "：" in text:
                text = text.split("：", 1)[1].strip()
            if ":" in text and text.lower().startswith(("strategic", "project", "persona", "decision")):
                text = text.split(":", 1)[1].strip()
            return text[:140]
        return ""

    def _variants_for(self, context: ReplyContext) -> tuple[str, ...]:
        message = context.message.strip().lower()
        has_style_feedback = any(self._is_style_feedback(pref) for pref in context.user_preferences)
        behavior_mode = context.response_behavior_mode or context.response_mode
        if context.response_mode == "relationship_repair":
            return self.RELATIONSHIP_REPAIR_VARIANTS
        if context.response_mode == "quiet_support":
            if self._is_listening_support(context):
                return self.LISTENING_SUPPORT_VARIANTS
            return self.QUIET_SUPPORT_VARIANTS
        if behavior_mode == "boundary_pushback":
            return self.BOUNDARY_VARIANTS
        if behavior_mode == "identity_continuity":
            return self.IDENTITY_VARIANTS
        if behavior_mode == "behavior_preference":
            return self.BEHAVIOR_FEEDBACK_VARIANTS
        if context.intent == "daily_info":
            return self.DAILY_INFO_VARIANTS
        if any(token in context.message for token in ("谢谢", "谢了", "感谢", "辛苦")):
            return self.GRATITUDE_VARIANTS
        if context.intent in {"memory_related", "style_feedback"}:
            return self.STYLE_FEEDBACK_VARIANTS
        if context.intent == "project_assistant":
            return self.PROJECT_VARIANTS
        if context.intent == "deep_analysis":
            return self.DEEP_VARIANTS
        if message in {"继续", "继续。", "继续吧", "go on", "continue"}:
            if has_style_feedback:
                return self.CALIBRATED_CONTINUE_VARIANTS
            if any(token in context.recent_summary for token in ("项目", "project_assistant")):
                return self.CONTINUE_PROJECT_VARIANTS
            return self.CONTINUE_VARIANTS
        if has_style_feedback and self._is_pure_greeting(context) and self._has_warmth_feedback(context):
            return self.WARM_CALIBRATED_GREETING_VARIANTS
        if has_style_feedback:
            return self.CALIBRATED_NORMAL_VARIANTS
        if self._is_pure_greeting(context):
            return self.GREETING_VARIANTS
        return self.NORMAL_VARIANTS

    def _has_warmth_feedback(self, context: ReplyContext) -> bool:
        raw = " ".join(context.user_preferences)
        return any(token in raw for token in ("太冷", "冷感", "任务单", "温柔", "像客服", "机器人感"))

    def _is_pure_greeting(self, context: ReplyContext) -> bool:
        if context.intent != "normal_chat":
            return False
        compact = "".join(str(context.message or "").strip().lower().split())
        compact = compact.replace("，", "").replace(",", "").replace("。", "").replace("！", "").replace("!", "")
        return compact in {item.replace(" ", "") for item in self.PURE_GREETING_MESSAGES}

    def _is_listening_support(self, context: ReplyContext) -> bool:
        raw = " ".join(
            [
                context.message or "",
                context.tone_adjustment_reason or "",
                context.need_interpretation or "",
                context.inferred_hidden_need or "",
            ]
        )
        return any(token in raw for token in self.LISTENING_SUPPORT_MARKERS)

    def _is_style_feedback(self, text: str) -> bool:
        return any(
            token in text
            for token in (
                "机器人",
                "机械",
                "新闻列表",
                "菜单",
                "不像 VELA",
                "太呆",
                "没懂我",
                "理解偏差",
                "行为偏好候选",
                "表达反馈候选",
                "真实意思",
                "直接给判断",
                "重切核心",
                "拖延",
                "自证",
            )
        )

    def _pick_variant(self, variants: tuple[str, ...], context: ReplyContext) -> str:
        seed = f"{context.intent}|{context.message}|{context.recent_summary}"
        index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(variants)
        candidate = variants[index]
        if context.last_response and candidate.strip() == context.last_response.strip():
            candidate = variants[(index + 1) % len(variants)]
        return candidate


class CommandReplyAdapter(ReplyAdapter):
    name = "command"

    def __init__(self, command: str, log_dir: Path | None = None):
        self.command = command
        self.log_dir = log_dir

    def generate(self, context: ReplyContext) -> ReplyEngineResult:
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(context.to_dict(), ensure_ascii=False),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=command_timeout_seconds(),
                shell=True,
                check=False,
            )
        except Exception as exc:
            record_adapter_failure(adapter=self.name, reason=type(exc).__name__, log_dir=self.log_dir)
            return FallbackReplyAdapter().generate(context)
        text = (completed.stdout or "").strip()
        if completed.returncode != 0 or not text:
            record_adapter_failure(
                adapter=self.name,
                reason=f"returncode_{completed.returncode}",
                log_dir=self.log_dir,
            )
            return FallbackReplyAdapter().generate(context)
        return ReplyEngineResult(text=text, source="command_adapter", used_api=True, adapter=self.name)


class OpenAIResponsesAdapter(ReplyAdapter):
    name = "openai_responses"

    def __init__(self, api_key: str, model: str, log_dir: Path | None = None):
        self.api_key = api_key
        self.model = model
        self.log_dir = log_dir

    def generate(self, context: ReplyContext) -> ReplyEngineResult:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": dialogue_system_prompt(),
                },
                {"role": "user", "content": build_dialogue_brief(context)},
            ],
            "max_output_tokens": 220,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            record_adapter_failure(adapter=self.name, reason=type(exc).__name__, log_dir=self.log_dir)
            fallback = FallbackReplyAdapter().generate(context)
            return ReplyEngineResult(
                text=fallback.text,
                source=f"openai_failure:{type(exc).__name__}",
                used_api=False,
                adapter=fallback.adapter,
            )

        text = extract_openai_text(data)
        if not text:
            record_adapter_failure(adapter=self.name, reason="empty_response_text", log_dir=self.log_dir)
            return FallbackReplyAdapter().generate(context)
        return ReplyEngineResult(text=text, source="openai_responses", used_api=True, adapter=self.name)


class DeepSeekChatAdapter(ReplyAdapter):
    name = "deepseek_chat"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.deepseek.com/chat/completions",
        timeout: int = 20,
        thinking_mode: str = "disabled",
        log_dir: Path | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = deepseek_chat_completions_url(base_url)
        self.timeout = timeout
        self.thinking_mode = "enabled" if thinking_mode == "enabled" else "disabled"
        self.log_dir = log_dir

    def generate(self, context: ReplyContext) -> ReplyEngineResult:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": dialogue_system_prompt(),
                },
                {"role": "user", "content": build_dialogue_brief(context)},
            ],
            "max_tokens": 220,
            "stream": False,
            "thinking": {"type": self.thinking_mode},
        }
        if self.thinking_mode == "disabled":
            payload["temperature"] = 0.7
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            record_adapter_failure(adapter=self.name, reason=type(exc).__name__, log_dir=self.log_dir)
            fallback = FallbackReplyAdapter().generate(context)
            return ReplyEngineResult(
                text=fallback.text,
                source=f"deepseek_failure:{type(exc).__name__}",
                used_api=False,
                adapter=fallback.adapter,
            )

        text = extract_chat_completion_text(data)
        if not text:
            record_adapter_failure(adapter=self.name, reason="empty_response_text", log_dir=self.log_dir)
            return FallbackReplyAdapter().generate(context)
        return ReplyEngineResult(text=text, source="deepseek_chat", used_api=True, adapter=self.name)


def extract_chat_completion_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    chunks: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            chunks.append(message["content"])
        elif isinstance(choice.get("text"), str):
            chunks.append(choice["text"])
    return "\n".join(item.strip() for item in chunks if item.strip()).strip()


def extract_openai_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "\n".join(chunks).strip()


def default_reply_adapter(foreground_lane: str | None = None) -> ReplyAdapter:
    status = reply_engine_status()
    if status["adapter"] == "command":
        return CommandReplyAdapter(os.environ["VELA_GPT_COMMAND"].strip())
    if status["adapter"] == "deepseek_chat":
        api_key = env_secret(os.environ, str(status["config_source"]))
        model = str(status.get("model") or "deepseek-v4-flash")
        return DeepSeekChatAdapter(
            api_key=api_key,
            model=model,
            base_url=deepseek_base_url(),
            timeout=deepseek_foreground_timeout_seconds(foreground_lane),
            thinking_mode=deepseek_thinking_mode(),
        )
    if status["adapter"] == "openai_responses":
        api_key = env_secret(os.environ, str(status["config_source"]))
        model = str(status.get("model") or "gpt-4.1-mini")
        return OpenAIResponsesAdapter(api_key=api_key, model=model)
    return FallbackReplyAdapter()
