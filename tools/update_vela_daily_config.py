from __future__ import annotations

import re
from pathlib import Path


CONFIG = Path(r"C:\Users\Admin\.cc-connect\config.toml")

DAILY_COMMAND = '''[[commands]]
name = "vela-daily-briefing"
description = "VELA overnight intelligence briefing via local UTF-8 sender"
exec = "python -X utf8 \\"C:/Users/Admin/Desktop/CC-WECHAT/tools/vela_daily_briefing.py\\""
work_dir = "C:/Users/Admin/Desktop/CC-WECHAT"

'''


def replace_or_insert_daily_command(text: str) -> str:
    pattern = re.compile(
        r'\[\[commands\]\]\s*\nname = "vela-daily-briefing"\s*\n.*?(?=\n\[\[(?:commands|aliases|projects)\]\]|\Z)',
        re.S,
    )
    if pattern.search(text):
        return pattern.sub(DAILY_COMMAND.rstrip(), text)

    marker = '[[commands]]\nname = "vela-talk"'
    if marker in text:
        return text.replace(marker, DAILY_COMMAND + marker, 1)
    return DAILY_COMMAND + text


def ensure_project_quiet_fields(text: str) -> str:
    project_marker = '[[projects]]\nname = "VELA"'
    if project_marker not in text:
        return text
    project_start = text.index(project_marker)
    next_table = text.find("\n[projects.agent]", project_start)
    if next_table == -1:
        return text
    head = text[:next_table]
    tail = text[next_table:]
    additions = []
    for line in [
        "quiet = true",
        "show_context_indicator = false",
        "reply_footer = false",
    ]:
        if line not in head[project_start:]:
            additions.append(line)
    if additions:
        head += "\n" + "\n".join(additions) + "\n"
    return head + tail


def main() -> int:
    text = CONFIG.read_text(encoding="utf-8")
    text = replace_or_insert_daily_command(text)
    text = ensure_project_quiet_fields(text)
    CONFIG.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
