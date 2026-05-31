from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(r"C:\Users\Admin\Desktop\CC-WECHAT")
CONTRACT = ROOT / "VELA" / "voice-contract.json"
PERSONALITY = Path(r"C:\Users\Admin\.codex\skills\vela-personality\SKILL.md")
AGENTS = Path(r"C:\Users\Admin\Desktop\AGENTS.md")
CONFIG = Path(r"C:\Users\Admin\.cc-connect\config.toml")
SCRIPT = ROOT / "tools" / "vela_personality.py"
SYNC_SCRIPT = ROOT / "tools" / "update_vela_dialogue_contracts.py"
REPLY_ENGINE = ROOT / "tools" / "vela_reply_engine.py"


class VelaVoiceContractTests(unittest.TestCase):
    def load_contract(self):
        return json.loads(CONTRACT.read_text(encoding="utf-8"))

    def load_reply_engine(self):
        spec = importlib.util.spec_from_file_location("vela_reply_engine", REPLY_ENGINE)
        module = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_sync_script_routes_backups_to_vela_iteration_archive(self):
        spec = importlib.util.spec_from_file_location("update_vela_dialogue_contracts", SYNC_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source = temp_root / "Desktop" / "AGENTS.md"
            archive = temp_root / "CC-WECHAT" / "VELA" / "iteration-archive" / "AGENTS"
            source.parent.mkdir(parents=True)
            source.write_text("active instructions", encoding="utf-8")

            original_targets = getattr(module, "BACKUP_TARGETS", {})
            module.BACKUP_TARGETS = {source: archive}
            try:
                module.backup(source)
            finally:
                module.BACKUP_TARGETS = original_targets

            archived = list(archive.glob("AGENTS.md.backup-*"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0].read_text(encoding="utf-8"), "active instructions")
            self.assertEqual(list(source.parent.glob("AGENTS.md.backup-*")), [])

    def test_voice_contract_exists_with_core_vectors_and_scenarios(self):
        contract = self.load_contract()

        self.assertEqual(contract["name"], "VELA")
        self.assertIn("巴拉莱卡", contract["vectors"]["decisiveness"])
        self.assertIn("执行力", contract["vectors"]["decisiveness"])
        self.assertIn("果决力", contract["vectors"]["decisiveness"])
        self.assertIn("叶文洁", contract["vectors"]["long_horizon"])
        self.assertIn("思维", contract["vectors"]["long_horizon"])
        self.assertIn("韧劲", contract["vectors"]["long_horizon"])
        self.assertIn("周迅", contract["vectors"]["texture"])
        self.assertIn("性格语气", contract["vectors"]["texture"])
        self.assertIn("判断先于解释，动作先于姿态", contract["hard_rules"])
        self.assertIn("不要把所有回复压成同一个模板", contract["hard_rules"])

        scenarios = contract["pressure_scenarios"]
        self.assertEqual(set(scenarios), {"用户疲惫", "计划很虚", "嫌你机械", "战略判断"})
        for scenario in scenarios.values():
            self.assertIn("rule", scenario)
            self.assertIn("example", scenario)
            self.assertNotIn("有什么可以帮", scenario["example"])

        depth = contract["character_depth"]
        self.assertIn("relationship_stance", depth)
        self.assertIn("silence_rule", depth)
        self.assertIn("human_texture", depth)
        self.assertIn("anti_flattening", depth)
        self.assertIn("不是角色扮演", depth["anti_flattening"])

        cadence = contract["cadence_palette"]
        self.assertEqual(set(cadence), {"短句断刀", "低声收束", "冷幽默", "人味停顿"})
        for item in cadence.values():
            self.assertIn("rule", item)
            self.assertIn("example", item)
            self.assertNotIn("有什么可以帮", item["example"])

        intake = contract["source_material_intake"]
        self.assertIn("先蒸馏，不复读", intake["rule"])
        self.assertIn("人物素材", intake["rule"])
        self.assertIn("不要建立台词库", intake["copyright_boundary"])
        self.assertIn("原句留在门外", intake["example"])
        self.assertEqual(
            set(intake["buckets"]),
            {"判断方式", "执行姿态", "语言节奏", "人味底色", "边界禁区"},
        )

        samples = contract["live_dialogue_samples"]
        self.assertEqual(
            set(samples),
            {"战略分岔", "疲惫推进", "素材吸收", "机械纠偏", "含糊求助"},
        )
        for sample in samples.values():
            self.assertIn("user", sample)
            self.assertIn("reply", sample)
            self.assertNotIn("有什么可以帮", sample["reply"])
            self.assertNotIn("作为 VELA", sample["reply"])
            self.assertLessEqual(len(sample["reply"]), 90)

        gates = contract["dialogue_quality_gates"]
        self.assertEqual(gates["pass_threshold"], 3)
        self.assertIn("执行力", gates["dimensions"])
        self.assertIn("长线判断", gates["dimensions"])
        self.assertIn("人味质地", gates["dimensions"])
        self.assertIn("反机械", gates["dimensions"])
        self.assertIn("有什么可以帮", gates["forbidden_phrases"])

    def test_contract_terms_are_projected_to_runtime_surfaces(self):
        contract = self.load_contract()
        surfaces = "\n".join(
            [
                PERSONALITY.read_text(encoding="utf-8"),
                AGENTS.read_text(encoding="utf-8"),
                CONFIG.read_text(encoding="utf-8"),
                self.load_reply_engine().dialogue_system_prompt(),
            ]
        )

        for term in contract["must_include_terms"]:
            self.assertIn(term, surfaces)
        for label, scenario in contract["pressure_scenarios"].items():
            self.assertIn(label, surfaces)
            self.assertIn(scenario["example"], surfaces)

    def test_contract_terms_are_projected_to_router_runtime_prompt(self):
        contract = self.load_contract()
        data = __import__("tomllib").loads(CONFIG.read_text(encoding="utf-8"))
        vela_talk = [item for item in data["commands"] if item["name"] == "vela-talk"][0]
        runtime_prompt = self.load_reply_engine().dialogue_system_prompt()

        self.assertIn("vela_router.py", vela_talk["exec"])
        self.assertIn("{{args:VELA}}", vela_talk["exec"])
        self.assertNotIn("prompt", vela_talk)
        for rule in contract["hard_rules"]:
            self.assertIn(rule, runtime_prompt)
        for detail in contract["character_depth"].values():
            self.assertIn(detail, runtime_prompt)
        self.assertIn("短句断刀", runtime_prompt)
        self.assertIn("低声收束", runtime_prompt)
        self.assertNotIn("巴拉莱卡", runtime_prompt)
        self.assertNotIn("叶文洁", runtime_prompt)
        self.assertNotIn("周迅", runtime_prompt)

    def test_contract_vectors_are_projected_to_personality_skill(self):
        contract = self.load_contract()
        text = PERSONALITY.read_text(encoding="utf-8")

        self.assertIn("## Contract Snapshot", text)
        for vector in contract["vectors"].values():
            self.assertIn(vector, text)
        self.assertIn("执行力和果决力", text)
        self.assertIn("思维和韧劲", text)
        self.assertIn("性格语气", text)

    def test_personality_script_outputs_contract_scenarios(self):
        contract = self.load_contract()
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "probe"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        for label, scenario in contract["pressure_scenarios"].items():
            self.assertIn(label, completed.stdout)
            self.assertIn(scenario["example"], completed.stdout)
        self.assertIn("人物素材", completed.stdout)
        self.assertIn(contract["source_material_intake"]["example"], completed.stdout)
        self.assertIn("原句留在门外", completed.stdout)

    def test_personality_script_reports_contract_source(self):
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "status"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("契约源：VELA/voice-contract.json", completed.stdout)

    def test_personality_script_reports_character_profile(self):
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "profile"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("VELA 人物画像", completed.stdout)
        self.assertIn("关系姿态", completed.stdout)
        self.assertIn("沉默规则", completed.stdout)
        self.assertIn("人味底色", completed.stdout)
        self.assertIn("不是角色扮演", completed.stdout)
        self.assertIn("契约源：VELA/voice-contract.json", completed.stdout)

    def test_personality_script_reports_dialogue_samples(self):
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "samples"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("VELA 对白样本", completed.stdout)
        for label in ["短句断刀", "低声收束", "冷幽默", "人味停顿"]:
            self.assertIn(label, completed.stdout)
        self.assertIn("证据还差一块", completed.stdout)
        self.assertNotIn("有什么可以帮", completed.stdout)
        self.assertIn("契约源：VELA/voice-contract.json", completed.stdout)

    def test_personality_script_reports_live_dialogue_litmus(self):
        contract = self.load_contract()
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "litmus"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("VELA 真人对话压测", completed.stdout)
        for label, sample in contract["live_dialogue_samples"].items():
            self.assertIn(label, completed.stdout)
            self.assertIn(sample["user"], completed.stdout)
            self.assertIn(sample["reply"], completed.stdout)
        self.assertIn("原句留在门外", completed.stdout)
        self.assertNotIn("有什么可以帮", completed.stdout)
        self.assertNotIn("作为 VELA", completed.stdout)

    def test_personality_script_audits_live_dialogue_samples(self):
        contract = self.load_contract()
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "audit"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("VELA 对话质检", completed.stdout)
        self.assertIn("总体：通过", completed.stdout)
        for label in contract["live_dialogue_samples"]:
            self.assertIn(label, completed.stdout)
        for dimension in ["执行力", "长线判断", "人味质地", "反机械"]:
            self.assertIn(dimension, completed.stdout)

    def test_personality_script_rejects_mechanical_reply(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                str(SCRIPT),
                "audit",
                "你好，有什么可以帮你？我将首先为你提供几个选项。",
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("总体：不通过", completed.stdout)
        self.assertIn("有什么可以帮", completed.stdout)
        self.assertIn("反机械", completed.stdout)

    def test_personality_script_audits_latest_cc_connect_reply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = Path(tmpdir) / "VELA_test.json"
            session.write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {"role": "user", "content": "/VELA 我现在有点乱", "timestamp": "2026-05-25T10:00:00+08:00"},
                                    {
                                        "role": "assistant",
                                        "content": "别把雾当地图。你要我先判断人、事，还是路线？说一个，我来切。",
                                        "timestamp": "2026-05-25T10:00:02+08:00",
                                    },
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["VELA_CC_CONNECT_SESSIONS"] = tmpdir

            completed = subprocess.run(
                [sys.executable, "-X", "utf8", str(SCRIPT), "audit-last"],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("最近微信回包", completed.stdout)
        self.assertIn("总体：通过", completed.stdout)
        self.assertIn("别把雾当地图", completed.stdout)

    def test_personality_script_rejects_latest_mechanical_cc_connect_reply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = Path(tmpdir) / "VELA_test.json"
            session.write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "history": [
                                    {"role": "user", "content": "/VELA", "timestamp": "2026-05-25T10:00:00+08:00"},
                                    {
                                        "role": "assistant",
                                        "content": "你好，有什么可以帮你？我将首先为你提供几个选项。",
                                        "timestamp": "2026-05-25T10:00:02+08:00",
                                    },
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["VELA_CC_CONNECT_SESSIONS"] = tmpdir

            completed = subprocess.run(
                [sys.executable, "-X", "utf8", str(SCRIPT), "audit-last"],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("最近微信回包", completed.stdout)
        self.assertIn("总体：不通过", completed.stdout)
        self.assertIn("有什么可以帮", completed.stdout)

    def test_personality_script_learns_growth_note(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            notes = Path(tmpdir) / "growth-notes.md"
            notes.write_text("# VELA Growth Notes\n", encoding="utf-8")
            env = os.environ.copy()
            env["VELA_GROWTH_NOTES"] = str(notes)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(SCRIPT),
                    "learn",
                    "以后少解释身份，多给判断；冷幽默只切坏逻辑。",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("已沉淀", completed.stdout)
            self.assertIn("少解释身份，多给判断", completed.stdout)
            self.assertNotIn("有什么可以帮", completed.stdout)
            written = notes.read_text(encoding="utf-8")
            self.assertIn("少解释身份，多给判断", written)
            self.assertIn("冷幽默只切坏逻辑", written)

    def test_personality_script_records_source_material(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_notes = Path(tmpdir) / "source-material.md"
            env = os.environ.copy()
            env["VELA_SOURCE_MATERIAL"] = str(source_notes)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(SCRIPT),
                    "material",
                    "叶文洁的三观分析：长期代价比即时胜利更重要。",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("收档", completed.stdout)
            self.assertIn("先蒸馏，不复读", completed.stdout)
            self.assertIn("原句留在门外", completed.stdout)
            written = source_notes.read_text(encoding="utf-8")
            self.assertIn("叶文洁", written)
            self.assertIn("判断方式", written)
            self.assertIn("长期代价", written)

    def test_sync_script_uses_voice_contract_as_source(self):
        text = SYNC_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("voice-contract.json", text)
        self.assertIn("load_voice_contract", text)
        self.assertIn("render_agents_pressure_scenarios", text)
        self.assertIn("render_skill_pressure_scenarios", text)
        self.assertIn("render_agents_character_depth", text)
        self.assertIn("render_skill_character_depth", text)
        self.assertIn("render_agents_cadence_palette", text)
        self.assertIn("render_skill_cadence_palette", text)
        self.assertIn("render_skill_source_material_intake", text)
        self.assertIn("render_skill_live_dialogue_samples", text)
        self.assertIn("render_dialogue_quality_gate", text)
        self.assertIn("audit_latest_cc_connect_reply", text)


if __name__ == "__main__":
    unittest.main()
