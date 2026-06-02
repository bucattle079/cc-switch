import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SMOKE = TOOLS / "vela_acceptance_smoke.py"


def load_smoke_module():
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("vela_acceptance_smoke_test", SMOKE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaAcceptanceSmokeTests(unittest.TestCase):
    def test_smoke_runner_covers_routes_feedback_and_foreground_boundaries(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp:
            report = smoke.run_smoke_suite(log_dir=Path(tmp))

        self.assertTrue(report["ok"], report)
        scenario_ids = {case["id"] for case in report["cases"]}
        for required in {
            "normal_hello",
            "normal_one_next_step",
            "daily_info_plain_sort",
            "weather_jinjiang",
            "weather_new_york_cold",
            "market_add_position",
            "market_current_a_share_realtime_compact",
            "market_no_raw_english",
            "freshness_status",
            "codex_status_route_only",
            "project_augsun_continue",
            "deep_autopsy_vela",
            "identity_memory_boundary",
            "sensitive_memory_guard",
            "style_feedback_no_customer_voice",
            "daily_info_real_decision_filter",
            "weather_schedule_boundary",
            "weather_trip_customer_plan",
            "market_policy_not_news_list",
            "market_position_risk_not_news_list",
            "market_impulse_brake",
            "codex_git_noise_boundary",
            "codex_progress_no_logs",
            "project_followup_minimum_action",
            "project_minimum_loop",
            "deep_root_cause_not_mysticism",
            "style_feedback_say_human",
            "memory_confirm_market_preference",
            "feedback_smarter_then_hello",
            "feedback_misread_then_hello",
            "feedback_push_then_continue",
            "feedback_too_long_then_continue",
            "feedback_too_cold_then_hello",
            "feedback_customer_voice_then_continue",
        }:
            self.assertIn(required, scenario_ids)
        self.assertGreaterEqual(report["case_count"], 23)

        for case in report["cases"]:
            with self.subTest(case["id"]):
                self.assertTrue(case["ok"], case)
                self.assertEqual(case["intent"], case["expected_intent"])
                self.assertFalse(case["leaks"], case)
                self.assertNotIn("response_quality_signals", case["reply_preview"])
                self.assertNotIn("active_persona_capabilities", case["reply_preview"])

        two_turn_cases = [case for case in report["cases"] if case["kind"] == "two_turn"]
        self.assertTrue(two_turn_cases)
        for case in two_turn_cases:
            with self.subTest(case["id"]):
                self.assertIn("preference_or_feedback_adapted", case["latest_iteration_signal"]["response_quality_signals"])
                self.assertTrue(any(token in case["reply_preview"] for token in ("我在", "在。", "听着", "继续", "上一轮", "阻塞", "一个动作", "接着来")))
                for self_label in ("少菜单", "直接给判断", "不解释身份", "废话收短", "不摆路牌", "少解释", "机械味", "不像提示牌"):
                    self.assertNotIn(self_label, case["reply_preview"])

        codex = next(case for case in report["cases"] if case["id"] == "codex_status_route_only")
        self.assertFalse(codex["side_effects_allowed"])
        self.assertFalse(codex["bridge_executed"])

        memory_confirm = next(case for case in report["cases"] if case["id"] == "memory_confirm_market_preference")
        self.assertTrue(memory_confirm["confirmed_preference_written"], memory_confirm)
        self.assertIn("A股", memory_confirm["reply_preview"])
        self.assertNotIn("候选记忆", memory_confirm["reply_preview"])
        self.assertNotIn("schema", memory_confirm["reply_preview"])

    def test_smoke_runner_cli_json_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [sys.executable, "-X", "utf8", str(SMOKE), "--json", "--log-dir", tmp],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False, indent=2))
        self.assertGreaterEqual(report["case_count"], 8)
        self.assertNotIn("DEEPSEEK_API_KEY", completed.stdout)
        self.assertNotIn("raw payload", completed.stdout.lower())

    def test_foreground_leak_detector_flags_mojibake_text(self):
        smoke = load_smoke_module()

        leaks = smoke.find_leaks("K锛屽湪銆傚皯鑿滃崟锛岀洿鎺ョ湅鐩爣銆?")

        self.assertIn("mojibake", leaks)

    def test_entrypoint_smoke_keeps_hard_lanes_local_when_deepseek_env_exists(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp:
            report = smoke.run_smoke_suite(log_dir=Path(tmp), use_entrypoint=True, fake_deepseek_env=True)

        self.assertTrue(report["ok"], report)
        self.assertTrue(report["entrypoint"])
        hard_lane_ids = {
            "weather_jinjiang",
            "market_add_position",
            "market_current_a_share_realtime_compact",
            "freshness_status",
        }
        now_info_ids = {
            "market_current_now_info_realtime_compact",
            "market_current_news_realtime_compact",
            "market_current_us_info_not_a_share",
            "market_current_global_not_a_share",
        }
        current_daily_info_ids = {
            "daily_info_now_general_news_uses_deepseek_chain",
            "daily_info_now_search_policy_uses_deepseek_chain",
            "daily_info_now_policy_question_uses_deepseek_chain",
            "daily_info_now_search_openai_uses_deepseek_chain",
            "daily_info_now_company_notice_uses_deepseek_chain",
            "daily_info_now_app_update_uses_deepseek_chain",
            "world_info_now_event_not_market",
            "weather_now_new_york_uses_deepseek_chain",
        }
        for case in report["cases"]:
            if case["id"] in hard_lane_ids:
                with self.subTest(case["id"]):
                    self.assertIn(
                        case["latest_quality_log"]["quality_flags"][1],
                        {"adapter:fallback", "adapter:local_status", "adapter:local_market"},
                    )
                    self.assertNotEqual(case["latest_quality_log"]["quality_flags"][1], "adapter:deepseek_chat")
                    if case["id"].startswith("market_"):
                        self.assertIn("实时源", case["reply_preview"])
                    else:
                        self.assertIn("实时源：未接入", case["reply_preview"])
                    self.assertFalse(case["leaks"], case)
            if case["id"] in now_info_ids:
                with self.subTest(case["id"]):
                    adapter_flag = case["latest_quality_log"]["quality_flags"][1]
                    self.assertIn(adapter_flag, {"adapter:deepseek_chat", "adapter:fallback_current_info_fallback"})
                    self.assertNotEqual(adapter_flag, "adapter:local_market")
                    self.assertIn("实时源", case["reply_preview"])
                    self.assertFalse(case["leaks"], case)
            if case["id"] in current_daily_info_ids:
                with self.subTest(case["id"]):
                    adapter_flag = case["latest_quality_log"]["quality_flags"][1]
                    self.assertIn(adapter_flag, {"adapter:deepseek_chat", "adapter:fallback_current_info_fallback"})
                    self.assertNotIn(adapter_flag, {"adapter:local_market", "adapter:local_status"})
                    self.assertIn("DeepSeek API", case["reply_preview"])
                    self.assertNotIn("状态边界", case["reply_preview"])
                    self.assertFalse(case["leaks"], case)

        refresh = next(case for case in report["cases"] if case["id"] == "market_refresh_entry")
        self.assertEqual(refresh["latest_quality_log"]["quality_flags"][1], "adapter:local_status")
        self.assertFalse(refresh["bridge_executed"])

    def test_entrypoint_smoke_marks_interactions_as_acceptance_smoke(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            report = smoke.run_smoke_suite(log_dir=log_dir, use_entrypoint=True, fake_deepseek_env=True)
            rows = []
            for path in [*log_dir.glob("*/interaction-*.jsonl"), *log_dir.glob("*/session-notes-*.jsonl")]:
                rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

        self.assertTrue(report["ok"], report)
        self.assertTrue(rows)
        self.assertTrue(all(row.get("source") == "acceptance_smoke" for row in rows))

    def test_entrypoint_smoke_reports_speed_lane_budgets(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp:
            report = smoke.run_smoke_suite(log_dir=Path(tmp), use_entrypoint=True, fake_deepseek_env=True)

        by_id = {case["id"]: case for case in report["cases"]}
        fast_ids = {"normal_hello", "normal_one_next_step", "freshness_status"}
        cached_ids = {
            "market_add_position",
            "market_current_a_share_realtime_compact",
            "market_current_now_info_realtime_compact",
            "market_current_news_realtime_compact",
            "market_current_us_info_not_a_share",
            "market_current_global_not_a_share",
            "market_no_raw_english",
            "market_policy_not_news_list",
            "market_impulse_brake",
            "market_refresh_entry",
        }

        for case_id in fast_ids:
            with self.subTest(case_id):
                case = by_id[case_id]
                self.assertEqual(case["latency_budget_ms"], 2000)
                self.assertTrue(case["latency_ok"], case)
                self.assertGreaterEqual(case["latency_ms"], 0)
                self.assertLessEqual(case["latency_ms"], case["latency_budget_ms"])
                self.assertIn("tool_lane:fast", case["latest_quality_log"]["quality_flags"])

        for case_id in cached_ids:
            with self.subTest(case_id):
                case = by_id[case_id]
                self.assertEqual(case["latency_budget_ms"], 8000)
                self.assertTrue(case["latency_ok"], case)
                self.assertGreaterEqual(case["latency_ms"], 0)
                self.assertLessEqual(case["latency_ms"], case["latency_budget_ms"])
                self.assertIn("tool_lane:cached", case["latest_quality_log"]["quality_flags"])

    def test_smoke_runner_checks_market_impulse_compactness(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp:
            report = smoke.run_smoke_suite(log_dir=Path(tmp), use_entrypoint=True, fake_deepseek_env=True)

        by_id = {case["id"]: case for case in report["cases"]}
        impulse = by_id["market_impulse_brake"]
        self.assertTrue(impulse["ok"], impulse)
        self.assertLessEqual(impulse["reply_chars"], 520)
        self.assertTrue(impulse["max_reply_chars_ok"], impulse)
        self.assertEqual(impulse["forbidden_reply_tokens_found"], [])

    def test_smoke_runner_checks_project_risk_count(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp:
            report = smoke.run_smoke_suite(log_dir=Path(tmp), use_entrypoint=True, fake_deepseek_env=True)

        by_id = {case["id"]: case for case in report["cases"]}
        project = by_id["project_augsun_continue"]
        self.assertTrue(project["ok"], project)
        self.assertGreaterEqual(project["risk_bullets"], 3)
        self.assertTrue(project["min_risk_bullets_ok"], project)

    def test_runtime_audit_reports_router_config_and_live_process_gap(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            sessions = cc_home / "sessions"
            sessions.mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                """
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args:VELA}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"
work_dir = "C:/Users/Admin/Desktop/CC-WECHAT"
timeout_seconds = 75
""".strip(),
                encoding="utf-8",
            )
            stale_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            (sessions / "VELA_test.json").write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {
                                        "role": "assistant",
                                        "content": "K，在。少菜单，直接看目标。",
                                        "timestamp": stale_time,
                                    }
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=False,
                max_session_age_hours=24,
            )

        self.assertFalse(report["ok"])
        self.assertTrue(report["checks"]["config"]["ok"])
        self.assertTrue(report["checks"]["router_config"]["ok"])
        self.assertTrue(report["checks"]["commands"]["ok"])
        self.assertFalse(report["checks"]["cc_connect_process"]["ok"])
        self.assertFalse(report["checks"]["latest_session_reply"]["ok"])
        self.assertIn("stale", report["checks"]["latest_session_reply"]["detail"])
        self.assertIn("fresh WeChat prompt", report["checks"]["latest_session_reply"]["detail"])
        self.assertIn("cc_connect_process", report["failed"])
        self.assertIn("latest_session_reply", report["failed"])
        self.assertEqual(report["latest_reply"]["leaks"], [])

    def test_runtime_audit_reports_learning_loop_state(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            learning_loop = Path(tmp) / "VELA" / "learning-loop"
            (cc_home / "sessions").mkdir(parents=True)
            learning_loop.mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                """
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args:VELA}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"
""".strip(),
                encoding="utf-8",
            )
            rows_by_file = {
                "session-notes-2026-06-01.jsonl": [{"level": "Session Notes", "summary": "short context"}],
                "interaction-2026-06-01.jsonl": [{"level": "Interaction Log", "message_summary": "hello"}],
                "human-iteration-2026-06-01.jsonl": [{"response_quality_signals": ["preference_or_feedback_adapted"]}],
                "memory-candidates-2026-06-01.jsonl": [
                    {"level": "Preference Candidate", "classification": "style_feedback", "summary": "less robotic"},
                    {"level": "Strategic Memory Candidate", "classification": "strategic_goal", "summary": "AugSun minimum loop"},
                ],
                "strategic-memory-2026-06-01.jsonl": [
                    {"level": "Strategic Memory", "memory_type": "project_goal", "summary": "confirmed direction"}
                ],
            }
            for filename, rows in rows_by_file.items():
                (learning_loop / filename).write_text(
                    "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                    encoding="utf-8",
                )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=False,
                max_session_age_hours=9999,
                learning_loop_dir=learning_loop,
            )

        check = report["checks"]["learning_loop_state"]
        self.assertTrue(check["ok"], report)
        for token in [
            "Session Notes",
            "Interaction Log",
            "Preference Candidate",
            "Style Feedback Candidate",
            "Strategic Memory Candidate",
            "Strategic Memory",
        ]:
            self.assertIn(token, check["detail"])
        self.assertNotIn("confirmed direction", check["detail"])

    def test_runtime_audit_cli_json_reports_nonzero_for_live_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            (cc_home / "sessions").mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                """
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args:VELA}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"
""".strip(),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(SMOKE),
                    "--runtime-audit",
                    "--json",
                    "--cc-home",
                    str(cc_home),
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )

        report = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(report["ok"])
        self.assertIn("latest_session_reply", report["failed"])
        self.assertTrue(report["failed"])
        self.assertNotIn("DEEPSEEK_API_KEY", completed.stdout)

    def test_runtime_audit_cli_wait_json_reports_wait_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            (cc_home / "sessions").mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                """
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args:VELA}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"
""".strip(),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(SMOKE),
                    "--runtime-audit",
                    "--json",
                    "--wait-live-seconds",
                    "0.1",
                    "--wait-poll-seconds",
                    "0.05",
                    "--cc-home",
                    str(cc_home),
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )

        report = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(report["wait"]["status"], "timed_out")
        self.assertGreaterEqual(report["wait"]["attempts"], 1)
        self.assertIn("next_action", report)

    def test_runtime_process_detector_checks_patched_cc_connect_binary(self):
        smoke = load_smoke_module()
        calls = []
        original_run = smoke.subprocess.run

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="24272\n", stderr="")

        smoke.subprocess.run = fake_run
        try:
            detected = smoke.detect_cc_connect_process()
        finally:
            smoke.subprocess.run = original_run

        self.assertTrue(detected)
        command_text = " ".join(calls[0])
        self.assertIn("cc-connect", command_text)
        self.assertIn("cc-connect-patched", command_text)

    def test_runtime_audit_flags_multiple_cc_connect_processes(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            (cc_home / "sessions").mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                """
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args:VELA}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"
""".strip(),
                encoding="utf-8",
            )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                process_count=2,
                max_session_age_hours=9999,
            )

        self.assertFalse(report["checks"]["cc_connect_process"]["ok"])
        self.assertIn("multiple", report["checks"]["cc_connect_process"]["detail"])
        self.assertIn("count=2", report["checks"]["cc_connect_process"]["detail"])
        self.assertIn("cc_connect_process", report["failed"])

    def test_runtime_audit_flags_inbound_message_newer_than_session_reply(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            sessions = cc_home / "sessions"
            sessions.mkdir(parents=True)
            state_dir = cc_home / "weixin" / "codex-wechat" / "bot"
            state_dir.mkdir(parents=True)
            context_tokens = state_dir / "context_tokens.json"
            context_tokens.write_text('{"opaque":"cursor"}', encoding="utf-8")
            (cc_home / "config.toml").write_text(
                f"""
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args}}}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args:VELA}}}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"

[[projects.platforms]]
type = "weixin"

[projects.platforms.options]
state_dir = "{str(state_dir).replace("\\", "/")}"
""".strip(),
                encoding="utf-8",
            )
            session_file = sessions / "VELA_test.json"
            session_file.write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {
                                        "role": "assistant",
                                        "content": "K，在。少菜单，直接看目标。",
                                        "timestamp": "2026-06-01T00:00:00+00:00",
                                    }
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            older_than_inbound = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc).timestamp()
            os.utime(session_file, (older_than_inbound, older_than_inbound))
            os.utime(context_tokens, (older_than_inbound, older_than_inbound))
            (cc_home / "cc-connect.log").write_text(
                'time=2026-06-01T09:00:00+08:00 level=INFO msg="message received" platform=weixin content_len=6\n',
                encoding="utf-8",
            )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                max_session_age_hours=9999,
            )

        self.assertFalse(report["ok"])
        self.assertIn("inbound_to_reply", report["failed"])
        self.assertFalse(report["checks"]["inbound_to_reply"]["ok"])
        self.assertIn("message received", report["checks"]["inbound_to_reply"]["detail"])
        self.assertNotIn("content_len", report["checks"]["inbound_to_reply"]["detail"])
        self.assertIn("weixin_dispatch_trace", report["failed"])
        trace = report["checks"]["weixin_dispatch_trace"]["detail"]
        self.assertIn("session_file_after_inbound=no", trace)
        self.assertIn("context_tokens_after_inbound=no", trace)
        self.assertNotIn("opaque", json.dumps(report, ensure_ascii=False))
        self.assertNotIn(str(state_dir), json.dumps(report, ensure_ascii=False))
        self.assertEqual(report["next_action"]["kind"], "inspect_weixin_reply_dispatch")
        self.assertIn("inbound_to_reply", report["next_action"]["checks"])
        self.assertIn("weixin_dispatch_trace", report["next_action"]["checks"])
        self.assertIn("cc_connect_process", report["next_action"]["checks"])

    def test_runtime_audit_flags_latest_weixin_inbound_without_router_dispatch(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            sessions = cc_home / "sessions"
            sessions.mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                """
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args:VELA}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"
""".strip(),
                encoding="utf-8",
            )
            session_file = sessions / "VELA_test.json"
            session_file.write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {
                                        "role": "assistant",
                                        "content": "K，在。",
                                        "timestamp": "2026-06-01T00:00:00+00:00",
                                    }
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cc_home / "cc-connect.log").write_text(
                "\n".join(
                    [
                        'time=2026-06-01T20:47:31+08:00 level=INFO msg="message received" platform=weixin content_len=4',
                        'time=2026-06-01T20:47:31+08:00 level=INFO msg="audit: command_executed" platform=weixin project=VELA command=vela-router type=custom',
                        'time=2026-06-01T20:47:38+08:00 level=INFO msg="message received" platform=weixin content_len=24',
                    ]
                ),
                encoding="utf-8",
            )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                max_session_age_hours=9999,
            )

        self.assertFalse(report["checks"]["weixin_command_dispatch"]["ok"])
        self.assertIn("latest Weixin inbound", report["checks"]["weixin_command_dispatch"]["detail"])
        self.assertIn("weixin_command_dispatch", report["failed"])
        self.assertEqual(report["next_action"]["kind"], "inspect_weixin_reply_dispatch")
        self.assertIn("weixin_command_dispatch", report["next_action"]["checks"])

    def test_runtime_audit_treats_inbound_before_service_start_as_not_current(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            sessions = cc_home / "sessions"
            sessions.mkdir(parents=True)
            state_dir = cc_home / "weixin" / "codex-wechat" / "bot"
            state_dir.mkdir(parents=True)
            (state_dir / "get_updates.buf").write_text("poll", encoding="utf-8")
            (cc_home / "config.toml").write_text(
                f"""
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args}}}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args:VELA}}}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"

[[projects.platforms]]
type = "weixin"

[projects.platforms.options]
state_dir = "{str(state_dir).replace("\\", "/")}"
""".strip(),
                encoding="utf-8",
            )
            (sessions / "VELA_test.json").write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {
                                        "role": "assistant",
                                        "content": "K，在。",
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                    }
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cc_home / "cc-connect.log").write_text(
                "\n".join(
                    [
                        'time=2026-06-01T20:47:38+08:00 level=INFO msg="message received" platform=weixin content_len=24',
                        'time=2026-06-01T20:47:39+08:00 level=INFO msg="audit: command_executed" platform=weixin project=VELA command=vela-router type=custom',
                    ]
                ),
                encoding="utf-8",
            )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                process_started_at="2026-06-01T21:08:40+08:00",
                max_session_age_hours=24,
            )

        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["weixin_inbound_seen"]["ok"])
        self.assertIn("older than current cc-connect process start", report["checks"]["weixin_inbound_seen"]["detail"])
        self.assertTrue(report["checks"]["weixin_command_dispatch"]["ok"])
        self.assertEqual(report["checks"]["weixin_command_dispatch"]["detail"], "no inbound to trace")
        self.assertTrue(report["checks"]["inbound_to_reply"]["ok"])
        self.assertEqual(report["next_action"]["kind"], "send_weixin_prompt")
        self.assertIn("你好", report["next_action"]["prompts"])
        self.assertIn("你好 VELA", report["next_action"]["prompts"])
        self.assertIn("现在DeepSeek有什么新消息", report["next_action"]["prompts"])
        self.assertIn("现在小米汽车有什么公告", report["next_action"]["prompts"])
        self.assertIn("现在ChatGPT有什么更新", report["next_action"]["prompts"])
        self.assertIn("现在纽约冷吗", report["next_action"]["prompts"])
        self.assertIn("现在帮我查这个政策", report["next_action"]["prompts"])
        self.assertIn("明天晋江天气", report["next_action"]["prompts"])
        self.assertIn("继续 VELA 项目", report["next_action"]["prompts"])
        self.assertNotIn("继续 AugSun 项目", report["next_action"]["prompts"])
        self.assertIn("你太像机器人了", report["next_action"]["prompts"])
        self.assertIn("地狱验尸一下 VELA 为什么不智能", report["next_action"]["prompts"])
        self.assertEqual(report["latest_inbound"]["timestamp"], "2026-06-01T12:47:38+00:00")
        self.assertEqual(report["latest_inbound"]["current_window_timestamp"], "")
        self.assertEqual(report["latest_inbound"]["service_started_at"], "2026-06-01T13:08:40+00:00")

    def test_runtime_audit_accepts_logged_inbound_router_dispatch(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "cc-connect.log"
            log_path.write_text(
                "\n".join(
                    [
                        'time=2026-06-01T20:47:38+08:00 level=INFO msg="message received" platform=weixin content_len=24',
                        'time=2026-06-01T20:47:39+08:00 level=INFO msg="audit: command_executed" platform=weixin project=VELA command=inbound-router type=inbound_router',
                    ]
                ),
                encoding="utf-8",
            )

            check = smoke.weixin_command_dispatch(
                log_path,
                smoke.parse_timestamp("2026-06-01T20:47:38+08:00"),
            )

        self.assertTrue(check["ok"])
        self.assertIn("dispatched", check["detail"])
        self.assertIn("inbound-router", check["detail"])

    def test_runtime_audit_accepts_inbound_router_direct_reply_without_session_write(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            sessions = cc_home / "sessions"
            sessions.mkdir(parents=True)
            state_dir = cc_home / "weixin" / "codex-wechat" / "bot"
            state_dir.mkdir(parents=True)
            (state_dir / "get_updates.buf").write_text("poll", encoding="utf-8")
            context_tokens = state_dir / "context_tokens.json"
            context_tokens.write_text('{"moved":true}', encoding="utf-8")
            (cc_home / "config.toml").write_text(
                f"""
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args}}}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args:VELA}}}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"

[[projects.platforms]]
type = "weixin"

[projects.platforms.options]
state_dir = "{str(state_dir).replace("\\", "/")}"
""".strip(),
                encoding="utf-8",
            )
            (sessions / "VELA_test.json").write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {
                                        "role": "assistant",
                                        "content": "旧的干净回复。",
                                        "timestamp": "2026-06-01T00:00:00+00:00",
                                    }
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            inbound_time = datetime(2026, 6, 1, 12, 47, 38, tzinfo=timezone.utc).timestamp()
            after_inbound = datetime(2026, 6, 1, 12, 47, 40, tzinfo=timezone.utc).timestamp()
            os.utime(context_tokens, (after_inbound, after_inbound))
            (cc_home / "cc-connect.log").write_text(
                "\n".join(
                    [
                        'time=2026-06-01T20:47:38+08:00 level=INFO msg="message received" platform=weixin content_len=24',
                        'time=2026-06-01T20:47:39+08:00 level=INFO msg="audit: command_executed" platform=weixin project=VELA command=inbound-router type=inbound_router',
                    ]
                ),
                encoding="utf-8",
            )
            fresh_poll = datetime.now(timezone.utc).timestamp()
            os.utime(state_dir / "get_updates.buf", (fresh_poll, fresh_poll))
            os.utime(sessions / "VELA_test.json", (inbound_time - 3600, inbound_time - 3600))

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                max_session_age_hours=1,
            )

        self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False, indent=2))
        self.assertTrue(report["checks"]["latest_session_reply"]["ok"])
        self.assertIn("direct foreground path", report["checks"]["latest_session_reply"]["detail"])
        self.assertTrue(report["checks"]["inbound_to_reply"]["ok"])
        self.assertIn("direct replies may not write", report["checks"]["inbound_to_reply"]["detail"])
        self.assertNotIn("latest_session_reply", report["failed"])
        self.assertNotIn("inbound_to_reply", report["failed"])

    def test_runtime_audit_accepts_local_foreground_proof_when_cc_log_is_stale(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cc_home = root / ".cc-connect"
            sessions = cc_home / "sessions"
            sessions.mkdir(parents=True)
            state_dir = cc_home / "weixin" / "codex-wechat" / "bot"
            state_dir.mkdir(parents=True)
            learning_loop = root / "VELA" / "learning-loop"
            send_once = root / "VELA" / "send-once"
            learning_loop.mkdir(parents=True)
            send_once.mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                f"""
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args}}}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args:VELA}}}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"

[[projects.platforms]]
type = "weixin"

[projects.platforms.options]
state_dir = "{str(state_dir).replace("\\", "/")}"
""".strip(),
                encoding="utf-8",
            )
            (sessions / "VELA_test.json").write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {
                                        "role": "assistant",
                                        "content": "旧的干净回复。",
                                        "timestamp": "2026-05-25T03:36:19+00:00",
                                    }
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service_started = datetime(2026, 6, 2, 3, 45, 0, tzinfo=timezone.utc)
            claim_time = datetime(2026, 6, 2, 3, 51, 37, 904581, tzinfo=timezone.utc)
            reply_time = datetime(2026, 6, 2, 3, 51, 38, 80840, tzinfo=timezone.utc)
            state_time = claim_time.timestamp()
            (state_dir / "context_tokens.json").write_text('{"moved":true}', encoding="utf-8")
            (state_dir / "get_updates.buf").write_text("poll", encoding="utf-8")
            os.utime(state_dir / "context_tokens.json", (state_time, state_time))
            fresh_poll = datetime.now(timezone.utc).timestamp()
            os.utime(state_dir / "get_updates.buf", (fresh_poll, fresh_poll))
            (cc_home / "cc-connect.log").write_text(
                'time=2026-06-01T20:47:38+08:00 level=INFO msg="message received" platform=weixin content_len=24',
                encoding="utf-8",
            )
            (send_once / "last-claim.json").write_text(
                json.dumps(
                    {
                        "created_at": claim_time.isoformat(),
                        "intent": "normal_chat",
                        "message_preview": "你好 VELA",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            rows_by_file = {
                "session-notes-2026-06-02.jsonl": [{"level": "Session Notes", "summary": "你好 VELA"}],
                "interaction-2026-06-02.jsonl": [
                    {
                        "created_at": reply_time.isoformat(),
                        "level": "Interaction Log",
                        "message_summary": "你好 VELA",
                        "intent": "normal_chat",
                        "response_preview": "K，在。先不推你，话从哪里开始都行。",
                    }
                ],
                "human-iteration-2026-06-02.jsonl": [{"response_quality_signals": ["foreground_reply_clean"]}],
                "memory-candidates-2026-06-02.jsonl": [
                    {"level": "Preference Candidate", "classification": "style_feedback", "summary": "less robotic"}
                ],
                "strategic-memory-2026-06-02.jsonl": [
                    {"level": "Strategic Memory", "memory_type": "project_goal", "summary": "confirmed VELA direction"}
                ],
            }
            for filename, rows in rows_by_file.items():
                (learning_loop / filename).write_text(
                    "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                    encoding="utf-8",
                )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                process_started_at=service_started,
                max_session_age_hours=24,
                learning_loop_dir=learning_loop,
            )

        self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False, indent=2))
        self.assertTrue(report["checks"]["latest_session_reply"]["ok"])
        self.assertIn("learning-loop", report["checks"]["latest_session_reply"]["detail"])
        self.assertTrue(report["checks"]["weixin_inbound_seen"]["ok"])
        self.assertIn("local foreground proof", report["checks"]["weixin_inbound_seen"]["detail"])
        self.assertTrue(report["checks"]["weixin_command_dispatch"]["ok"])
        self.assertIn("send-once", report["checks"]["weixin_command_dispatch"]["detail"])
        self.assertTrue(report["checks"]["inbound_to_reply"]["ok"])
        self.assertEqual(report["latest_reply"]["preview"], "K，在。先不推你，话从哪里开始都行。")
        self.assertEqual(report["latest_inbound"]["source"], "local_foreground_proof")
        self.assertNotIn("weixin_inbound_seen", report["failed"])

    def test_runtime_audit_requires_weixin_inbound_not_only_internal_session_send(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            sessions = cc_home / "sessions"
            sessions.mkdir(parents=True)
            state_dir = cc_home / "weixin" / "codex-wechat" / "bot"
            state_dir.mkdir(parents=True)
            (state_dir / "get_updates.buf").write_text("opaque-poll-cursor", encoding="utf-8")
            (cc_home / "config.toml").write_text(
                f"""
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args}}}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args:VELA}}}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"

[[projects.platforms]]
type = "weixin"

[projects.platforms.options]
state_dir = "{str(state_dir).replace("\\", "/")}"
token = "test-token"
""".strip(),
                encoding="utf-8",
            )
            (sessions / "VELA_test.json").write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {
                                        "role": "assistant",
                                        "content": "K，在。少菜单，直接看目标。",
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                    }
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                max_session_age_hours=24,
            )

        self.assertFalse(report["ok"])
        self.assertTrue(report["checks"]["latest_session_reply"]["ok"])
        self.assertFalse(report["checks"]["weixin_inbound_seen"]["ok"])
        self.assertIn("weixin_inbound_seen", report["failed"])
        self.assertNotIn("latest_session_reply", report["failed"])
        self.assertIn("fresh WeChat prompt", report["checks"]["weixin_inbound_seen"]["detail"])
        self.assertEqual(report["next_action"]["kind"], "send_weixin_prompt")
        self.assertIn("你好 VELA", report["next_action"]["prompts"])
        self.assertIn("现在DeepSeek有什么新消息", report["next_action"]["prompts"])
        self.assertIn("现在小米汽车有什么公告", report["next_action"]["prompts"])
        self.assertIn("现在ChatGPT有什么更新", report["next_action"]["prompts"])
        self.assertIn("现在纽约冷吗", report["next_action"]["prompts"])
        self.assertIn("现在帮我查这个政策", report["next_action"]["prompts"])
        self.assertIn("明天晋江天气", report["next_action"]["prompts"])
        self.assertIn("继续 VELA 项目", report["next_action"]["prompts"])
        self.assertNotIn("继续 AugSun 项目", report["next_action"]["prompts"])
        self.assertIn("你太像机器人了", report["next_action"]["prompts"])
        self.assertIn("地狱验尸一下 VELA 为什么不智能", report["next_action"]["prompts"])
        feedback_index = report["next_action"]["prompts"].index("你太像机器人了")
        self.assertEqual(report["next_action"]["prompts"][feedback_index + 1], "你好")
        self.assertIn("--runtime-audit --json", report["next_action"]["verify_command"])
        self.assertIn("--wait-live-seconds 90", report["next_action"]["wait_command"])
        rendered = smoke.render_runtime_report(report)
        self.assertIn("next_action: send_weixin_prompt", rendered)
        self.assertIn("你好 VELA", rendered)
        self.assertIn("现在DeepSeek有什么新消息", rendered)
        self.assertIn("现在小米汽车有什么公告", rendered)
        self.assertIn("现在ChatGPT有什么更新", rendered)
        self.assertIn("现在纽约冷吗", rendered)
        self.assertIn("现在帮我查这个政策", rendered)
        self.assertIn("明天晋江天气", rendered)
        self.assertIn("继续 VELA 项目", rendered)
        self.assertNotIn("继续 AugSun 项目", rendered)
        self.assertIn("你太像机器人了", rendered)
        self.assertIn("地狱验尸一下 VELA 为什么不智能", rendered)
        self.assertIn("wait_verify:", rendered)

    def test_runtime_audit_dry_runs_configured_router_command(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            (cc_home / "sessions").mkdir(parents=True)
            command = f'"{sys.executable}" -X utf8 "{ROOT / "tools" / "vela_router.py"}" --stdin'
            (cc_home / "config.toml").write_text(
                f"""
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args}}}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args:VELA}}}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = '{command.replace("\\", "/")}'
work_dir = "{str(ROOT).replace("\\", "/")}"
timeout_seconds = 75
""".strip(),
                encoding="utf-8",
            )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                max_session_age_hours=9999,
            )

        self.assertTrue(report["checks"]["router_command_dry_run"]["ok"], report)
        self.assertIn("normal_chat", report["checks"]["router_command_dry_run"]["detail"])
        self.assertNotIn("DEEPSEEK_API_KEY", json.dumps(report, ensure_ascii=False))

    def test_runtime_audit_reports_deepseek_runtime_without_secret_or_endpoint(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            (cc_home / "sessions").mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                """
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args:VELA}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"
""".strip(),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEY": "sk-deepseek-secret",
                    "DEEPSEEK_MODEL": "deepseek-chat",
                    "DEEPSEEK_BASE_URL": "https://proxy.example/v1",
                },
                clear=True,
            ):
                report = smoke.run_runtime_audit(
                    cc_home=cc_home,
                    process_running=True,
                    max_session_age_hours=9999,
                )

        self.assertTrue(report["checks"]["deepseek_runtime"]["ok"], report)
        detail = report["checks"]["deepseek_runtime"]["detail"]
        self.assertIn("adapter=deepseek_chat", detail)
        self.assertIn("model=deepseek-chat", detail)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("sk-deepseek-secret", serialized)
        self.assertNotIn("proxy.example", serialized)
        self.assertNotIn("DEEPSEEK_BASE_URL", serialized)

    def test_runtime_audit_reports_fallback_when_deepseek_key_missing(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            (cc_home / "sessions").mkdir(parents=True)
            (cc_home / "config.toml").write_text(
                """
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{args:VELA}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"
""".strip(),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True):
                report = smoke.run_runtime_audit(
                    cc_home=cc_home,
                    process_running=True,
                    max_session_age_hours=9999,
                )

        self.assertTrue(report["checks"]["deepseek_runtime"]["ok"], report)
        self.assertIn("adapter=fallback", report["checks"]["deepseek_runtime"]["detail"])
        self.assertIn("DeepSeek key not configured", report["checks"]["deepseek_runtime"]["detail"])
        self.assertNotIn("DEEPSEEK_API_KEY", json.dumps(report, ensure_ascii=False))

    def test_runtime_wait_returns_when_live_audit_passes(self):
        smoke = load_smoke_module()
        clock = {"now": 0.0}
        reports = [
            {"ok": False, "failed": ["weixin_inbound_seen"], "checks": {}, "latest_reply": {}, "next_action": {}},
            {"ok": True, "failed": [], "checks": {}, "latest_reply": {}, "next_action": {}},
        ]

        def fake_audit(**_kwargs):
            return reports.pop(0)

        report = smoke.wait_for_runtime_audit(
            cc_home=Path("unused"),
            timeout_seconds=10,
            poll_seconds=1,
            audit_fn=fake_audit,
            sleep_fn=lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
            monotonic_fn=lambda: clock["now"],
        )

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["wait"]["status"], "satisfied")
        self.assertEqual(report["wait"]["attempts"], 2)

    def test_runtime_wait_times_out_with_last_audit_report(self):
        smoke = load_smoke_module()
        clock = {"now": 0.0}

        def fake_audit(**_kwargs):
            return {
                "ok": False,
                "failed": ["weixin_inbound_seen"],
                "checks": {},
                "latest_reply": {},
                "next_action": {"kind": "send_weixin_prompt"},
            }

        report = smoke.wait_for_runtime_audit(
            cc_home=Path("unused"),
            timeout_seconds=3,
            poll_seconds=1,
            audit_fn=fake_audit,
            sleep_fn=lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
            monotonic_fn=lambda: clock["now"],
        )

        self.assertFalse(report["ok"], report)
        self.assertEqual(report["wait"]["status"], "timed_out")
        self.assertGreaterEqual(report["wait"]["attempts"], 2)
        self.assertIn("weixin_inbound_seen", report["failed"])

    def test_runtime_audit_reports_weixin_poll_state_without_leaking_cursor(self):
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as tmp:
            cc_home = Path(tmp) / ".cc-connect"
            (cc_home / "sessions").mkdir(parents=True)
            state_dir = cc_home / "weixin" / "codex-wechat" / "bot"
            state_dir.mkdir(parents=True)
            (state_dir / "get_updates.buf").write_text("opaque-poll-cursor", encoding="utf-8")
            (cc_home / "config.toml").write_text(
                f"""
[[commands]]
name = "vela-router"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args}}}}"

[[commands]]
name = "vela-talk"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" {{{{args:VELA}}}}"

[[projects]]
name = "VELA"

[projects.intent_router]
enabled = true
command = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_router.py\\" --stdin"

[[projects.platforms]]
type = "weixin"

[projects.platforms.options]
state_dir = "{str(state_dir).replace("\\", "/")}"
token = "test-token"
""".strip(),
                encoding="utf-8",
            )

            report = smoke.run_runtime_audit(
                cc_home=cc_home,
                process_running=True,
                max_session_age_hours=9999,
            )

        self.assertTrue(report["checks"]["weixin_poll_state"]["ok"], report)
        self.assertIn("poll buffer fresh", report["checks"]["weixin_poll_state"]["detail"])
        self.assertNotIn("opaque-poll-cursor", json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
