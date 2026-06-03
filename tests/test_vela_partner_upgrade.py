import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"
ROUTER = TOOLS / "vela_router.py"
PRODUCT = TOOLS / "vela_product_layers.py"
REPLY_ENGINE = TOOLS / "vela_reply_engine.py"
MARKET = TOOLS / "vela_market_briefing.py"


def load_module(path: Path, name: str):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaPartnerUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.learning_loop_dir = Path(self.temp_dir.name) / "learning-loop"
        self.env_patcher = patch.dict("os.environ", self.isolated_env(), clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def isolated_env(self, **overrides):
        env = {"VELA_LEARNING_LOOP_DIR": str(self.learning_loop_dir)}
        env.update(overrides)
        return env

    def test_freshness_reply_is_human_readable_and_hides_schema(self):
        router = load_module(ROUTER, "vela_router_partner_freshness")

        started = time.perf_counter()
        reply = router.reply_for("这是实时的吗")
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 2.0)
        self.assertIn("不是实时直播", reply)
        self.assertIn("更新时间", reply)
        self.assertIn("实时源", reply)
        self.assertIn("缓存", reply)
        self.assertNotIn("数据来源：", reply)
        for leaked in [
            "data_status",
            "last_updated:",
            "source_type",
            "refresh_available",
            "refresh_in_progress",
            "confidence_note",
            "cache_path",
        ]:
            self.assertNotIn(leaked, reply)

    def test_market_refresh_status_hides_schema_and_does_not_fake_realtime(self):
        router = load_module(ROUTER, "vela_router_partner_refresh")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(router, "MARKET_REFRESH_DIR", Path(tmp)):
                with patch("subprocess.Popen") as popen:
                    popen.return_value.pid = 12345
                    reply = router.reply_for("刷新最新市场资讯")

        self.assertIn("不拿缓存冒充实时", reply)
        self.assertIn("最近缓存", reply)
        self.assertIn("后台刷新已启动", reply)
        self.assertIn("前台先返回状态", reply)
        self.assertNotIn("VELA 市场简报", reply)
        for leaked in ["data_status", "source_type", "refresh_available", "refresh_in_progress", "cache_path"]:
            self.assertNotIn(leaked, reply)
        popen.assert_called_once()
        popen_args = popen.call_args.args[0]
        self.assertIn("--lock-file", popen_args)
        self.assertIn(str(Path(tmp) / "refresh.lock"), popen_args)

    def test_market_refresh_reports_existing_background_job(self):
        router = load_module(ROUTER, "vela_router_partner_refresh_existing")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            router.MARKET_REFRESH_DIR = state_dir
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "refresh.lock").write_text("{}", encoding="utf-8")
            with patch("subprocess.Popen") as popen:
                reply = router.reply_for("刷新最新市场资讯")

        self.assertIn("后台刷新已在进行", reply)
        self.assertIn("前台先返回状态", reply)
        popen.assert_not_called()

    def test_market_refresh_lock_cleanup_removes_lock_file(self):
        market = load_module(MARKET, "vela_market_briefing_partner_cleanup")

        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "refresh.lock"
            lock.write_text("{}", encoding="utf-8")
            market.cleanup_lock_file(str(lock))

        self.assertFalse(lock.exists())

    def test_deepseek_wins_over_command_adapter_for_dialogue_default(self):
        engine = load_module(REPLY_ENGINE, "vela_reply_engine_partner_priority")

        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "sk-deepseek-secret",
                "VELA_GPT_COMMAND": "python fake_codex_dialogue.py",
            },
            clear=True,
        ):
            status = engine.reply_engine_status()
            adapter = engine.default_reply_adapter()

        self.assertEqual(status["adapter"], "deepseek_chat")
        self.assertEqual(status["config_source"], "DEEPSEEK_API_KEY")
        self.assertEqual(adapter.name, "deepseek_chat")
        self.assertNotIn("sk-deepseek-secret", json.dumps(status))

    def test_partner_loop_selects_tools_and_learning_without_promoting_memory(self):
        product = load_module(PRODUCT, "vela_product_layers_partner_loop")

        normal = product.select_model_and_tools(
            "normal_chat",
            env={"DEEPSEEK_API_KEY": "sk-test", "VELA_GPT_COMMAND": "codex fake"},
        )
        codex = product.select_model_and_tools("codex_task", env={"DEEPSEEK_API_KEY": "sk-test"})
        feedback = product.evaluate_learning("你太像机器人了", "memory_related")

        self.assertEqual(normal.model_adapter, "deepseek_chat")
        self.assertFalse(normal.allow_codex)
        self.assertFalse(normal.allow_market)
        self.assertEqual(normal.foreground_lane, "fast")
        self.assertEqual(codex.model_adapter, "codex_bridge")
        self.assertTrue(codex.allow_codex)
        self.assertTrue(feedback.should_record_candidate)
        self.assertTrue(feedback.should_affect_next_reply)
        self.assertEqual(feedback.classification, "style_feedback")
        self.assertFalse(feedback.promote_to_strategic_memory)

    def test_model_selector_matches_runtime_adapter_priority_after_deepseek(self):
        product = load_module(PRODUCT, "vela_product_layers_partner_adapter_priority")

        selection = product.select_model_and_tools(
            "normal_chat",
            env={
                "VELA_GPT_COMMAND": "python fake_gpt.py",
                "VELA_OPENAI_API_KEY": "sk-openai-secret",
            },
        )

        self.assertEqual(selection.model_adapter, "command")

    def test_learning_evaluation_is_recorded_in_quality_log(self):
        product = load_module(PRODUCT, "vela_product_layers_partner_quality")

        with tempfile.TemporaryDirectory() as tmp:
            result = product.run_layered_response(
                "你太像机器人了",
                intent="memory_related",
                log_dir=Path(tmp),
            )
            quality_path = next(Path(tmp).glob("reply-quality-*.jsonl"))
            row = json.loads(quality_path.read_text(encoding="utf-8"))

        self.assertTrue(result.memory_candidate)
        self.assertNotIn("style_feedback", result.text)
        self.assertIn("learning_eval:style_feedback", row["quality_flags"])
        self.assertIn("affects_next_reply", row["quality_flags"])
        self.assertTrue(row["memory_candidate"])

    def test_style_feedback_shapes_immediate_continue_followup(self):
        product = load_module(PRODUCT, "vela_product_layers_partner_feedback_followup")

        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            product.run_layered_response(
                "你太像机器人了，少菜单，多判断",
                intent="memory_related",
                log_dir=log_dir,
                reply_adapter=product.FallbackReplyAdapter(),
            )
            result = product.run_layered_response(
                "继续",
                intent="normal_chat",
                log_dir=log_dir,
                reply_adapter=product.FallbackReplyAdapter(),
            )

        self.assertIn("K", result.text)
        self.assertTrue(any(token in result.text for token in ["继续", "上一轮", "阻塞", "一个动作", "接着来"]))
        for self_label in ["少菜单", "多判断", "机械味", "不摆路牌", "少解释"]:
            self.assertNotIn(self_label, result.text)
        self.assertNotIn("要看盘，说 A股、美股或韩国", result.text)

    def test_project_progress_status_routes_to_codex_bridge(self):
        router = load_module(ROUTER, "vela_router_partner_codex_progress")

        for text in ["查看项目进展", "当前项目推进状态", "Codex 执行到哪里"]:
            intent = router.classify_intent(text)

            self.assertEqual(intent.name, "codex_task", text)
            self.assertTrue(intent.codex_allowed, text)
            self.assertFalse(intent.market_allowed, text)

    def test_codex_product_judgment_hides_automation_and_directive_noise(self):
        product = load_module(PRODUCT, "vela_product_layers_partner_codex_noise")

        result = product.run_layered_response(
            "CODEX/",
            intent="codex_task",
            codex_summary=(
                "VELA · CODEX 最近完成 项目: Automation: VELA market cache 17:00 "
                "Automation ID: vela-market-cache-17-00 "
                "Automation memory: $CODEX_HOME/automations/vela-market-cache-17-00.md "
                "最后结论 ::inbox-item{title=\"17:00 market cache refreshed\" "
                "summary=\"Cache written and JSON validated; no WeChat sent\"} "
                "截图已生成。文本备份已保存。"
            ),
        )

        self.assertIn("CODEX 产品判断摘要", result.text)
        for leaked in [
            "Automation ID",
            "Automation memory",
            "$CODEX_HOME",
            "::inbox-item",
            "Cache written",
            "截图已生成",
            "文本备份",
            "最后结论",
            "最近完成",
        ]:
            self.assertNotIn(leaked, result.text)

    def test_codex_product_judgment_keeps_conclusion_while_dropping_command_logs(self):
        product = load_module(PRODUCT, "vela_product_layers_partner_codex_command_noise")

        result = product.run_layered_response(
            "CODEX/",
            intent="codex_task",
            codex_summary=(
                "$CODEX_HOME/automations/run.md\n"
                "pytest -q tests/test_vela_partner_upgrade.py 10 passed\n"
                "rg -n schema_version tools/vela_router.py\n"
                "C:\\Users\\Admin\\Desktop\\CC-WECHAT\\tools\\vela_router.py:338\n"
                "Automation ID: vela-market-cache-17-00\n"
                "::inbox-item{title=\"17:00 market cache refreshed\" summary=\"Cache written and JSON validated\"}\n"
                "当前结论：市场刷新前台已状态先行，缓存不冒充实时；学习反馈进入下一轮。"
            ),
        )

        self.assertIn("CODEX 产品判断摘要", result.text)
        self.assertIn("市场刷新前台已状态先行", result.text)
        self.assertIn("学习反馈进入下一轮", result.text)
        for leaked in ["pytest", "rg -n", "schema_version", "C:\\Users", "Automation ID", "::inbox-item", "Cache written"]:
            self.assertNotIn(leaked, result.text)

    def test_layered_response_passes_foreground_lane_to_default_adapter(self):
        product = load_module(PRODUCT, "vela_product_layers_partner_lane_budget")
        reply_engine = load_module(REPLY_ENGINE, "vela_reply_engine_partner_lane_budget")
        lanes = []

        class LaneProbeAdapter(reply_engine.ReplyAdapter):
            name = "lane_probe"

            def generate(self, context):
                return reply_engine.ReplyEngineResult(
                    text=f"K，lane ok: {context.intent}",
                    source="test",
                    used_api=False,
                    adapter=self.name,
                )

        def adapter_factory(*, foreground_lane=None):
            lanes.append(foreground_lane)
            return LaneProbeAdapter()

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(product, "default_reply_adapter", side_effect=adapter_factory):
                product.run_layered_response("帮我总结这段", intent="normal_chat", log_dir=Path(tmp))
                product.run_layered_response("地狱验尸一下", intent="deep_analysis", log_dir=Path(tmp))

        self.assertEqual(lanes, ["fast", "deep"])


if __name__ == "__main__":
    unittest.main()
