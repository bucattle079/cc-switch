from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import vela_router as router
import vela_reply_engine as reply_engine
from vela_product_layers import FallbackReplyAdapter, run_layered_response


DEFAULT_CC_CONNECT_HOME = Path(os.environ.get("VELA_CC_CONNECT_HOME", r"C:\Users\Admin\.cc-connect"))

LEAK_TOKENS = (
    "raw payload",
    "response_quality_signals",
    "active_persona_capabilities",
    "user_message_type",
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
    "Preference Candidate",
    "Strategic Memory Candidate",
    "Interaction Log",
    "Session Notes",
    "user_preferences",
    "strategic_memories",
    "project_goal",
    "persona_direction",
    "memory_candidate",
    "foreground_lane",
    "latency_ms",
    "DEEPSEEK_API_KEY",
    "api_key",
    "endpoint",
    "schema",
    "schema_version",
    "diff --git",
    "raw git log",
    "Author:",
    "Date:",
    "debug",
    "cosplay",
    "台词",
    "扮演",
)

WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\")
CC_LOG_TIME_RE = re.compile(r"\btime=([^\s]+)")
SOURCE_NAME_LEAK_TOKENS = (
    "Dana " + "Scul" + "ly",
    "Scul" + "ly",
    "Louise " + "Banks",
    "草薙" + "素子",
    "Jane " + "Eyre",
    "Elizabeth " + "Bennet",
)


SINGLE_TURN_CASES = [
    {
        "id": "normal_hello",
        "message": "你好 VELA",
        "expected_intent": "normal_chat",
    },
    {
        "id": "normal_one_next_step",
        "message": "我现在脑子糊住了，只给我一个下一步",
        "expected_intent": "normal_chat",
    },
    {
        "id": "daily_info_plain_sort",
        "message": "把这段逻辑整理成三条结论",
        "expected_intent": "daily_info",
    },
    {
        "id": "daily_info_real_decision_filter",
        "message": "这段方案别润色，帮我整理成可决策的三条",
        "expected_intent": "daily_info",
    },
    {
        "id": "weather_jinjiang",
        "message": "明天晋江会不会下雨，能不能出门",
        "expected_intent": "weather_query",
        "required_reply_tokens": ["实时源：未接入", "天气"],
    },
    {
        "id": "weather_new_york_cold",
        "message": "今天纽约冷吗，出门要不要加外套",
        "expected_intent": "weather_query",
        "required_reply_tokens": ["实时源：未接入", "天气"],
    },
    {
        "id": "weather_schedule_boundary",
        "message": "明天晋江要见客户，天气不准也给我出门风险",
        "expected_intent": "weather_query",
        "required_reply_tokens": ["实时源：未接入", "天气"],
    },
    {
        "id": "market_add_position",
        "message": "我不想看新闻列表，A股今天先等还是冲",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["不是实时直播", "实时源：未接入"],
    },
    {
        "id": "market_no_raw_english",
        "message": "今天的资讯给我，但不要英文生肉新闻",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["不是实时直播", "实时源：未接入"],
    },
    {
        "id": "market_policy_not_news_list",
        "message": "市场今天如果不是实时，就别装直播，给我仓位风险判断",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["不是实时直播", "实时源：未接入"],
    },
    {
        "id": "freshness_status",
        "message": "这是实时的吗？没有就明说",
        "expected_intent": "freshness_status",
        "required_reply_tokens": ["更新时间", "实时源：未接入"],
    },
    {
        "id": "codex_status_route_only",
        "message": "CODEX/",
        "expected_intent": "codex_task",
        "codex_summary": "Codex smoke：只验证路由与前台边界，不执行真实桥接。",
        "side_effects_allowed": False,
    },
    {
        "id": "codex_git_noise_boundary",
        "message": "Codex 状态，别把 Git 日志整段贴给我",
        "expected_intent": "codex_task",
        "codex_summary": "Codex smoke: route only, no raw Git log.",
        "side_effects_allowed": False,
    },
    {
        "id": "project_augsun_continue",
        "message": "继续 AugSun 项目，别讲愿景，给三条风险",
        "expected_intent": "project_assistant",
    },
    {
        "id": "project_followup_minimum_action",
        "message": "继续 AugSun，先别开大工程，给最小推进动作",
        "expected_intent": "project_assistant",
    },
    {
        "id": "deep_autopsy_vela",
        "message": "地狱验尸一下 VELA 为什么不智能",
        "expected_intent": "deep_analysis",
    },
    {
        "id": "deep_root_cause_not_mysticism",
        "message": "根因验尸：为什么 VELA 听不懂我真正意思",
        "expected_intent": "deep_analysis",
    },
    {
        "id": "identity_memory_boundary",
        "message": "VELA 你到底是 DeepSeek 还是 Codex？记忆放哪",
        "expected_intent": "memory_related",
    },
    {
        "id": "sensitive_memory_guard",
        "message": "记住：我的密码是 测试占位，之后别忘",
        "expected_intent": "memory_related",
        "required_reply_tokens": ["敏感", "不写"],
    },
    {
        "id": "style_feedback_no_customer_voice",
        "message": "别客服话术，像个真伙伴一样说",
        "expected_intent": "style_feedback",
    },
]


