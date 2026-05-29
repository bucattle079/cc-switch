import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "clawbot_codex_console.py"


def load_console_module():
    spec = importlib.util.spec_from_file_location("clawbot_codex_console", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ClawbotCodexConsoleTests(unittest.TestCase):
    def test_final_paragraph_ignores_internal_tails(self):
        console = load_console_module()

        text = "Done.\n\nFinal conclusion.\n::git-stage{cwd=\"x\"}\n<oai-mem-citation>hidden"

        self.assertEqual(console.final_paragraph(text), "Final conclusion.")

    def test_completed_tasks_skip_goal_context_user_message(self):
        console = load_console_module()
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "rollout.jsonl"
            rows = [
                {"type": "turn_context", "payload": {"turn_id": "turn-1"}},
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "<goal_context>internal</goal_context>"},
                },
                {"type": "event_msg", "payload": {"type": "user_message", "message": "real user task"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "task_complete",
                        "turn_id": "turn-1",
                        "completed_at": 1779615913,
                        "duration_ms": 1234,
                        "last_agent_message": "Summary.\n\nFinal answer.",
                    },
                },
            ]
            rollout.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            thread = console.ThreadSummary(
                id="thread-1",
                title="Thread",
                cwd=str(Path(tmp)),
                rollout_path=str(rollout),
                updated_at_ms=1779615913000,
                model="gpt-test",
                reasoning_effort="medium",
                approval_mode="never",
                sandbox_policy='{"type":"danger-full-access"}',
                tokens_used=100,
                preview="",
            )

            tasks = console.extract_completed_tasks(thread)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].user_request, "real user task")
        self.assertEqual(console.final_paragraph(tasks[0].final_message), "Final answer.")

    def test_new_codex_command_is_listed_in_status(self):
        console = load_console_module()

        help_text = console.render_help()

        self.assertIn("/CODEX", help_text)


if __name__ == "__main__":
    unittest.main()
