from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GROWTH_NOTES = Path(os.environ.get("VELA_GROWTH_NOTES", ROOT / "VELA" / "growth-notes.md"))
SOURCE_MATERIAL = Path(os.environ.get("VELA_SOURCE_MATERIAL", ROOT / "VELA" / "source-material.md"))
CC_CONNECT_SESSIONS = Path(os.environ.get("VELA_CC_CONNECT_SESSIONS", r"C:\Users\Admin\.cc-connect\sessions"))
VOICE_CONTRACT = ROOT / "VELA" / "voice-contract.json"


def load_contract() -> dict:
    return json.loads(VOICE_CONTRACT.read_text(encoding="utf-8"))


def render_status() -> str:
    contract = load_contract()
    vectors = contract["vectors"]
    rules = "\n".join(f"- {rule}" for rule in contract["hard_rules"])
    return (
        "VELA 人格状态\n\n"
        f"骨架：{vectors['decisiveness']}\n"
        f"视野：{vectors['long_horizon']}\n"
        f"质地：{vectors['texture']}\n\n"
        "当前硬规则：\n"
        f"{rules}\n\n"
        f"契约源：{contract['contract_source']}"
    )


GROWTH_HEADER = """VELA 成长记录

成长不是换皮，是蒸馏。留下有效的判断习惯，砍掉会让她变机械的废话。"""


SOURCE_HEADER = """# VELA Source Material

人物素材不是台词库。每条素材先蒸馏，不复读；只保留判断方式、执行姿态、语言节奏和人味底色。"""


def render_voice() -> str:
    contract = load_contract()
    lines = [
        "VELA 语气校准",
        "",
        "不要把所有回复压成同一个模板。她不是客服，不是播报员，也不是穿军装的菜单。",
        "",
        "句法规则：",
    ]
    for label, scenario in contract["pressure_scenarios"].items():
        lines.append(f"- {label}：{scenario['rule']}")
    lines.append("")
    lines.append(f"契约源：{contract['contract_source']}")
    return "\n".join(lines)


def render_probe() -> str:
    contract = load_contract()
    lines = ["VELA 对话压测"]
    for label, scenario in contract["pressure_scenarios"].items():
        lines.extend(["", label, scenario["example"]])
    lines.extend(["", "人物素材", contract["source_material_intake"]["example"]])
    lines.extend(["", f"契约源：{contract['contract_source']}"])
    return "\n".join(lines)


def render_litmus() -> str:
    contract = load_contract()
    lines = ["VELA 真人对话压测"]
    for label, sample in contract["live_dialogue_samples"].items():
        lines.extend(["", label, f"用户：{sample['user']}", f"VELA：{sample['reply']}"])
    lines.extend(["", f"契约源：{contract['contract_source']}"])
    return "\n".join(lines)


def audit_reply(reply: str, contract: dict) -> dict:
    gates = contract["dialogue_quality_gates"]
    forbidden = [phrase for phrase in gates["forbidden_phrases"] if phrase.lower() in reply.lower()]
    dimensions: dict[str, bool] = {}
    for label, keywords in gates["dimensions"].items():
        if label == "反机械":
            dimensions[label] = not forbidden and len(reply) <= gates["max_reply_chars"]
        else:
            dimensions[label] = any(keyword in reply for keyword in keywords)
    score = sum(1 for passed in dimensions.values() if passed)
    passed = dimensions.get("反机械", False) and score >= gates["pass_threshold"]
    return {
        "passed": passed,
        "score": score,
        "dimensions": dimensions,
        "forbidden": forbidden,
        "length": len(reply),
    }


