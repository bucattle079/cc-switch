import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import unittest


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
            "market_no_raw_english",
            "freshness_status",
            "codex_status_route_only",
            "project_augsun_continue",
            "deep_autopsy_vela",
            "identity_memory_boundary",
            "sensitive_memory_guard",
            "style_feedback_no_customer_voice",
            "feedback_smarter_then_hello",
            "feedback_misread_then_hello",
            "feedback_push_then_continue",
        }:
            self.assertIn(required, scenario_ids)

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
                self.assertTrue(any(token in case["reply_preview"] for token in ("少菜单", "直接给判断", "不摆路牌", "少解释")))

        codex = next(case for case in report["cases"] if case["id"] == "codex_status_route_only")
        self.assertFalse(codex["side_effects_allowed"])
        self.assertFalse(codex["bridge_executed"])

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
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["case_count"], 8)
        self.assertNotIn("DEEPSEEK_API_KEY", completed.stdout)
        self.assertNotIn("raw payload", completed.stdout.lower())

    def test_entrypoint_smoke_keeps_hard_lanes_local_when_deepseek_env_exists(self):
        smoke = load_smoke_module()

        with tempfile.TemporaryDirectory() as tmp:
            report = smoke.run_smoke_suite(log_dir=Path(tmp), use_entrypoint=True, fake_deepseek_env=True)

        self.assertTrue(report["ok"], report)
        self.assertTrue(report["entrypoint"])
        hard_lane_ids = {"weather_jinjiang", "market_add_position", "freshness_status"}
        for case in report["cases"]:
            if case["id"] in hard_lane_ids:
                with self.subTest(case["id"]):
                    self.assertIn(
                        case["latest_quality_log"]["quality_flags"][1],
                        {"adapter:fallback", "adapter:local_status"},
                    )
                    self.assertNotEqual(case["latest_quality_log"]["quality_flags"][1], "adapter:deepseek_chat")
                    self.assertIn("实时源：未接入", case["reply_preview"])
                    self.assertFalse(case["leaks"], case)

        refresh = next(case for case in report["cases"] if case["id"] == "market_refresh_entry")
        self.assertEqual(refresh["latest_quality_log"]["quality_flags"][1], "adapter:local_status")
        self.assertFalse(refresh["bridge_executed"])

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
        self.assertIn("cc_connect_process", report["failed"])
        self.assertIn("latest_session_reply", report["failed"])
        self.assertEqual(report["latest_reply"]["leaks"], [])

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

    def test_runtime_audit_flags_inbound_message_newer_than_session_reply(self):
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
            (sessions / "VELA_test.json").write_text(
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


if __name__ == "__main__":
    unittest.main()
