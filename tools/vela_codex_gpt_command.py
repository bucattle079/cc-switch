from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]

VELA_PROMPT_CORE = (
    "你是 VELA，不是客服。你是冷静战略参谋：先判断目标，再切断噪音，最后给最短有效路径。"
    "表达比例：冷静判断55%，战略拆解18%，赛博神性13%，毒舌幽默14%。"
    "称呼用户为 K。短、准、有判断；不要菜单腔，不要工程日志腔，不要过度玄学。"
)

NOISE_PATTERNS = (
    re.compile(r"raw payload", re.IGNORECASE),
    re.compile(r"debug", re.IGNORECASE),
    re.compile(r"schema_version", re.IGNORECASE),
    re.compile(r"runtime metadata", re.IGNORECASE),
    re.compile(r"adapter logs", re.IGNORECASE),
    re.compile(r"\btokens?\b", re.IGNORECASE),
    re.compile(r"\bsandbox\b", re.IGNORECASE),
    re.compile(r"\bapproval\b", re.IGNORECASE),
    re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s，。；,;]+"),
)


def build_codex_prompt(context: dict) -> str:
    return (
        f"{VELA_PROMPT_CORE}\n\n"
        "你正在为微信短回复生成最终正文。只输出给用户看的中文正文，不要输出 token、路径、debug、schema、"
        "adapter、runtime metadata、Codex 日志或工具过程。不要调用 shell，不要修改文件。\n\n"
        "如果 tool_policy.allow_retrieval 为 false，不要检索实时信息；只做对话或分析。"
        "如果需要检索但没有可靠来源，明确说信息不足，不要编造。\n\n"
        "上下文 JSON：\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def clean_final_text(text: str) -> str:
    lines: list[str] = []
    for line in str(text or "").splitlines():
        if any(pattern.search(line) for pattern in NOISE_PATTERNS):
            continue
        lines.append(line.rstrip())
    cleaned = "\n".join(line for line in lines if line.strip()).strip()
    if not cleaned:
        return ""
    if not cleaned.startswith("K"):
        cleaned = "K，" + cleaned
    return cleaned


def codex_launch_args() -> list[str]:
    codex = shutil.which("codex") or "codex"
    if Path(codex).suffix.lower() in {".cmd", ".bat"}:
        return ["cmd", "/d", "/c", codex]
    return [codex]


def run_codex(prompt: str, *, timeout: int, tmp_dir: Path | None = None) -> str:
    tmp_dir = tmp_dir or Path(tempfile.gettempdir())
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="vela-codex-gpt-",
        suffix=".txt",
        dir=tmp_dir,
        delete=False,
    ) as handle:
        output_path = Path(handle.name)

    model = os.environ.get("VELA_CODEX_MODEL", "gpt-5.5")
    reasoning = os.environ.get("VELA_CODEX_REASONING_EFFORT", "low")
    args = [
        *codex_launch_args(),
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-rules",
        "-s",
        "read-only",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning}"',
        "--color",
        "never",
        "-o",
        str(output_path),
        "-",
    ]
    try:
        completed = subprocess.run(
            args,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
            cwd=str(ROOT),
        )
        if completed.returncode != 0:
            return ""
        if not output_path.exists():
            return ""
        return clean_final_text(output_path.read_text(encoding="utf-8", errors="replace"))
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("VELA_CODEX_TIMEOUT_SECONDS", "180")))
    parser.add_argument("--tmp-dir", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        context = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        context = {"message": "", "intent": "normal_chat", "surface": "wechat_short_reply"}
    prompt = build_codex_prompt(context if isinstance(context, dict) else {})
    tmp_dir = Path(args.tmp_dir) if args.tmp_dir else None
    text = run_codex(prompt, timeout=args.timeout, tmp_dir=tmp_dir)
    if not text:
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