def render_dialogue_audit(custom_reply: str = "") -> tuple[str, bool]:
    contract = load_contract()
    if custom_reply:
        items = [("输入回复", custom_reply)]
    else:
        items = [(label, sample["reply"]) for label, sample in contract["live_dialogue_samples"].items()]

    lines = ["VELA 对话质检", ""]
    all_passed = True
    for label, reply in items:
        result = audit_reply(reply, contract)
        all_passed = all_passed and result["passed"]
        state = "通过" if result["passed"] else "不通过"
        dimension_text = " ".join(
            f"{name}:{'✓' if passed else '×'}" for name, passed in result["dimensions"].items()
        )
        lines.extend(
            [
                f"{label}：{state}",
                f"- {dimension_text}",
                f"- 字数：{result['length']}",
            ]
        )
        if result["forbidden"]:
            lines.append(f"- 命中禁用：{'、'.join(result['forbidden'])}")
        lines.append(f"- 样本：{reply}")
        lines.append("")
    lines.append(f"总体：{'通过' if all_passed else '不通过'}")
    return "\n".join(lines).rstrip(), all_passed


def iter_session_assistant_messages(session_data: dict) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    for session in session_data.get("sessions", {}).values():
        for item in session.get("history", []):
            if item.get("role") == "assistant" and item.get("content"):
                messages.append((item.get("timestamp", ""), item["content"]))
    return messages


def latest_cc_connect_reply() -> tuple[str, Path | None]:
    candidates: list[tuple[str, float, Path, str]] = []
    if not CC_CONNECT_SESSIONS.exists():
        return "", None
    for path in CC_CONNECT_SESSIONS.glob("VELA*.json"):
        if ".bak-" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for timestamp, content in iter_session_assistant_messages(data):
            candidates.append((timestamp, path.stat().st_mtime, path, content))
    if not candidates:
        return "", None
    candidates.sort(key=lambda item: (item[0], item[1]))
    _timestamp, _mtime, path, content = candidates[-1]
    return content, path


def audit_latest_cc_connect_reply() -> tuple[str, bool]:
    reply, path = latest_cc_connect_reply()
    if not reply:
        return "VELA 对话质检\n\n最近微信回包：不通过\n- 没有找到 cc-connect assistant 回包。\n\n总体：不通过", False
    output, passed = render_dialogue_audit(reply)
    source = str(path) if path else "unknown"
    output = output.replace("输入回复：", f"最近微信回包：", 1)
    return f"{output}\n- 来源：{source}", passed


def render_profile() -> str:
    contract = load_contract()
    depth = contract["character_depth"]
    lines = [
        "VELA 人物画像",
        "",
        depth["relationship_stance"],
        depth["silence_rule"],
        depth["human_texture"],
        depth["anti_flattening"],
        "",
        f"契约源：{contract['contract_source']}",
    ]
    return "\n".join(lines)


def render_samples() -> str:
    contract = load_contract()
    lines = ["VELA 对白样本"]
    for label, item in contract["cadence_palette"].items():
        lines.extend(["", label, item["example"]])
    lines.extend(["", f"契约源：{contract['contract_source']}"])
    return "\n".join(lines)


def render_growth() -> str:
    notes = GROWTH_NOTES.read_text(encoding="utf-8").strip()
    body = notes.splitlines()[1:] if notes.startswith("# ") else notes.splitlines()
    cleaned = "\n".join(line for line in body if line.strip()).strip()
    return f"{GROWTH_HEADER}\n\n{cleaned}"


def normalize_growth_note(text: str) -> str:
    return " ".join(text.replace("\r", " ").replace("\n", " ").split()).strip(" -。")


def record_growth_note(text: str) -> str:
    note = normalize_growth_note(text)
    if not note:
        return "给我一条能沉淀的修正。空话不入档，噪音没有长期价值。"
    GROWTH_NOTES.parent.mkdir(parents=True, exist_ok=True)
    if not GROWTH_NOTES.exists():
        GROWTH_NOTES.write_text("# VELA Growth Notes\n", encoding="utf-8")
    existing = GROWTH_NOTES.read_text(encoding="utf-8").rstrip()
    stamp = datetime.now().strftime("%Y-%m-%d")
    entry = f"- {stamp}: {note}"
    if note not in existing:
        GROWTH_NOTES.write_text(existing + "\n" + entry + "\n", encoding="utf-8")
    return f"已沉淀。不是换皮，是校准：{note}"


