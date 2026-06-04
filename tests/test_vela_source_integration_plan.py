import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "VELA" / "source-integration-plan.json"


class VelaSourceIntegrationPlanTests(unittest.TestCase):
    def test_source_integration_plan_declares_provider_ready_surfaces(self):
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

        self.assertEqual(plan["schema_version"], 1)
        self.assertIn("official_announcements", plan["sources"])
        self.assertIn("judicial_auction", plan["sources"])
        self.assertIn("court_documents", plan["sources"])
        self.assertIn("execution_info", plan["sources"])
        self.assertIn("enterprise_query", plan["sources"])
        self.assertIn("eastmoney_xueqiu_market_info", plan["sources"])
        self.assertIn("mutual_finance_listed_company_watchlist", plan["sources"])
        self.assertEqual(
            set(plan["output_structures"]),
            {"daily_brief", "topic_radar", "company_watchlist", "risk_signal", "decision_log", "local_memory"},
        )
        for source in plan["sources"].values():
            self.assertIn(source["source_type"], {"web_search", "news", "market_data", "local_files", "generic_tool_connector"})
            self.assertIn(source["status"], {"provider_ready", "local_file_ready", "planned"})
            self.assertFalse(source.get("pretend_connected", True))


if __name__ == "__main__":
    unittest.main()
