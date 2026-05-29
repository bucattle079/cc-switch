from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None


MAX_OUTPUT_CHARS = 3600
DEFAULT_THREAD_LIMIT = 5
DEFAULT_HISTORY_LIMIT = 6
BOT_DISPLAY_NAME = "VELA"


class ThreadSummary(NamedTuple):
    id: str
    title: str
    cwd: str
    rollout_path: str
    updated_at_ms: int
    model: str
    reasoning_effort: str
    approval_mode: str
    sandbox_policy: str
    tokens_used: int
    preview: str


class GoalSummary(NamedTuple):
    thread_id: str
    objective: str
    status: str
    tokens_used: int
    token_budget: int | None
    time_used_seconds: int
    updated_at_ms: int


class RolloutMessage(NamedTuple):
    role: str
    text: str


class CompletedTask(NamedTuple):
    thread: ThreadSummary
    completed_at: int
    duration_ms: int
    user_request: str
    final_message: str


SECRET_KEYS = (
    "token",
    "api_key",
    "apikey",
    "secret",
    "bot_secret",
    "bot_token",
    "password",
    "proxy_password",
)


def redact_secret_text(text: str) -> str:
    keys = "|".join(re.escape(k) for k in SECRET_KEYS)
    quoted = re.compile(rf"(?im)^(\s*(?:{keys})\s*=\s*)([\"']).*?\2\s*$")
    unquoted = re.compile(rf"(?im)^(\s*(?:{keys})\s*=\s*)\S+\s*$")
    text = quoted.sub(r'\1"***"', text)
    return unquoted.sub(r'\1"***"', text)


def clean_path(value: str | Path | None) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return text


def public_workspace_label(value: str | Path | None) -> str:
    text = clean_path(value)
    if not text:
        return "未配置"
    try:
        label = Path(text).name
    except (OSError, ValueError):
        label = ""
    return label or "本地工作区"