def render_source_protocol() -> str:
    contract = load_contract()
    intake = contract["source_material_intake"]
    buckets = "、".join(intake["buckets"])
    return (
        "VELA 素材吸收协议\n\n"
        f"{intake['rule']}\n"
        f"{intake['copyright_boundary']}\n\n"
        f"示例：{intake['example']}\n\n"
        f"收档桶：{buckets}\n"
        "用法：素材 <台词/三观分析/人物旁白>。我会收成规则，不让她变成拼贴。"
    )


def classify_source_material(note: str) -> list[str]:
    buckets: list[str] = []
    if any(key in note for key in ["叶文洁", "三体", "长期", "未来", "代价", "文明", "沉默"]):
        buckets.append("判断方式")
    if any(key in note for key in ["巴拉莱卡", "黑礁", "执行", "果决", "军官", "铁血", "嘲讽"]):
        buckets.append("执行姿态")
    if any(key in note for key in ["台词", "旁白", "语气", "节奏", "冷幽默", "嘲讽"]):
        buckets.append("语言节奏")
    if any(key in note for key in ["周迅", "质感", "底色", "烟火", "旧伤", "克制", "人味"]):
        buckets.append("人味底色")
    if any(key in note for key in ["模仿", "复读", "照搬", "台词库", "复制"]):
        buckets.append("边界禁区")
    return buckets or ["判断方式"]


def record_source_material(text: str) -> str:
    note = normalize_growth_note(text)
    if not note:
        return render_source_protocol()

    SOURCE_MATERIAL.parent.mkdir(parents=True, exist_ok=True)
    if not SOURCE_MATERIAL.exists():
        SOURCE_MATERIAL.write_text(SOURCE_HEADER + "\n", encoding="utf-8")

    existing = SOURCE_MATERIAL.read_text(encoding="utf-8").rstrip()
    stamp = datetime.now().strftime("%Y-%m-%d")
    buckets = "、".join(classify_source_material(note))
    excerpt = note if len(note) <= 240 else note[:237] + "..."
    entry = (
        f"\n- {stamp} | 桶：{buckets}\n"
        f"  素材：{excerpt}\n"
        "  蒸馏：先蒸馏，不复读；吸收判断方式、执行姿态、语言节奏和人味底色，禁止建立台词库。\n"
    )
    if note not in existing:
        SOURCE_MATERIAL.write_text(existing + entry, encoding="utf-8")
    return f"收档。先蒸馏，不复读：{buckets}。原句留在门外。"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("mode", nargs="?", default="status")
    parser.add_argument("text", nargs=argparse.REMAINDER)
    args, _unknown = parser.parse_known_args(argv)

    mode = args.mode.lower()
    if mode in {"growth", "成长"}:
        print(render_growth())
    elif mode in {"learn", "学习", "remember", "沉淀"}:
        print(record_growth_note(" ".join(args.text)))
    elif mode in {"material", "素材", "source", "补充"}:
        print(record_source_material(" ".join(args.text)))
    elif mode in {"profile", "portrait", "画像"}:
        print(render_profile())
    elif mode in {"samples", "sample", "dialogue", "对白", "样本"}:
        print(render_samples())
    elif mode in {"voice", "tone", "语气"}:
        print(render_voice())
    elif mode in {"probe", "test", "压测"}:
        print(render_probe())
    elif mode in {"litmus", "真人", "对话压测", "live"}:
        print(render_litmus())
    elif mode in {"audit", "质检", "quality", "gate"}:
        output, passed = render_dialogue_audit(" ".join(args.text))
        print(output)
        return 0 if passed else 1
    elif mode in {"audit-last", "最近质检", "last-audit", "wechat-audit"}:
        output, passed = audit_latest_cc_connect_reply()
        print(output)
        return 0 if passed else 1
    else:
        print(render_status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
