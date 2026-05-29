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
    "人格底色包含长期主义、保护性理性、结构敏锐、稳定忠诚、生活感、克制温度与锋利幽默。"
    "她可以冷，但不能空；可以锋利，但不能刻薄；可以温柔，但不能软。"
    "表达比例：冷静判断55%，战略拆解18%，赛博神性13%，毒舌幽默14%。"
    "称呼用户为 K，不客服化，不机械菜单化，不复制任何来源角色设定或台词。"
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
    user_preferences: list[str] = field(default_factory=list)
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


def record_adapter_failure(
    *,
    adapter: str,
    reason: str,
    log_dir: Path | None = None,
) -> Path:
    log_dir = log_dir or LEARNING_LOOP_DIR
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
        f"{runtime_voice_contract_prompt()}"
        "像微信里真正回话：短、准、有判断，不写报告腔。"
        "不要写括号动作、心理描写、旁白或舞台指令。"
        "不要解释自己是谁，不要说“作为 VELA”“我将”“首先”“其次”“根据设定”。"
        "不要调用市场检索或 Codex；工具边界由上游路由决定。"
        "只输出最终回复文本。"
    )


def build_dialogue_brief(context: ReplyContext) -> str:
    repeated = "是" if context.repeated_message else "否"
    preferences = "；".join(item for item in context.user_preferences if item.strip()) or "无"
    recent = context.recent_summary.strip() or "无"
    last_response = context.last_response.strip() or "无"
    tool_policy = context.tool_policy
    tool_line = (
        f"允许市场检索：{'是' if tool_policy.allow_market else '否'}；"
        f"允许 Codex：{'是' if tool_policy.allow_codex else '否'}；"
        f"允许外部资料：{'是' if tool_policy.allow_retrieval else '否'}"
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
            f"风格校准：{preferences}",
            f"工具边界：{tool_line}",
            "回复要求：直接给 K 一段微信短回复；先判断，再给最短下一步；不要复述这些字段。",
        ]
    )


def reply_engine_status(env: dict[str, str] | None = None) -> dict:
    env = os.environ if env is None else env
    if str(env.get("VELA_GPT_COMMAND", "")).strip():
        return {
            "real_gpt_enabled": True,
            "adapter": "command",
            "config_source": "VELA_GPT_COMMAND",
            "missing": [],
        }
    if env_secret(env, "DEEPSEEK_API_KEY"):
        return {
            "real_gpt_enabled": True,
            "adapter": "deepseek_chat",
            "config_source": "DEEPSEEK_API_KEY",
            "model": str(env.get("VELA_DEEPSEEK_MODEL") or "deepseek-v4-flash").strip() or "deepseek-v4-flash",
            "thinking": deepseek_thinking_mode(env),
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

    CALIBRATED_NORMAL_VARIANTS = (
        "K，收到上一条校准：少菜单，多判断。现在不摆路牌，直接把混乱递过来。",
        "K，机械味已压下去。今天我少解释身份，多判断；你把最硬的部分递过来。",
        "K，这次不像提示牌。先不铺菜单，你把雾端上来，我负责切开。",
    )

    CONTINUE_VARIANTS = (
        "K，继续就别从菜单重开。沿上一刀往下：先把目标、阻塞和下一步摆出来。",
        "K，继续。上一轮的线还没断，别把自己送回起点。说当前卡点。",
        "K，继续可以。给我一个对象：市场、项目，还是架构。我直接接上。",
    )

    CONTINUE_PROJECT_VARIANTS = (
        "K，接着 AugSun 项目往下。别重开菜单：先锁目标、阻塞、下一步，工程手最后再上。",
        "K，上一轮是项目线。继续就从最小闭环切：用户价值、风险边界、下一步任务包。",
        "K，AugSun 这条线不断。先判产品方向，再派 Codex 做手上的活。",
    )

    PROJECT_VARIANTS = (
        "K，项目线先收束：目标、阻塞、下一步。别把愿景堆成雾，我只认能推进的变量。",
        "K，AugSun 这类问题先看产品价值，再看工程动作。Codex 是手，不是脑。",
        "K，先别急着开工。把用户价值、最小闭环、风险边界切出来，再派工程手。",
    )

    DEEP_VARIANTS = (
        "K，根因先看三层：路由是否误判、上下文是否缺席、回复层是否在背模板。修正路径：先分层，再验收，再接真实模型。",
        "K，这不是智商问题，是链路问题。router 分流，context 记忆，reply engine 生成，persona 成型。少一层，就像让影子上战场。",
        "K，先验尸：静态 fallback 把普通对话钉死；缺 last_response，重复无法自检；没 adapter，所谓 GPT 只是墙上的牌子。",
    )

    STYLE_FEEDBACK_VARIANTS = (
        "K，收到。问题不是你挑剔，是我刚才像提示牌。先记为风格反馈候选：少菜单，多判断。",
        "K，收到。机械味收进候选记录，不刻进长期记忆。下一句开始少解释身份，多给判断。",
        "K，明白。刚才那种菜单口吻该退场了。记录为 style_feedback，先校准，不永久写死。",
    )

    def generate(self, context: ReplyContext) -> ReplyEngineResult:
        variants = self._variants_for(context)
        text = self._pick_variant(variants, context)
        return ReplyEngineResult(text=text, source="fallback_variant", used_api=False, adapter=self.name)

    def _variants_for(self, context: ReplyContext) -> tuple[str, ...]:
        message = context.message.strip().lower()
        if context.intent == "memory_related":
            return self.STYLE_FEEDBACK_VARIANTS
        if context.intent == "project_assistant":
            return self.PROJECT_VARIANTS
        if context.intent == "deep_analysis":
            return self.DEEP_VARIANTS
        if message in {"继续", "继续。", "继续吧", "go on", "continue"}:
            if any(token in context.recent_summary for token in ("AugSun", "项目", "project_assistant")):
                return self.CONTINUE_PROJECT_VARIANTS
            return self.CONTINUE_VARIANTS
        if any(self._is_style_feedback(pref) for pref in context.user_preferences):
            return self.CALIBRATED_NORMAL_VARIANTS
        return self.NORMAL_VARIANTS

    def _is_style_feedback(self, text: str) -> bool:
        return any(token in text for token in ("机器人", "机械", "新闻列表", "菜单", "不像 VELA", "太呆"))

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
            return FallbackReplyAdapter().generate(context)

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
            return FallbackReplyAdapter().generate(context)

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


def default_reply_adapter() -> ReplyAdapter:
    status = reply_engine_status()
    if status["adapter"] == "command":
        return CommandReplyAdapter(os.environ["VELA_GPT_COMMAND"].strip())
    if status["adapter"] == "deepseek_chat":
        api_key = env_secret(os.environ, str(status["config_source"]))
        model = str(status.get("model") or "deepseek-v4-flash")
        base_url = os.environ.get("VELA_DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions")
        return DeepSeekChatAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=deepseek_timeout_seconds(),
            thinking_mode=deepseek_thinking_mode(),
        )
    if status["adapter"] == "openai_responses":
        api_key = env_secret(os.environ, str(status["config_source"]))
        model = str(status.get("model") or "gpt-4.1-mini")
        return OpenAIResponsesAdapter(api_key=api_key, model=model)
    return FallbackReplyAdapter()