def truncate(text: str, max_chars: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def format_time(ms: int | None) -> str:
    if not ms:
        return "未知"
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "未知"


def format_unix_time(seconds: int | None) -> str:
    if not seconds:
        return "未知"
    try:
        return datetime.fromtimestamp(int(seconds)).strftime("%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "未知"


def home_dir() -> Path:
    return Path.home()


def default_codex_home() -> Path:
    return Path(os.environ.get("CLAWBOT_CODEX_HOME", home_dir() / ".codex"))


def default_cc_home() -> Path:
    return Path(os.environ.get("CLAWBOT_CC_CONNECT_HOME", home_dir() / ".cc-connect"))


def ensure_utf8_stdio(stdout: Any | None = None, stderr: Any | None = None) -> None:
    for stream in (stdout or sys.stdout, stderr or sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if tomllib is None:
        return {}
    try:
        return tomllib.loads(raw)
    except Exception:
        return {}


def cc_config_summary(cc_home: Path) -> dict[str, str]:
    cfg = load_toml(cc_home / "config.toml")
    projects = cfg.get("projects") or []
    project = projects[0] if projects else {}
    agent = project.get("agent") or {}
    agent_options = agent.get("options") or {}
    platforms = project.get("platforms") or []
    weixin = next((p for p in platforms if p.get("type") == "weixin"), {})
    weixin_options = weixin.get("options") or {}
    return {
        "project": str(project.get("name") or "未配置"),
        "agent": str(agent.get("type") or "未配置"),
        "mode": str(agent_options.get("mode") or "未配置"),
        "cmd": str(agent_options.get("cmd") or "codex"),
        "work_dir": str(agent_options.get("work_dir") or ""),
        "platform": str(weixin.get("type") or "未配置"),
        "allow_from": str(weixin_options.get("allow_from") or ""),
        "account_id": str(weixin_options.get("account_id") or ""),
    }


def sqlite_connect_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"pragma table_info({table})")}
    except sqlite3.Error:
        return set()


def select_expr(columns: set[str], name: str, default: str = "NULL") -> str:
    if name in columns:
        return name
    return f"{default} as {name}"


def query_threads(codex_home: Path, limit: int = DEFAULT_THREAD_LIMIT) -> list[ThreadSummary]:
    conn = sqlite_connect_readonly(codex_home / "state_5.sqlite")
    if conn is None:
        return []
    try:
        cols = table_columns(conn, "threads")
        if not cols:
            return []
        fields = [
            select_expr(cols, "id"),
            select_expr(cols, "title", "''"),
            select_expr(cols, "cwd", "''"),
            select_expr(cols, "rollout_path", "''"),
            select_expr(cols, "updated_at_ms", "0"),
            select_expr(cols, "model", "''"),
            select_expr(cols, "reasoning_effort", "''"),
            select_expr(cols, "approval_mode", "''"),
            select_expr(cols, "sandbox_policy", "''"),
            select_expr(cols, "tokens_used", "0"),
            select_expr(cols, "preview", "''"),
        ]
        where = "where archived = 0" if "archived" in cols else ""
        order = "updated_at_ms desc" if "updated_at_ms" in cols else "rowid desc"
        rows = conn.execute(
            f"select {', '.join(fields)} from threads {where} order by {order} limit ?",
            (limit,),
        ).fetchall()
        return [
            ThreadSummary(
                id=str(row[0] or ""),
                title=str(row[1] or ""),
                cwd=clean_path(row[2]),
                rollout_path=clean_path(row[3]),
                updated_at_ms=int(row[4] or 0),
                model=str(row[5] or ""),
                reasoning_effort=str(row[6] or ""),
                approval_mode=str(row[7] or ""),
                sandbox_policy=str(row[8] or ""),
                tokens_used=int(row[9] or 0),
                preview=str(row[10] or ""),
            )
            for row in rows
        ]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def query_goals(codex_home: Path, limit: int = 3) -> list[GoalSummary]:
    conn = sqlite_connect_readonly(codex_home / "goals_1.sqlite")
    if conn is None:
        return []
    try:
        cols = table_columns(conn, "thread_goals")
        if not cols:
            return []
        fields = [
            select_expr(cols, "thread_id"),
            select_expr(cols, "objective", "''"),
            select_expr(cols, "status", "''"),
            select_expr(cols, "tokens_used", "0"),
            select_expr(cols, "token_budget"),
            select_expr(cols, "time_used_seconds", "0"),
            select_expr(cols, "updated_at_ms", "0"),
        ]
        rows = conn.execute(
            f"""
            select {', '.join(fields)}
            from thread_goals
            order by case status when 'active' then 0 when 'blocked' then 1 else 2 end,
                     updated_at_ms desc
            limit ?
            """,
            (limit,),
        ).fetchall()
        return [
            GoalSummary(
                thread_id=str(row[0] or ""),
                objective=str(row[1] or ""),
                status=str(row[2] or "unknown"),
                tokens_used=int(row[3] or 0),
                token_budget=None if row[4] is None else int(row[4]),
                time_used_seconds=int(row[5] or 0),
                updated_at_ms=int(row[6] or 0),
            )
            for row in rows
        ]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def parse_sandbox(policy: str) -> str:
    if not policy:
        return "未知"
    try:
        data = json.loads(policy)
    except json.JSONDecodeError:
        return truncate(policy, 42)
    if isinstance(data, dict):
        return str(data.get("type") or data.get("sandbox_mode") or "未知")
    return truncate(str(data), 42)


def detect_cc_connect_running() -> str:
    try:
        if os.name == "nt":
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "(Get-Process cc-connect -ErrorAction SilentlyContinue | Select-Object -First 1).Id",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return "运行中" if result.stdout.strip() else "未检测到"
        result = subprocess.run(["pgrep", "-f", "cc-connect"], capture_output=True, text=True, timeout=3)
        return "运行中" if result.stdout.strip() else "未检测到"
    except Exception:
        return "未知"


def extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("input_text") or item.get("output_text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def is_internal_user_message(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("<goal_context>") or stripped.startswith("<environment_context>")


def extract_rollout_messages(path: Path, limit: int = DEFAULT_HISTORY_LIMIT) -> list[RolloutMessage]:
    if not path.exists():
        return []
    messages: list[RolloutMessage] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = row.get("payload") if isinstance(row, dict) else None
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") != "message":
                    continue
                role = str(payload.get("role") or "")
                if role not in {"user", "assistant"}:
                    continue
                text = truncate(extract_content_text(payload.get("content")), 260)
                if text:
                    messages.append(RolloutMessage(role=role, text=text))
    except OSError:
        return []
    return messages[-limit:]


def extract_completed_tasks(thread: ThreadSummary) -> list[CompletedTask]:
    path = Path(thread.rollout_path)
    if not path.exists():
        return []

    current_turn_id = ""
    turn_user_messages: dict[str, str] = {}
    completed: list[CompletedTask] = []

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = row.get("payload") if isinstance(row, dict) else None
                if not isinstance(payload, dict):
                    continue

                row_type = row.get("type")
                payload_type = payload.get("type")

                if row_type == "turn_context":
                    current_turn_id = str(payload.get("turn_id") or "")
                    continue

                if row_type == "event_msg" and payload_type == "user_message" and current_turn_id:
                    message = extract_content_text(payload.get("message")) or str(payload.get("message") or "")
                    if message and not is_internal_user_message(message):
                        turn_user_messages[current_turn_id] = message
                    continue

                if row_type == "response_item" and payload_type == "message":
                    role = str(payload.get("role") or "")
                    if role == "user" and current_turn_id:
                        text = extract_content_text(payload.get("content"))
                        if text and not is_internal_user_message(text):
                            turn_user_messages[current_turn_id] = text
                    continue

                if row_type == "event_msg" and payload_type == "task_complete":
                    final_message = str(payload.get("last_agent_message") or "").strip()
                    if not final_message:
                        continue
                    turn_id = str(payload.get("turn_id") or current_turn_id)
                    completed.append(
                        CompletedTask(
                            thread=thread,
                            completed_at=int(payload.get("completed_at") or thread.updated_at_ms // 1000 or 0),
                            duration_ms=int(payload.get("duration_ms") or 0),
                            user_request=turn_user_messages.get(turn_id, ""),
                            final_message=final_message,
                        )
                    )
    except OSError:
        return []
    return completed


def find_latest_completed_task(codex_home: Path | None = None, limit: int = 50) -> CompletedTask | None:
    threads = query_threads(codex_home or default_codex_home(), limit=limit)
    tasks: list[CompletedTask] = []
    for thread in threads:
        tasks.extend(extract_completed_tasks(thread))
    if not tasks:
        return None
    return max(tasks, key=lambda task: (task.completed_at, task.thread.updated_at_ms))


def strip_internal_tail(text: str) -> str:
    text = text.split("<oai-mem-citation>", 1)[0]
    kept: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("::git-"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def final_paragraph(text: str) -> str:
    cleaned = strip_internal_tail(text)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if not paragraphs:
        return truncate(cleaned, 900)
    return paragraphs[-1].strip()


def snapshot_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "VELA" / "codex-snapshots"


def render_snapshot_with_powershell(text_path: Path, image_path: Path) -> bool:
    ps_script = r'''
param([string]$TextPath, [string]$OutPath)
Add-Type -AssemblyName System.Drawing

$text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)
$width = 1120
$padding = 42
$fontTitle = New-Object System.Drawing.Font("Microsoft YaHei UI", 24, [System.Drawing.FontStyle]::Bold)
$fontBody = New-Object System.Drawing.Font("Microsoft YaHei UI", 18, [System.Drawing.FontStyle]::Regular)
$fontSmall = New-Object System.Drawing.Font("Microsoft YaHei UI", 12, [System.Drawing.FontStyle]::Regular)

$probe = New-Object System.Drawing.Bitmap($width, 10)
$graphics = [System.Drawing.Graphics]::FromImage($probe)
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$bodyWidth = $width - ($padding * 2)
$measure = $graphics.MeasureString($text, $fontBody, $bodyWidth)
$graphics.Dispose()
$probe.Dispose()

$height = [Math]::Min([Math]::Max([int]$measure.Height + 190, 560), 1900)
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$g = [System.Drawing.Graphics]::FromImage($bitmap)
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([System.Drawing.Color]::FromArgb(248, 249, 251))

$brushTitle = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(22, 28, 36))
$brushBody = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(31, 41, 55))
$brushMuted = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(100, 116, 139))
$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(203, 213, 225), 2)

$g.DrawString("VELA · Codex 最近完成结论", $fontTitle, $brushTitle, $padding, 34)
$g.DrawString("本地生成截图，用于微信回传最后结论段。", $fontSmall, $brushMuted, $padding, 78)
$g.DrawLine($pen, $padding, 112, $width - $padding, 112)
$rect = New-Object System.Drawing.RectangleF -ArgumentList ([single]$padding), ([single]138), ([single]$bodyWidth), ([single]($height - 178))
$g.DrawString($text, $fontBody, $brushBody, $rect)
$g.DrawString((Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $fontSmall, $brushMuted, $padding, $height - 34)

$bitmap.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bitmap.Dispose()
'''
    script_path = image_path.with_suffix(".render.ps1")
    script_path.write_text(ps_script, encoding="utf-8-sig", newline="\n")
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                str(text_path),
                str(image_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return result.returncode == 0 and not result.stderr.strip() and image_path.exists()
    except Exception:
        return False
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except OSError:
            pass


def create_task_snapshot(task: CompletedTask) -> tuple[Path, Path | None, str]:
    out_dir = snapshot_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(task.completed_at or int(datetime.now().timestamp())).strftime("%Y%m%d-%H%M%S")
    base = out_dir / f"codex-latest-{stamp}"
    paragraph = final_paragraph(task.final_message)
    text = "\n".join(
        [
            f"项目：{truncate(task.thread.title or task.thread.id, 90)}",
            f"工作区：{public_workspace_label(task.thread.cwd)}",
            f"完成：{format_unix_time(task.completed_at)}",
            "",
            "最后结论：",
            paragraph,
        ]
    )
    text_path = base.with_suffix(".txt")
    image_path = base.with_suffix(".png")
    text_path.write_text(text, encoding="utf-8", newline="\n")
    if render_snapshot_with_powershell(text_path, image_path):
        return text_path, image_path, paragraph
    return text_path, None, paragraph


def send_image_to_active_chat(image_path: Path) -> tuple[bool, str]:
    cmd = shutil.which("cc-connect") or shutil.which("cc-connect.cmd")
    if not cmd:
        npm_cmd = home_dir() / "AppData" / "Roaming" / "npm" / "cc-connect.cmd"
        if npm_cmd.exists():
            cmd = str(npm_cmd)
    if not cmd:
        return False, "未找到 cc-connect 命令"
    try:
        result = subprocess.run(
            [cmd, "send", "--project", BOT_DISPLAY_NAME, "--image", str(image_path)],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, "已发送"
    return False, truncate((result.stderr or result.stdout or "发送失败").strip(), 180)


def resolve_thread(threads: list[ThreadSummary], target: str | None) -> ThreadSummary | None:
    if not threads:
        return None
    if not target:
        return threads[0]
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(threads):
            return threads[idx]
    for thread in threads:
        if thread.id.startswith(target) or target in thread.title:
            return thread
    return None


def render_status(codex_home: Path | None = None, cc_home: Path | None = None) -> str:
    codex_home = codex_home or default_codex_home()
    cc_home = cc_home or default_cc_home()
    cfg = cc_config_summary(cc_home)
    threads = query_threads(codex_home)
    goals = query_goals(codex_home)
    lines = [
        f"{BOT_DISPLAY_NAME} · Codex 控制台",
        "",
        "连接",
        f"- cc-connect: {detect_cc_connect_running()}",
        f"- WeChat: {cfg['platform']} / account {cfg['account_id'] or '未配置'}",
        f"- Codex: {cfg['cmd']} / 权限: {cfg['mode']}",
        f"- 工作区: {public_workspace_label(cfg['work_dir'])}",
        "- AI 标识: 保持微信/iLink 原设置",
        "",
    ]
    if goals:
        lines.append("目标")
        for goal in goals[:2]:
            budget = "无预算" if goal.token_budget is None else f"{goal.tokens_used}/{goal.token_budget}"
            lines.append(f"- {goal.status}: {truncate(goal.objective, 92)} ({budget}, {format_time(goal.updated_at_ms)})")
        lines.append("")
    if threads:
        lines.append("最近 Codex 项目")
        for idx, thread in enumerate(threads, start=1):
            sandbox = parse_sandbox(thread.sandbox_policy)
            title = truncate(thread.title or thread.preview or thread.id, 72)
            workspace = public_workspace_label(thread.cwd)
            lines.append(f"{idx}. {title}")
            lines.append(
                f"   {format_time(thread.updated_at_ms)} | {thread.model or 'model?'} | sandbox {sandbox} | approval {thread.approval_mode or '?'}"
            )
            lines.append(f"   工作区: {workspace}")
    else:
        lines.extend(["最近 Codex 项目", "- 未找到 Codex thread 状态库"])
    lines.extend(
        [
            "",
            "微信命令",
            "- /vela 或 /clawbot: 总览",
            "- /CODEX: 查看最近完成的 Codex 任务结论，并生成截图",
            "- /clawbot projects: 项目列表",
            "- /clawbot history 1 6: 查看第 1 个项目最近 6 条对话",
            "- /mode yolo: 保持最高执行权限",
        ]
    )
    return clip_output("\n".join(lines))


def render_projects(codex_home: Path | None = None) -> str:
    threads = query_threads(codex_home or default_codex_home(), limit=10)
    lines = [f"{BOT_DISPLAY_NAME} · Codex 项目", ""]
    for idx, thread in enumerate(threads, start=1):
        lines.append(f"{idx}. {truncate(thread.title or thread.preview or thread.id, 90)}")
        lines.append(f"   ID: {thread.id}")
        lines.append(f"   工作区: {public_workspace_label(thread.cwd)}")
        lines.append(f"   更新: {format_time(thread.updated_at_ms)} | tokens {thread.tokens_used}")
    if not threads:
        lines.append("- 未找到项目")
    return clip_output("\n".join(lines))


def render_goals(codex_home: Path | None = None) -> str:
    goals = query_goals(codex_home or default_codex_home(), limit=8)
    lines = [f"{BOT_DISPLAY_NAME} · Codex 目标", ""]
    for goal in goals:
        budget = "无预算" if goal.token_budget is None else f"{goal.tokens_used}/{goal.token_budget}"
        lines.append(f"- {goal.status}: {truncate(goal.objective, 120)}")
        lines.append(f"  thread: {goal.thread_id} | {budget} | {format_time(goal.updated_at_ms)}")
    if not goals:
        lines.append("- 未找到目标记录")
    return clip_output("\n".join(lines))


def render_history(codex_home: Path | None = None, target: str | None = None, limit: int = DEFAULT_HISTORY_LIMIT) -> str:
    threads = query_threads(codex_home or default_codex_home(), limit=20)
    thread = resolve_thread(threads, target)
    if thread is None:
        return f"{BOT_DISPLAY_NAME} · Codex 对话\n\n未找到对应项目。先用 /vela projects 查看编号。"
    messages = extract_rollout_messages(Path(thread.rollout_path), limit=limit)
    lines = [
        f"{BOT_DISPLAY_NAME} · Codex 对话",
        "",
        f"项目: {truncate(thread.title or thread.id, 96)}",
        f"工作区: {public_workspace_label(thread.cwd)}",
        "",
    ]
    for msg in messages:
        role = "你" if msg.role == "user" else "Codex"
        lines.append(f"{role}: {msg.text}")
    if not messages:
        lines.append("- 没有可读取的最近对话")
    return clip_output("\n".join(lines))


def render_codex_latest(send_image: bool = True, codex_home: Path | None = None) -> str:
    task = find_latest_completed_task(codex_home)
    if task is None:
        return (
            f"{BOT_DISPLAY_NAME} · CODEX 最近完成\n\n"
            "没找到已完成任务记录。不是坏消息，只是账本还没留下可读结论。"
        )

    text_path, image_path, paragraph = create_task_snapshot(task)
    send_note = "截图未生成"
    if image_path is not None:
        send_note = "截图已生成。"
        if send_image:
            sent, detail = send_image_to_active_chat(image_path)
            send_note = "截图已回传微信。" if sent else "截图已生成，但自动回传失败；需要我再试一次。"

    lines = [
        f"{BOT_DISPLAY_NAME} · CODEX 最近完成",
        "",
        f"项目: {truncate(task.thread.title or task.thread.id, 80)}",
        f"工作区: {public_workspace_label(task.thread.cwd)}",
        f"完成: {format_unix_time(task.completed_at)}",
    ]
    if task.user_request:
        lines.append(f"任务: {truncate(task.user_request, 130)}")
    lines.extend(
        [
            "",
            "最后结论",
            paragraph,
            "",
            send_note,
            "文本备份已保存。",
        ]
    )
    return clip_output("\n".join(lines))


def render_wechat(cc_home: Path | None = None) -> str:
    cc_home = cc_home or default_cc_home()
    cfg = cc_config_summary(cc_home)
    lines = [
        f"{BOT_DISPLAY_NAME} · WeChat 连接",
        "",
        f"- cc-connect: {detect_cc_connect_running()}",
        f"- project: {cfg['project']}",
        f"- platform: {cfg['platform']}",
        f"- allow_from: {cfg['allow_from'] or '未配置'}",
        f"- account_id: {cfg['account_id'] or '未配置'}",
        f"- mode: {cfg['mode']}",
        "- header 名称: 目标为 VELA；若微信仍显示旧名，请在 iLink/微信机器人账号侧改昵称；本机配置不改 AI 标识。",
    ]
    return clip_output("\n".join(lines))


def render_help() -> str:
    return "\n".join(
        [
            f"{BOT_DISPLAY_NAME} · 帮助",
            "",
            "/vela",
            "/CODEX",
            "/vela projects",
            "/vela goals",
            "/vela history 1 6",
            "/vela wechat",
            "/clawbot",
            "",
            "权限已由 cc-connect 的 Codex mode 控制；最高权限为 yolo。",
        ]
    )


def clip_output(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    suffix = "\n\n[输出已截断，可用更具体的子命令继续查看]"
    return text[: MAX_OUTPUT_CHARS - len(suffix)] + suffix


def parse_limit(value: str | None, default: int) -> int:
    try:
        parsed = int(value or "")
    except ValueError:
        return default
    return max(1, min(parsed, 20))


def main(argv: list[str]) -> int:
    ensure_utf8_stdio()
    command = argv[0].lower() if argv else "status"
    args = argv[1:] if argv else []
    if command in {"status", "状态", "总览", "overview"}:
        output = render_status()
    elif command in {"projects", "project", "项目"}:
        output = render_projects()
    elif command in {"goals", "goal", "目标"}:
        output = render_goals()
    elif command in {"history", "thread", "对话", "历史"}:
        target = args[0] if args else None
        limit = parse_limit(args[1] if len(args) > 1 else None, DEFAULT_HISTORY_LIMIT)
        output = render_history(target=target, limit=limit)
    elif command in {"codex", "latest", "最近任务", "最近完成"}:
        output = render_codex_latest(send_image="--no-send" not in args)
    elif command in {"wechat", "weixin", "微信"}:
        output = render_wechat()
    elif command in {"help", "-h", "--help", "帮助"}:
        output = render_help()
    else:
        output = render_status()
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
