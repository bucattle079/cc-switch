from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"
ROUTER = TOOLS / "vela_router.py"


def load_router():
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("vela_router_final_humanizer", ROUTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VelaFinalHumanizerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patcher = patch.dict(
            "os.environ",
            {"VELA_LEARNING_LOOP_DIR": str(Path(self.temp_dir.name) / "learning-loop")},
            clear=True,
        )
        self.env_patcher.start()
        self.router = load_router()

    def tearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def reply(self, message: str) -> str:
        return self.router.reply_for(message)

    def assert_no_template_tics(self, text: str) -> None:
        forbidden = [
            "K，",
            "K。",
            "K，在",
            "直接说",
            "不用铺垫",
            "不绕弯",
            "废话我会过滤",
            "刻板也是一种风格",
            "我会自己过滤",
            "把真正的问题放前面",
            "当前状态如下",
            "模型生成：不可用",
            "缓存状态：可用",
            "real_time_source_available",
            "model_generated_only",
            "cached_summary_available",
        ]
        for token in forbidden:
            self.assertNotIn(token, text)

    def test_plain_vela_ping_does_not_default_to_fixed_k_catchphrase(self):
        reply = self.reply("VELA")

        self.assertLess(len(reply), 80)
        self.assertFalse(reply.startswith("K，"), reply)
        self.assert_no_template_tics(reply)

    def test_short_greeting_does_not_default_to_fixed_k_catchphrase(self):
        reply = self.reply("你好 VELA")

        self.assertLess(len(reply), 80)
        self.assertFalse(reply.startswith("K"), reply)
        self.assertTrue(any(token in reply for token in ["在", "我在", "听着", "你说"]), reply)
        self.assert_no_template_tics(reply)

    def test_how_to_communicate_answers_the_actual_question(self):
        reply = self.reply("如何更好地与你沟通")

        self.assertTrue(any(token in reply for token in ["目标", "背景", "限制", "想要", "结论"]), reply)
        self.assertIn("沟通", reply)
        self.assert_no_template_tics(reply)

    def test_user_direction_correction_is_acknowledged_and_redirected(self):
        reply = self.reply("现在是需要的是了解如何和你沟通")

        self.assertTrue(any(token in reply for token in ["对", "明白", "你问的是", "你要的是"]), reply)
        self.assertIn("沟通", reply)
        self.assertNotIn("把真正的问题放前面", reply)
        self.assert_no_template_tics(reply)

    def test_filter_what_repairs_bad_wording(self):
        reply = self.reply("过滤啥？")

        self.assertTrue(any(token in reply for token in ["我说错", "表达不当", "不是过滤你", "过滤的是我"]), reply)
        self.assert_no_template_tics(reply)

    def test_realtime_market_boundary_is_user_readable_not_engineering_fields(self):
        reply = self.reply("现在的市场资讯")

        self.assertTrue(
            any(
                token in reply
                for token in ["不能读取实时", "实时源未接入", "实时源暂不可用", "不能给盘中实时结论", "实时源已接入"]
            ),
            reply,
        )
        for token in ["状态边界", "数据来源：本地市场缓存", "模型仅生成", "缓存摘要", "可用性"]:
            self.assertNotIn(token, reply)
        self.assert_no_template_tics(reply)

    def test_how_long_realtime_source_answer_first(self):
        reply = self.reply("接通实时的源要多久呢？")
        first_line = reply.splitlines()[0]

        self.assertTrue(any(token in first_line for token in ["小时", "半天", "一天", "1-2 天", "1–2 天"]), reply)
        self.assertNotIn("当前报告基于", first_line)
        self.assertNotIn("更新时间", first_line)
        self.assert_no_template_tics(reply)

    def test_time_query_answers_with_clock_not_mechanical_proof(self):
        reply = self.reply("现在纽约时间约是几点")

        self.assertIn("纽约", reply)
        self.assertRegex(reply, r"\b\d{1,2}:\d{2}\b")
        self.assertIn("UTC", reply)
        self.assertTrue(any(token in reply for token in ["清晨", "上午", "午间", "下午", "晚上", "深夜"]), reply)
        for token in [
            "判断：",
            "本地时区直接计算",
            "本地计算",
            "闲聊模板",
            "冒充答案",
            "不是模板",
            "不拿模板",
        ]:
            self.assertNotIn(token, reply)
        self.assert_no_template_tics(reply)

    def test_criticism_repairs_instead_of_defending_style(self):
        reply = self.reply("好吧 你的回答还是一样刻板")

        self.assertTrue(any(token in reply for token in ["对", "确实", "这次", "重说"]), reply)
        self.assertNotIn("刻板也是一种风格", reply)
        self.assertNotIn("防御", reply)
        self.assertTrue(any(token in reply for token in ["先回答", "系统状态", "状态说明", "重说"]), reply)
        self.assert_no_template_tics(reply)

    def test_session_style_feedback_affects_next_turn_no_k_prefix(self):
        first = self.reply("你刚刚还是模板，不要 K，更像真人一点")
        second = self.reply("你好 VELA")

        self.assert_no_template_tics(first)
        self.assert_no_template_tics(second)
        self.assertFalse(second.startswith("K"), second)
        self.assertNotIn("把真正的问题放前面", second)

    def test_ellipsis_is_treated_as_dissatisfaction_not_new_command(self):
        reply = self.reply("。。")

        self.assertFalse(reply.startswith("K"), reply)
        self.assertTrue(any(token in reply for token in ["不是在提新问题", "无语", "话术化", "我重说"]), reply)
        self.assertTrue(any(token in reply for token in ["重说", "重新", "修正", "换一版"]), reply)
        self.assertNotIn("把真正的问题放前面", reply)
        self.assert_no_template_tics(reply)

    def test_deepseek_api_question_explains_model_vs_retrieval_without_talking_down(self):
        reply = self.reply("我不是给你的后台连接了 DEEPSEEK API 吗 为什么不能直接接入去检索资料？")

        self.assertFalse(reply.startswith("K"), reply)
        self.assertIn("模型推理", reply)
        self.assertTrue(any(token in reply for token in ["外部信息入口", "检索工具", "搜索工具", "网页抓取", "行情数据源"]), reply)
        self.assertIn("DeepSeek", reply)
        self.assertNotIn("小白", reply)
        self.assert_no_template_tics(reply)

    def test_deepseek_api_self_search_question_explains_retrieval_boundary(self):
        reply = self.reply("为什么接了 DeepSeek API 还不能自己搜？")

        self.assertFalse(reply.startswith("K"), reply)
        self.assertIn("模型推理", reply)
        self.assertTrue(any(token in reply for token in ["外部信息入口", "检索工具", "搜索工具", "网页抓取", "行情数据源"]), reply)
        self.assertIn("DeepSeek", reply)
        self.assertNotIn("先把真实问题拎出来", reply)
        self.assert_no_template_tics(reply)

    def test_market_vix_question_keeps_realtime_boundary_and_mentions_vix(self):
        reply = self.reply("目前的存储和光模块在国际金融市场的讨论度很高，还能持续吗？另外现在 VIX 值是多少呢？")

        self.assertFalse(reply.startswith("K"), reply)
        self.assertIn("VIX", reply)
        self.assertTrue(any(token in reply for token in ["实时源", "不能给", "暂不可用", "未接入", "缓存"]), reply)
        self.assertTrue(any(token in reply for token in ["存储", "光模块", "AI", "方向判断"]), reply)
        for token in ["状态边界", "数据来源：", "model_generated_only", "cached_summary_available"]:
            self.assertNotIn(token, reply)
        self.assert_no_template_tics(reply)


if __name__ == "__main__":
    unittest.main()
