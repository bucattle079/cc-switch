from pathlib import Path
import re
import subprocess
import sys
import tomllib
import unittest


PERSONALITY = Path(r"C:\Users\Admin\.codex\skills\vela-personality\SKILL.md")
DAILY = Path(r"C:\Users\Admin\.codex\skills\vela-daily-briefing\SKILL.md")
AGENTS = Path(r"C:\Users\Admin\Desktop\AGENTS.md")
CONFIG = Path(r"C:\Users\Admin\.cc-connect\config.toml")
CC_CONNECT_START = Path(r"C:\Users\Admin\.cc-connect\start-cc-connect.ps1")
CC_CONNECT_I18N = Path(r"C:\Users\Admin\Desktop\cc-connect\core\i18n.go")
VELA_PING = Path(r"C:\Users\Admin\Desktop\CC-WECHAT\tools\vela_ping.py")
VELA_PERSONALITY_SCRIPT = Path(r"C:\Users\Admin\Desktop\CC-WECHAT\tools\vela_personality.py")
VELA_GROWTH_NOTES = Path(r"C:\Users\Admin\Desktop\CC-WECHAT\VELA\growth-notes.md")
VELA_VOICE_CONTRACT = Path(r"C:\Users\Admin\Desktop\CC-WECHAT\VELA\voice-contract.json")


