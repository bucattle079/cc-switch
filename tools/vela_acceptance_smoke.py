from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import vela_router as router
from vela_product_layers import FallbackReplyAdapter, run_layered_response


LEAK_TOKENS = (
    "raw payload",
    "response_quality_signals",
    "active_persona_capabilities",
    "user_message_type",
    "DEEPSEEK_API_KEY",
    "api_key",
    "endpoint",
    "schema",
    "debug",
    "cosplay",
    "台词",
    "扮演",
)

WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\")
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
        "id": "weather_jinjiang",
        "message": "明天晋江会不会下雨，能不能出门",
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

    def fake_codex() -> str:
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VELA local foreground acceptance smoke scenarios.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--entrypoint", action="store_true", help="Run through router.reply_for with safe stubs.")
    parser.add_argument("--fake-deepseek-env", action="store_true", help="Set a temporary DeepSeek key sentinel during smoke.")
    parser.add_argument("--log-dir", type=Path, default=None, help="Use this learning-loop directory instead of a temp dir.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
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
