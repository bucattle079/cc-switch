import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
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
            "weather_jinjiang",
            "market_add_position",
            "freshness_status",
            "codex_status_route_only",
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


if __name__ == "__main__":
    unittest.main()