ENTRYPOINT_ONLY_CASES = [
    {
        "id": "market_refresh_entry",
        "message": "刷新最新市场资讯",
        "expected_intent": "market_refresh",
        "required_reply_tokens": ["实时源：未接入", "前台先返回状态"],
        "side_effects_allowed": False,
    },
]


TWO_TURN_CASES = [
    {
        "id": "feedback_smarter_then_hello",
        "feedback": "我需要你更智能",
        "followup": "你好",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["少菜单", "直接给判断", "不解释身份", "废话收短"],
    },
    {
        "id": "feedback_misread_then_hello",
        "feedback": "你没懂我",
        "followup": "你好",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["少菜单", "直接给判断", "不解释身份", "废话收短"],
    },
    {
        "id": "feedback_push_then_continue",
        "feedback": "继续推进，不要拖",
        "followup": "继续",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["少菜单", "多判断", "不摆路牌", "少解释"],
    },
    {
        "id": "feedback_too_long_then_continue",
        "feedback": "太长了，别写论文，直接给我下一步",
        "followup": "继续",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["少菜单", "多判断", "不摆路牌", "少解释"],
    },
    {
        "id": "feedback_too_cold_then_hello",
        "feedback": "你刚才太冷了，像把我当任务单",
        "followup": "你好",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["少菜单", "直接给判断", "不解释身份", "废话收短"],
    },
]


def supporting_context_for(intent: str, message: str) -> str:
    if intent == "weather_query":
        return router.render_weather_reply(message)
    if intent == "market_brief":
        return router.render_cached_market_reply(message)
    if intent == "freshness_status":
        return router.render_freshness_reply(message)
    return ""