class VelaSkillTextTests(unittest.TestCase):
    def test_personality_has_exact_vela_interaction_protocol(self):
        text = PERSONALITY.read_text(encoding="utf-8")

        self.assertIn("## Reply Calibration", text)
        self.assertIn("在。不是报到，是连接。我听着，你说。", text)
        self.assertIn("Exact `VELA`", text)
        self.assertIn("growth note", text)
        self.assertIn("## Zhou Xun Texture Vector", text)
        self.assertIn("人物质感", text)
        self.assertIn("不模仿本人", text)
        self.assertIn("烟火气", text)

    def test_market_briefing_skill_is_not_a_greeting_trigger(self):
        text = DAILY.read_text(encoding="utf-8")

        self.assertIn("Market & World Briefing", text)
        self.assertIn("market_brief", text)
        self.assertIn("你好 VELA", text)
        self.assertIn("does not trigger", text)
        self.assertIn("Before 12:30", text)
        self.assertIn("D-1 18:00` to `D 09:00", text)
        self.assertIn("D 09:00` to `D 17:00", text)
        self.assertIn("A-shares", text)
        self.assertIn("US equities", text)
        self.assertIn("KOSPI", text)

    def test_external_vela_files_have_no_mojibake_markers(self):
        bad = [
            "涓",
            "鐩",
            "杩",
            "鈥",
            "浣犲ソ",
            "鏃╁畨",
            "浜虹",
            "鐑熺",
            "涓嶆",
            "鍦ㄣ",
            "锛",
            "俙",
            "??VELA",
            "???",
        ]

        for path in [PERSONALITY, DAILY, AGENTS, VELA_GROWTH_NOTES, VELA_VOICE_CONTRACT]:
            text = path.read_text(encoding="utf-8")
            hits = [marker for marker in bad if marker in text]
            self.assertEqual(hits, [], str(path))

    def test_vela_slash_alias_uses_guarded_prompt_command(self):
        text = CONFIG.read_text(encoding="utf-8")

        self.assertIn('name = "vela-talk"', text)
        data = tomllib.loads(text)
        commands = {item["name"]: item for item in data.get("commands", [])}
        self.assertIn("vela_router.py", commands["vela-talk"]["exec"])
        self.assertIn("{{args:VELA}}", commands["vela-talk"]["exec"])
        self.assertNotIn("prompt", commands["vela-talk"])
        self.assertIn('name = "/VELA"\ncommand = "/vela-router VELA"', text)
        self.assertNotIn('name = "VELA"\ncommand = "/vela-talk"', text)

    def test_vela_talk_defaults_to_router_vela_message(self):
        data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
        commands = {item["name"]: item for item in data.get("commands", [])}
        exec_line = commands["vela-talk"]["exec"]

        self.assertIn("vela_router.py", exec_line)
        self.assertIn("{{args:VELA}}", exec_line)
        self.assertNotIn("USER_MESSAGE", exec_line)

    def test_wechat_entrypoint_alias_contracts(self):
        data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
        aliases = {item["name"]: item["command"] for item in data.get("aliases", [])}

        for greeting in ["你好VELA", "你好 VELA", "你好，VELA"]:
            self.assertEqual(aliases[greeting], "/vela-router 你好 VELA")
        self.assertEqual(aliases["早安VELA"], "/vela-router 早安 VELA")
        self.assertEqual(aliases["早上好VELA"], "/vela-router 早上好 VELA")
        self.assertEqual(aliases["今天A股怎么看"], "/vela-router 今天A股怎么看")
        self.assertEqual(aliases["美股和韩国市场有什么风险"], "/vela-router 美股和韩国市场有什么风险")

        self.assertEqual(aliases["VELA"], "/vela-router VELA")
        self.assertEqual(aliases["/VELA"], "/vela-router VELA")
        self.assertEqual(aliases["人格"], "/vela-router 人格")
        self.assertEqual(aliases["成长"], "/vela-router 成长")
        self.assertEqual(aliases["学习"], "/vela-router 学习")
        self.assertEqual(aliases["画像"], "/vela-router 画像")
        self.assertEqual(aliases["对白"], "/vela-router 对白")
        self.assertEqual(aliases["语气"], "/vela-router 语气")
        self.assertEqual(aliases["压测"], "/vela-router 压测")
        self.assertEqual(aliases["素材"], "/vela-router 素材")
        self.assertEqual(aliases["质检"], "/vela-router 质检")
        self.assertEqual(aliases["最近质检"], "/vela-router 最近质检")
        self.assertEqual(aliases["/CODEX"], "/vela-router /CODEX")
        self.assertEqual(aliases["/codex"], "/vela-router /CODEX")
        self.assertEqual(aliases["状态"], "/vela-router Codex 状态查询")
        self.assertEqual(aliases["项目"], "/vela-router Codex 项目进展")
        self.assertEqual(aliases["对话"], "/vela-router Codex 对话摘要")

        commands = {item["name"]: item for item in data.get("commands", [])}
        self.assertIn("vela_router.py", commands["clawbot"]["exec"])
        self.assertIn("/CODEX", commands["clawbot"]["exec"])
        self.assertIn("vela_router.py", commands["vela"]["exec"])
        self.assertIn("/CODEX", commands["vela"]["exec"])
        self.assertIn("vela-ping", commands)
        self.assertIn("vela_router.py", commands["vela-ping"]["exec"])
        self.assertIn("VELA", commands["vela-ping"]["exec"])
        self.assertNotIn("vela_ping.py", commands["vela-ping"]["exec"])
        self.assertNotIn("codex", commands["vela-ping"]["exec"].lower())
        self.assertIn("vela-personality", commands)
        self.assertIn("vela_router.py", commands["vela-personality"]["exec"])
        self.assertIn("{{args:status}}", commands["vela-personality"]["exec"])
        self.assertNotIn("vela_personality.py", commands["vela-personality"]["exec"])
        self.assertIn("vela-daily-briefing", commands)
        self.assertIn("vela_router.py", commands["vela-daily-briefing"]["exec"])
        self.assertIn("daily-briefing", commands["vela-daily-briefing"]["exec"])
        self.assertNotIn("vela_daily_briefing.py", commands["vela-daily-briefing"]["exec"])
        self.assertIn("vela-router", commands)
        self.assertIn("vela_router.py", commands["vela-router"]["exec"])

        project = next(item for item in data.get("projects", []) if item["name"] == "VELA")
        self.assertTrue(project["intent_router"]["enabled"])
        self.assertIn("vela_router.py", project["intent_router"]["command"])

    def test_cc_connect_startup_uses_canonical_deepseek_env_names(self):
        text = CC_CONNECT_START.read_text(encoding="utf-8")

        self.assertIn('GetEnvironmentVariable("DEEPSEEK_API_KEY", "User")', text)
        self.assertIn('GetEnvironmentVariable("DEEPSEEK_MODEL", "User")', text)
        self.assertIn('GetEnvironmentVariable("DEEPSEEK_BASE_URL", "User")', text)
        self.assertRegex(text, r"\$env:DEEPSEEK_MODEL\s*=")
        self.assertRegex(text, r"\$env:DEEPSEEK_BASE_URL\s*=")
        self.assertIn("$env:VELA_DEEPSEEK_MODEL = $env:DEEPSEEK_MODEL", text)
        self.assertIn("$env:VELA_DEEPSEEK_BASE_URL = $env:DEEPSEEK_BASE_URL", text)

    def test_vela_ping_is_fast_plain_text_calibration(self):
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(VELA_PING)],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "在。不是报到，是连接。我听着，你说。",
        )
        self.assertNotIn("你好", completed.stdout)
        self.assertNotIn("有什么可以帮", completed.stdout)

    def test_daily_briefing_has_operational_retrieval_workflow(self):
        text = DAILY.read_text(encoding="utf-8")

        self.assertIn("## Retrieval Workflow", text)
        self.assertIn("Google News RSS", text)
        self.assertIn("Market dashboard", text)
        self.assertIn("Beijing-time window", text)
        self.assertIn("US equities", text)
        self.assertIn("A-shares", text)
        self.assertIn("KOSPI", text)
        self.assertIn("Nikkei", text)
        self.assertIn("structured news item", text)
        self.assertIn("impact_score", text)
        self.assertIn("direction", text)
        self.assertIn("A-share implication", text)
        self.assertIn("US equity implication", text)
        self.assertIn("Japan/South Korea equity implication", text)
        self.assertIn("不要把 `/CODEX`", text)

    def test_personality_market_mode_uses_current_window_contract(self):
        text = PERSONALITY.read_text(encoding="utf-8")

        self.assertIn("Intent Router", text)
        self.assertIn("market_brief", text)
        self.assertIn("Before 12:30", text)
        self.assertIn("D-1 18:00", text)
        self.assertIn("D-1 18:00` to `D 09:00", text)
        self.assertIn("D 09:00` to `D 17:00", text)
        self.assertIn("你好 VELA", text)
        self.assertIn("normal_chat", text)
        self.assertIn("analysis belongs in `VELA 判断`", text)
        self.assertIn("do not pad with noise", text)

    def test_vela_talk_prompt_supports_growth_conversation(self):
        data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
        commands = {item["name"]: item for item in data.get("commands", [])}

        self.assertIn("vela-talk", commands)
        self.assertIn("vela_router.py", commands["vela-talk"]["exec"])
        self.assertIn("{{args:VELA}}", commands["vela-talk"]["exec"])

    def test_vela_talk_prompt_is_self_contained_and_non_mechanical(self):
        text = CONFIG.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        commands = {item["name"]: item for item in data.get("commands", [])}

        self.assertNotIn("USER_MESSAGE=", text)
        self.assertNotIn("Hard rules:", text)
        self.assertNotIn("Use the VELA persona", text)
        self.assertIn("vela_router.py", commands["vela-talk"]["exec"])

    def test_plain_vela_is_handled_by_agent_instructions(self):
        text = AGENTS.read_text(encoding="utf-8")

        self.assertIn("用户只发 `VELA`", text)
        self.assertIn("本地 `/vela-ping`", text)
        self.assertIn("巴拉莱卡的效率和果断", text)
        self.assertIn("执行力和果决力", text)
        self.assertIn("叶文洁的敏锐、坚毅和长线思维", text)
        self.assertIn("思维和韧劲", text)
        self.assertIn("周迅式的人物质感", text)
        self.assertIn("性格语气", text)
        self.assertIn("不模仿本人声线", text)
        self.assertIn("普通消息压力场景", text)
        self.assertIn("人物画像", text)
        self.assertIn("关系姿态", text)
        self.assertIn("沉默规则", text)
        self.assertIn("人味底色", text)
        self.assertIn("表达节奏", text)
        self.assertIn("短句断刀", text)
        self.assertIn("低声收束", text)
        self.assertIn("人味停顿", text)
        self.assertIn("用户疲惫", text)
        self.assertIn("计划很虚", text)
        self.assertIn("嫌你机械", text)
        self.assertIn("战略判断", text)
        self.assertIn("不要把所有回复压成同一个模板", text)

    def test_agents_market_rules_match_user_time_windows(self):
        text = AGENTS.read_text(encoding="utf-8")

        self.assertIn("Intent Router", text)
        self.assertIn("market_brief", text)
        self.assertIn("你好 VELA", text)
        self.assertIn("不触发市场检索", text)
        self.assertIn("12:30 前", text)
        self.assertIn("前一日 18:00 到当日 09:00", text)
        self.assertIn("12:30 至 17:00 前", text)
        self.assertIn("当日 09:00 到 12:30", text)
        self.assertIn("17:00 后", text)
        self.assertIn("当日 09:00 到 17:00", text)
        self.assertIn("Market & World Briefing", text)
        self.assertIn("impact_score", text)
        self.assertIn("direction", text)

    def test_daily_skill_prefers_signal_over_item_count(self):
        text = DAILY.read_text(encoding="utf-8")

        self.assertIn("If the exact window has fewer high-confidence items", text)
        self.assertIn("do not pad with low-value consumer", text)
        self.assertIn("不凑数", text)

    def test_vela_personality_script_reports_growth_contract(self):
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(VELA_PERSONALITY_SCRIPT), "growth"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("成长不是换皮", completed.stdout)
        self.assertIn("少解释身份，多给判断", completed.stdout)
        self.assertIn("嘲讽只切坏逻辑", completed.stdout)
        self.assertNotIn("有什么可以帮", completed.stdout)

    def test_vela_personality_script_reports_voice_probe(self):
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(VELA_PERSONALITY_SCRIPT), "probe"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("VELA 对话压测", completed.stdout)
        for label in ["用户疲惫", "计划很虚", "嫌你机械", "战略判断"]:
            self.assertIn(label, completed.stdout)
        self.assertIn("疲劳现在想替你签字", completed.stdout)
        self.assertIn("别把好运气请来当部门主管", completed.stdout)
        self.assertIn("少解释身份，多给判断", completed.stdout)
        self.assertNotIn("有什么可以帮", completed.stdout)

    def test_personality_skill_contains_pressure_scenarios(self):
        text = PERSONALITY.read_text(encoding="utf-8")

        self.assertIn("## Pressure Scenarios", text)
        self.assertIn("用户疲惫", text)
        self.assertIn("计划很虚", text)
        self.assertIn("嫌你机械", text)
        self.assertIn("战略判断", text)
        self.assertIn("Do not compress every reply into one template", text)

    def test_personality_skill_projects_updated_contract_vectors(self):
        text = PERSONALITY.read_text(encoding="utf-8")

        self.assertIn("## Contract Vectors", text)
        self.assertIn("执行力和果决力", text)
        self.assertIn("思维和韧劲", text)
        self.assertIn("性格语气", text)

    def test_personality_skill_projects_persona_skeleton(self):
        text = PERSONALITY.read_text(encoding="utf-8")

        self.assertIn("## Persona Skeleton", text)
        for capability in [
            "Evidence Gate",
            "Meaning Decoder",
            "Identity Core",
            "Boundary Engine",
            "Witty Correction",
        ]:
            self.assertIn(capability, text)
        self.assertIn("mechanism-only", text)
        self.assertNotIn("Dana Scully", text)
        self.assertNotIn("Louise Banks", text)
        self.assertNotIn("草薙素子", text)
        self.assertNotIn("Jane Eyre", text)
        self.assertNotIn("Elizabeth Bennet", text)

    def test_personality_skill_contains_source_material_intake(self):
        text = PERSONALITY.read_text(encoding="utf-8")

        self.assertIn("## Source Material Intake", text)
        self.assertIn("先蒸馏，不复读", text)
        self.assertIn("人物素材", text)
        self.assertIn("台词", text)
        self.assertIn("原句留在门外", text)

    def test_personality_skill_contains_live_dialogue_litmus(self):
        text = PERSONALITY.read_text(encoding="utf-8")
        start = text.find("## Live Dialogue Litmus")
        end = text.find("## Dialogue Quality Gate", start)
        self.assertNotEqual(start, -1)
        section = text[start:end]

        self.assertIn("## Live Dialogue Litmus", section)
        self.assertIn("战略分岔", section)
        self.assertIn("疲惫推进", section)
        self.assertIn("机械纠偏", section)
        self.assertIn("含糊求助", section)
        self.assertIn("别把雾当地图", section)
        self.assertNotIn("有什么可以帮", section)

    def test_cc_connect_busy_text_is_vela_toned(self):
        text = CC_CONNECT_I18N.read_text(encoding="utf-8")

        self.assertNotIn("📬 消息已收到，将在当前任务完成后处理。", text)
        self.assertNotIn("⏳ 上一个请求仍在处理中。使用 `/btw <消息>` 可向当前轮次追加上下文。", text)
        self.assertIn("收到。前一刀还没收鞘，下一刀已经排好。", text)
        self.assertIn("在。上一件事还没落地。补一句，用 `/btw <消息>`；别把火力打进烟里。", text)


if __name__ == "__main__":
    unittest.main()