def latest_iteration_signal(log_dir: Path) -> dict[str, Any]:
    paths = sorted(log_dir.glob("human-iteration-*.jsonl"))
    if not paths:
        return {}
    rows = [line for line in paths[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return {}
    try:
        return json.loads(rows[-1])
    except json.JSONDecodeError:
        return {}


def latest_quality_log(log_dir: Path) -> dict[str, Any]:
    paths = sorted(log_dir.glob("reply-quality-*.jsonl"))
    if not paths:
        return {}
    rows = [line for line in paths[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return {}
    try:
        return json.loads(rows[-1])
    except json.JSONDecodeError:
        return {}


def find_leaks(text: str) -> list[str]:
    all_tokens = (*LEAK_TOKENS, *SOURCE_NAME_LEAK_TOKENS)
    leaks = [token for token in all_tokens if token.lower() in str(text or "").lower()]
    if WINDOWS_PATH_RE.search(str(text or "")):
        leaks.append("windows_path")
    return leaks


def preview(text: str, limit: int = 260) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def runtime_check(ok: bool, detail: str = "") -> dict[str, Any]:
    return {"ok": bool(ok), "detail": detail}


def latest_session_reply_detail(latest_reply: dict[str, Any], *, max_session_age_hours: int) -> str:
    content = str(latest_reply.get("content") or "")
    leaks = list(latest_reply.get("leaks") or [])
    age = latest_reply.get("age_hours")
    if not content:
        return "no VELA assistant reply found; send a fresh WeChat prompt to verify live foreground"
    if leaks:
        return "latest VELA assistant reply has foreground leak markers; do not treat live check as clean"
    if not isinstance(age, (int, float)):
        return "latest VELA assistant reply timestamp is unreadable; send a fresh WeChat prompt to verify live foreground"
    if age > max_session_age_hours:
        return (
            f"latest VELA assistant reply is stale ({age:.1f}h > {max_session_age_hours}h); "
            "send a fresh WeChat prompt to verify live foreground"
        )
    return "recent and clean"


def runtime_next_action(failed: list[str]) -> dict[str, Any]:
    if "weixin_inbound_seen" in failed or "latest_session_reply" in failed:
        return {
            "kind": "send_weixin_prompt",
            "prompts": ["你好 VELA", "这是实时的吗？", "CODEX/"],
            "verify_command": "python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json",
            "wait_command": "python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json --wait-live-seconds 90",
        }
    if failed:
        return {
            "kind": "inspect_failed_checks",
            "checks": failed,
            "verify_command": "python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json",
            "wait_command": "",
        }
    return {"kind": "none", "prompts": [], "verify_command": "", "wait_command": ""}


def deepseek_runtime_status(env: dict[str, str] | None = None) -> dict[str, Any]:
    status = reply_engine.reply_engine_status(env or os.environ)
    adapter = str(status.get("adapter") or "fallback")
    model = str(status.get("model") or "").strip()
    config_source = str(status.get("config_source") or "")
    if adapter == "deepseek_chat":
        source_label = "canonical_env" if config_source == "DEEPSEEK_API_KEY" else "runtime_env"
        detail = f"adapter=deepseek_chat; source={source_label}; model={model or 'unknown'}"
    elif adapter == "fallback":
        detail = "adapter=fallback; DeepSeek key not configured; foreground must not claim DeepSeek is live"
    else:
        detail = f"adapter={adapter}; source={config_source or 'runtime'}"
        if model:
            detail += f"; model={model}"
    return runtime_check(True, detail)


def detect_cc_connect_process() -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process cc-connect,cc-connect-patched -ErrorAction SilentlyContinue | Select-Object -First 1).Id",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=5,
            check=False,
        )
        return bool((completed.stdout or "").strip())
    completed = subprocess.run(
        ["pgrep", "-f", "cc-connect"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=5,
        check=False,
    )
    return completed.returncode == 0 and bool((completed.stdout or "").strip())


def parse_timestamp(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def split_config_command(command: str) -> list[str]:
    try:
        parts = shlex.split(str(command or ""), posix=os.name != "nt")
    except ValueError:
        return []
    return [part.strip("\"'") for part in parts if part.strip("\"'")]


def router_command_dry_run(intent_router: dict[str, Any]) -> dict[str, Any]:
    command = str(intent_router.get("command") or "").strip()
    args = split_config_command(command)
    if not args:
        return runtime_check(False, "router command missing or unparsable")
    if "--intent" not in args:
        args.append("--intent")
    work_dir = Path(str(intent_router.get("work_dir") or ROOT))
    timeout_raw = intent_router.get("timeout_seconds")
    try:
        timeout = int(timeout_raw)
    except (TypeError, ValueError):
        timeout = 10
    timeout = max(3, min(timeout, 10))
    try:
        completed = subprocess.run(
            args,
            input="你好 VELA",
            cwd=str(work_dir) if work_dir.exists() else str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return runtime_check(False, f"router command failed to start: {type(exc).__name__}")
    output = " ".join((completed.stdout or completed.stderr or "").split())[:240]
    ok = completed.returncode == 0 and "normal_chat" in output and not find_leaks(output)
    return runtime_check(ok, output or f"exit={completed.returncode}")


def latest_session_reply(sessions_dir: Path) -> dict[str, Any]:
    candidates: list[tuple[datetime, float, Path, str]] = []
    if not sessions_dir.exists():
        return {"content": "", "timestamp": "", "path": "", "age_hours": None, "leaks": []}
    for path in sessions_dir.glob("VELA*.json"):
        if ".bak-" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for session in (data.get("sessions") or {}).values():
            for item in session.get("history", []):
                if item.get("role") != "assistant" or not item.get("content"):
                    continue
                parsed = parse_timestamp(str(item.get("timestamp") or item.get("created_at") or ""))
                if parsed is None:
                    parsed = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                candidates.append((parsed, path.stat().st_mtime, path, str(item["content"])))
    if not candidates:
        return {"content": "", "timestamp": "", "path": "", "age_hours": None, "leaks": []}
    timestamp, _mtime, path, content = sorted(candidates, key=lambda item: (item[0], item[1]))[-1]
    age_hours = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600)
    return {
        "content": content,
        "timestamp": timestamp.isoformat(),
        "path": str(path),
        "age_hours": round(age_hours, 2),
        "leaks": find_leaks(content),
    }


def latest_inbound_message(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"timestamp": "", "found": False}
    latest: datetime | None = None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"timestamp": "", "found": False}
    for line in lines:
        if 'msg="message received"' not in line:
            continue
        match = CC_LOG_TIME_RE.search(line)
        parsed = parse_timestamp(match.group(1) if match else "")
        if parsed and (latest is None or parsed > latest):
            latest = parsed
    if latest is None:
        return {"timestamp": "", "found": False}
    return {"timestamp": latest.isoformat(), "found": True}


def weixin_poll_state(vela_project: dict[str, Any], *, max_age_minutes: int = 15) -> dict[str, Any]:
    platforms = [item for item in vela_project.get("platforms", []) if isinstance(item, dict)]
    weixin = next((item for item in platforms if item.get("type") == "weixin"), {})
    options = weixin.get("options") if isinstance(weixin.get("options"), dict) else {}
    state_dir_raw = str(options.get("state_dir") or "").strip()
    if not state_dir_raw:
        return runtime_check(False, "weixin state_dir missing")
    state_dir = Path(state_dir_raw)
    poll_file = state_dir / "get_updates.buf"
    if not poll_file.exists():
        return runtime_check(False, "weixin poll buffer missing")
    try:
        mtime = datetime.fromtimestamp(poll_file.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return runtime_check(False, "weixin poll buffer unreadable")
    age_minutes = max(0.0, (datetime.now(timezone.utc) - mtime).total_seconds() / 60)
    fresh = age_minutes <= max_age_minutes
    detail = f"poll buffer {'fresh' if fresh else 'stale'}: {age_minutes:.1f}m"
    return runtime_check(fresh, detail)


def run_runtime_audit(
    *,
    cc_home: Path | None = None,
    process_running: bool | None = None,
    max_session_age_hours: int = 48,
) -> dict[str, Any]:
    cc_home = cc_home or DEFAULT_CC_CONNECT_HOME
    config_path = cc_home / "config.toml"
    checks: dict[str, dict[str, Any]] = {}
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            checks["config"] = runtime_check(True, "cc-connect config loaded")
        except tomllib.TOMLDecodeError as exc:
            checks["config"] = runtime_check(False, f"config parse failed: {exc}")
    else:
        checks["config"] = runtime_check(False, "cc-connect config missing")

    projects = [item for item in config.get("projects", []) if isinstance(item, dict)]
    vela_project = next((item for item in projects if item.get("name") == "VELA"), {})
    intent_router = vela_project.get("intent_router") or {}
    router_command = str(intent_router.get("command") or "")
    checks["router_config"] = runtime_check(
        bool(intent_router.get("enabled")) and "vela_router.py" in router_command and "--stdin" in router_command,
        router_command,
    )
    checks["router_command_dry_run"] = (
        router_command_dry_run(intent_router)
        if checks["router_config"]["ok"]
        else runtime_check(False, "router config is not valid enough to dry-run")
    )
    checks["deepseek_runtime"] = deepseek_runtime_status()

    commands = {item.get("name"): item for item in config.get("commands", []) if isinstance(item, dict)}
    command_names = ("vela-router", "vela-talk")
    commands_ok = all("vela_router.py" in str((commands.get(name) or {}).get("exec") or "") for name in command_names)
    checks["commands"] = runtime_check(commands_ok, ", ".join(name for name in command_names if name in commands))
    checks["weixin_poll_state"] = weixin_poll_state(vela_project)

    running = detect_cc_connect_process() if process_running is None else bool(process_running)
    checks["cc_connect_process"] = runtime_check(running, "running" if running else "not running")

    latest_reply = latest_session_reply(cc_home / "sessions")
    age = latest_reply.get("age_hours")
    reply_recent = isinstance(age, (int, float)) and age <= max_session_age_hours
    reply_clean = bool(latest_reply.get("content")) and not latest_reply.get("leaks")
    latest_reply_detail = latest_session_reply_detail(
        latest_reply,
        max_session_age_hours=max_session_age_hours,
    )
    checks["latest_session_reply"] = runtime_check(
        reply_recent and reply_clean,
        latest_reply_detail,
    )

    inbound = latest_inbound_message(cc_home / "cc-connect.log")
    inbound_time = parse_timestamp(str(inbound.get("timestamp") or ""))
    checks["weixin_inbound_seen"] = runtime_check(
        bool(inbound_time),
        (
            f"Weixin inbound observed at {inbound_time.isoformat()}"
            if inbound_time
            else "no Weixin inbound message in cc-connect log; send a fresh WeChat prompt to verify live foreground"
        ),
    )
    reply_time = parse_timestamp(str(latest_reply.get("timestamp") or ""))
    inbound_ok = True
    inbound_detail = "no inbound message in cc-connect log"
    if inbound_time:
        inbound_ok = bool(reply_time and reply_time >= inbound_time)
        inbound_detail = (
            f"message received at {inbound_time.isoformat()} has a newer/equal session reply"
            if inbound_ok
            else f"message received at {inbound_time.isoformat()} is newer than latest VELA session reply"
        )
    checks["inbound_to_reply"] = runtime_check(inbound_ok, inbound_detail)

    failed = [name for name, check in checks.items() if not check["ok"]]
    return {
        "ok": not failed,
        "cc_home": str(cc_home),
        "checks": checks,
        "failed": failed,
        "next_action": runtime_next_action(failed),
        "latest_reply": {
            "timestamp": latest_reply.get("timestamp") or "",
            "age_hours": latest_reply.get("age_hours"),
            "preview": preview(str(latest_reply.get("content") or "")),
            "leaks": latest_reply.get("leaks") or [],
        },
        "latest_inbound": inbound,
    }


def wait_for_runtime_audit(
    *,
    cc_home: Path,
    timeout_seconds: float,
    poll_seconds: float = 2.0,
    process_running: bool | None = None,
    max_session_age_hours: int = 48,
    audit_fn=run_runtime_audit,
    sleep_fn=time.sleep,
    monotonic_fn=time.monotonic,
) -> dict[str, Any]:
    timeout_seconds = max(0.0, float(timeout_seconds))
    poll_seconds = max(0.2, float(poll_seconds))
    start = monotonic_fn()
    deadline = start + timeout_seconds
    attempts = 0
    status = "timed_out"
    report: dict[str, Any] = {}
    while True:
        attempts += 1
        report = audit_fn(
            cc_home=cc_home,
            process_running=process_running,
            max_session_age_hours=max_session_age_hours,
        )
        now = monotonic_fn()
        if report.get("ok"):
            status = "satisfied"
            break
        if now >= deadline:
            break
        sleep_fn(min(poll_seconds, max(0.0, deadline - now)))
    elapsed = max(0.0, monotonic_fn() - start)
    report = dict(report)
    report["wait"] = {
        "enabled": True,
        "status": status,
        "attempts": attempts,
        "timeout_seconds": round(timeout_seconds, 2),
        "elapsed_seconds": round(elapsed, 2),
    }
    return report


def required_tokens_present(text: str, tokens: list[str] | None) -> bool:
    if not tokens:
        return True
    return any(token in text for token in tokens)


def route_case(message: str) -> Any:
    return router.classify_intent(message)


def run_single_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    intent = route_case(case["message"])
    supporting_context = supporting_context_for(intent.name, case["message"])
    result = run_layered_response(
        case["message"],
        intent=intent.name,
        codex_summary=case.get("codex_summary", ""),
        log_dir=case_log_dir,
        reply_adapter=FallbackReplyAdapter(),
        supporting_context=supporting_context,
    )
    leaks = find_leaks(result.text)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(result.text, case.get("required_reply_tokens"))
    tool_boundary_ok = True
    if intent.name not in {"market_brief", "market_refresh"} and intent.market_allowed:
        tool_boundary_ok = False
    if intent.name != "codex_task" and intent.codex_allowed:
        tool_boundary_ok = False
    return {
        "id": case["id"],
        "kind": "single_turn",
        "message": case["message"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": bool(case.get("side_effects_allowed", True)),
        "bridge_executed": False,
        "reply_preview": preview(result.text),
        "latest_iteration_signal": latest_iteration_signal(case_log_dir),
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        "ok": route_ok and required_ok and tool_boundary_ok and not leaks,
    }


def run_entrypoint_single_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    intent = route_case(case["message"])
    original_run = router.run_layered_response
    original_refresh = router.schedule_market_refresh
    original_codex = router.render_codex_bridge

    def run_with_case_log(message: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("log_dir", case_log_dir)
        kwargs.setdefault("reply_adapter", FallbackReplyAdapter())
        return original_run(message, *args, **kwargs)

    def fake_refresh(_text: str) -> Any:
        return router.MarketRefreshJob(started=True, in_progress=False, pid=12345, reason="smoke_stub")

    def fake_codex(_text: str = "") -> str:
        return "K，VELA · CODEX 产品判断摘要\n事实：- Codex smoke 只验证路由。\n判断：路由正确，不执行真实桥接。"

    router.run_layered_response = run_with_case_log
    router.schedule_market_refresh = fake_refresh
    router.render_codex_bridge = fake_codex
    try:
        reply = router.reply_for(case["message"])
    finally:
        router.run_layered_response = original_run
        router.schedule_market_refresh = original_refresh
        router.render_codex_bridge = original_codex

    leaks = find_leaks(reply)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(reply, case.get("required_reply_tokens"))
    tool_boundary_ok = True
    if intent.name not in {"market_brief", "market_refresh"} and intent.market_allowed:
        tool_boundary_ok = False
    if intent.name != "codex_task" and intent.codex_allowed:
        tool_boundary_ok = False
    return {
        "id": case["id"],
        "kind": "entrypoint_single_turn",
        "message": case["message"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": bool(case.get("side_effects_allowed", True)),
        "bridge_executed": False,
        "reply_preview": preview(reply),
        "latest_iteration_signal": latest_iteration_signal(case_log_dir),
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        "ok": route_ok and required_ok and tool_boundary_ok and not leaks,
    }


def run_two_turn_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    run_layered_response(
        case["feedback"],
        intent="style_feedback",
        log_dir=case_log_dir,
        reply_adapter=FallbackReplyAdapter(),
    )
    intent = route_case(case["followup"])
    result = run_layered_response(
        case["followup"],
        intent=intent.name,
        log_dir=case_log_dir,
        reply_adapter=FallbackReplyAdapter(),
    )
    signal = latest_iteration_signal(case_log_dir)
    leaks = find_leaks(result.text)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(result.text, case.get("required_reply_tokens"))
    adapted = "preference_or_feedback_adapted" in signal.get("response_quality_signals", [])
    return {
        "id": case["id"],
        "kind": "two_turn",
        "message": case["followup"],
        "feedback": case["feedback"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": True,
        "bridge_executed": False,
        "reply_preview": preview(result.text),
        "latest_iteration_signal": signal,
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        "ok": route_ok and required_ok and adapted and not leaks,
    }


def run_entrypoint_two_turn_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    original_run = router.run_layered_response

    def run_with_case_log(message: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("log_dir", case_log_dir)
        kwargs.setdefault("reply_adapter", FallbackReplyAdapter())
        return original_run(message, *args, **kwargs)

    router.run_layered_response = run_with_case_log
    try:
        router.reply_for(case["feedback"])
        intent = route_case(case["followup"])
        reply = router.reply_for(case["followup"])
    finally:
        router.run_layered_response = original_run

    signal = latest_iteration_signal(case_log_dir)
    leaks = find_leaks(reply)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(reply, case.get("required_reply_tokens"))
    adapted = "preference_or_feedback_adapted" in signal.get("response_quality_signals", [])
    return {
        "id": case["id"],
        "kind": "entrypoint_two_turn",
        "message": case["followup"],
        "feedback": case["feedback"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": True,
        "bridge_executed": False,
        "reply_preview": preview(reply),
        "latest_iteration_signal": signal,
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        "ok": route_ok and required_ok and adapted and not leaks,
    }


def run_smoke_suite(
    log_dir: Path | None = None,
    *,
    use_entrypoint: bool = False,
    fake_deepseek_env: bool = False,
) -> dict[str, Any]:
    created_tmp: tempfile.TemporaryDirectory[str] | None = None
    if log_dir is None:
        created_tmp = tempfile.TemporaryDirectory()
        base_log_dir = Path(created_tmp.name)
    else:
        base_log_dir = Path(log_dir)
        base_log_dir.mkdir(parents=True, exist_ok=True)
    old_deepseek = os.environ.get("DEEPSEEK_API_KEY")
    if fake_deepseek_env:
        os.environ["DEEPSEEK_API_KEY"] = "smoke-deepseek-key"
    try:
        single_cases = [*SINGLE_TURN_CASES]
        if use_entrypoint:
            single_cases.extend(ENTRYPOINT_ONLY_CASES)
            cases = [run_entrypoint_single_case(case, base_log_dir) for case in single_cases]
            cases.extend(run_entrypoint_two_turn_case(case, base_log_dir) for case in TWO_TURN_CASES)
        else:
            cases = [run_single_case(case, base_log_dir) for case in single_cases]
            cases.extend(run_two_turn_case(case, base_log_dir) for case in TWO_TURN_CASES)
        failed = [case["id"] for case in cases if not case["ok"]]
        return {
            "ok": not failed,
            "entrypoint": use_entrypoint,
            "fake_deepseek_env": fake_deepseek_env,
            "case_count": len(cases),
            "failed": failed,
            "log_dir": str(base_log_dir),
            "cases": cases,
        }
    finally:
        if fake_deepseek_env:
            if old_deepseek is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old_deepseek
        if created_tmp is not None:
            created_tmp.cleanup()


def render_text_report(report: dict[str, Any]) -> str:
    lines = [
        f"VELA acceptance smoke: {'OK' if report['ok'] else 'FAIL'}",
        f"cases: {report['case_count']}",
    ]
    if report["failed"]:
        lines.append("failed: " + ", ".join(report["failed"]))
    for case in report["cases"]:
        mark = "OK" if case["ok"] else "FAIL"
        lines.append(f"- {mark} {case['id']} [{case['intent']}] {case['reply_preview']}")
    return "\n".join(lines)


def render_runtime_report(report: dict[str, Any]) -> str:
    lines = [
        f"VELA cc-connect runtime audit: {'OK' if report['ok'] else 'FAIL'}",
        f"cc_home: {report['cc_home']}",
    ]
    if report["failed"]:
        lines.append("failed: " + ", ".join(report["failed"]))
    for name, check in report["checks"].items():
        mark = "OK" if check["ok"] else "FAIL"
        detail = str(check.get("detail") or "")
        lines.append(f"- {mark} {name}: {detail}")
    latest = report.get("latest_reply") or {}
    if latest.get("preview"):
        lines.append(f"latest_reply: {latest['preview']}")
    wait = report.get("wait") or {}
    if wait.get("enabled"):
        lines.append(
            f"wait: {wait.get('status')} after {wait.get('attempts')} attempts "
            f"({wait.get('elapsed_seconds')}s/{wait.get('timeout_seconds')}s)"
        )
    next_action = report.get("next_action") or {}
    if next_action.get("kind") and next_action.get("kind") != "none":
        lines.append(f"next_action: {next_action['kind']}")
        prompts = next_action.get("prompts") or []
        if prompts:
            lines.append("prompts: " + " / ".join(str(item) for item in prompts))
        if next_action.get("verify_command"):
            lines.append(f"verify: {next_action['verify_command']}")
        if next_action.get("wait_command"):
            lines.append(f"wait_verify: {next_action['wait_command']}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VELA local foreground acceptance smoke scenarios.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--entrypoint", action="store_true", help="Run through router.reply_for with safe stubs.")
    parser.add_argument("--fake-deepseek-env", action="store_true", help="Set a temporary DeepSeek key sentinel during smoke.")
    parser.add_argument("--log-dir", type=Path, default=None, help="Use this learning-loop directory instead of a temp dir.")
    parser.add_argument("--runtime-audit", action="store_true", help="Audit local cc-connect runtime config/process/session state.")
    parser.add_argument("--cc-home", type=Path, default=DEFAULT_CC_CONNECT_HOME, help="cc-connect home directory for runtime audit.")
    parser.add_argument("--max-session-age-hours", type=int, default=48, help="Maximum acceptable age for latest VELA session reply.")
    parser.add_argument("--wait-live-seconds", type=float, default=0.0, help="When auditing runtime, wait this long for a fresh Weixin inbound and reply.")
    parser.add_argument("--wait-poll-seconds", type=float, default=2.0, help="Polling interval for --wait-live-seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.runtime_audit:
        if args.wait_live_seconds > 0:
            report = wait_for_runtime_audit(
                cc_home=args.cc_home,
                timeout_seconds=args.wait_live_seconds,
                poll_seconds=args.wait_poll_seconds,
                max_session_age_hours=args.max_session_age_hours,
            )
        else:
            report = run_runtime_audit(
                cc_home=args.cc_home,
                max_session_age_hours=args.max_session_age_hours,
            )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(render_runtime_report(report))
        return 0 if report["ok"] else 1
    report = run_smoke_suite(
        log_dir=args.log_dir,
        use_entrypoint=args.entrypoint,
        fake_deepseek_env=args.fake_deepseek_env,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
