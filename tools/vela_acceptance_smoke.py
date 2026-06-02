from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import vela_router as router
import vela_reply_engine as reply_engine
from vela_product_layers import FallbackReplyAdapter, build_reply_context, run_layered_response


DEFAULT_CC_CONNECT_HOME = Path(os.environ.get("VELA_CC_CONNECT_HOME", r"C:\Users\Admin\.cc-connect"))

LEAK_TOKENS = (
    "raw payload",
    "response_quality_signals",
    "active_persona_capabilities",
    "user_message_type",
    "response_behavior_mode",
    "response_mode",
    "need_interpretation",
    "human_tone_vector",
    "persona_skeleton",
    "tool_policy",
    "should_clarify",
    "should_push_back",
    "should_use_evidence_gate",
    "should_reference_memory",
    "detected_user_state",
    "inferred_hidden_need",
    "tone_adjustment_reason",
    "tone_adjustment_candidate",
    "Preference Candidate",
    "Strategic Memory Candidate",
    "Interaction Log",
    "Session Notes",
    "user_preferences",
    "strategic_memories",
    "project_goal",
    "persona_direction",
    "memory_candidate",
    "foreground_lane",
    "latency_ms",
    "DEEPSEEK_API_KEY",
    "api_key",
    "endpoint",
    "schema",
    "schema_version",
    "diff --git",
    "raw git log",
    "Author:",
    "Date:",
    "截图已生成",
    "文本备份",
    "最后结论",
    "```",
    "debug",
    "cosplay",
    "台词",
    "扮演",
)

WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\")
CC_LOG_TIME_RE = re.compile(r"\btime=([^\s]+)")
SOURCE_NAME_LEAK_TOKENS = (
    "Dana " + "Scul" + "ly",
    "Scul" + "ly",
    "Louise " + "Banks",
    "草薙" + "素子",
    "Jane " + "Eyre",
    "Elizabeth " + "Bennet",
)
MOJIBAKE_TOKENS = (
    "锛",
    "銆",
    "浣犲",
    "鎴戝",
    "瀹炴椂",
    "鍒ゆ柇",
    "涓嬩竴",
    "甯傚満",
    "鑿滃崟",
    "闀挎湡",
    "鍊欓",
)


SINGLE_TURN_CASES = [
    {
        "id": "normal_hello",
        "message": "你好 VELA",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["在", "听着", "醒着"],
        "forbidden_reply_tokens": ["目标", "卡点", "开刀", "硌手", "混乱", "雾端", "菜单", "市场", "Codex"],
        "max_reply_chars": 40,
    },
    {
        "id": "normal_plain_hello",
        "message": "你好",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["在", "听着", "醒着"],
        "forbidden_reply_tokens": ["目标", "卡点", "开刀", "硌手", "混乱", "雾端", "菜单", "市场", "Codex"],
        "max_reply_chars": 40,
    },
    {
        "id": "normal_one_next_step",
        "message": "我现在脑子糊住了，只给我一个下一步",
        "expected_intent": "normal_chat",
    },
    {
        "id": "normal_listening_no_task",
        "message": "我只是想聊一下，不要马上给我任务",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["我听着", "你先说", "不用立刻变成任务"],
        "forbidden_reply_tokens": ["卡点", "目标", "开刀", "硌手", "混乱递过来"],
        "max_reply_chars": 120,
    },
    {
        "id": "normal_not_solution_just_annoyed",
        "message": "我不是要方案，就是有点烦",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["我听着", "你先说", "不用立刻变成任务"],
        "forbidden_reply_tokens": ["卡点", "目标", "开刀", "硌手", "混乱递过来"],
        "max_reply_chars": 120,
    },
    {
        "id": "normal_listen_first_no_analysis",
        "message": "别分析，先听我说会儿",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["我听着", "你先说", "不用立刻变成任务"],
        "forbidden_reply_tokens": ["卡点", "目标", "开刀", "硌手", "混乱递过来"],
        "max_reply_chars": 120,
    },
    {
        "id": "normal_pause_project_let_me_finish",
        "message": "现在先别推进，我想先把话说完",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["我听着", "你先说", "不用立刻变成任务"],
        "forbidden_reply_tokens": ["卡点", "目标", "开刀", "硌手", "混乱递过来"],
        "max_reply_chars": 120,
    },
    {
        "id": "daily_info_plain_sort",
        "message": "把这段逻辑整理成三条结论",
        "expected_intent": "daily_info",
    },
    {
        "id": "daily_info_real_decision_filter",
        "message": "这段方案别润色，帮我整理成可决策的三条",
        "expected_intent": "daily_info",
    },
    {
        "id": "daily_info_now_general_news_uses_deepseek_chain",
        "message": "现在DeepSeek有什么新消息",
        "expected_intent": "daily_info",
        "required_reply_tokens": ["DeepSeek API", "判断：", "下一步："],
        "forbidden_reply_tokens": ["DEEPSEEK_API_KEY", "状态边界", "VELA 市场简报", "Market & World Briefing"],
        "max_reply_chars": 260,
    },
    {
        "id": "daily_info_now_search_policy_uses_deepseek_chain",
        "message": "现在帮我查这个政策",
        "expected_intent": "daily_info",
        "required_reply_tokens": ["DeepSeek API", "判断：", "下一步："],
        "forbidden_reply_tokens": ["DEEPSEEK_API_KEY", "状态边界", "VELA 市场简报", "Market & World Briefing"],
        "max_reply_chars": 260,
    },
    {
        "id": "daily_info_now_policy_question_uses_deepseek_chain",
        "message": "现在这个政策怎么样",
        "expected_intent": "daily_info",
        "required_reply_tokens": ["DeepSeek API", "判断：", "下一步："],
        "forbidden_reply_tokens": ["DEEPSEEK_API_KEY", "状态边界", "VELA 市场简报", "Market & World Briefing"],
        "max_reply_chars": 260,
    },
    {
        "id": "daily_info_now_search_openai_uses_deepseek_chain",
        "message": "现在帮我搜一下OpenAI",
        "expected_intent": "daily_info",
        "required_reply_tokens": ["DeepSeek API", "判断：", "下一步："],
        "forbidden_reply_tokens": ["DEEPSEEK_API_KEY", "状态边界", "VELA 市场简报", "Market & World Briefing"],
        "max_reply_chars": 260,
    },
    {
        "id": "daily_info_now_company_notice_uses_deepseek_chain",
        "message": "现在小米汽车有什么公告",
        "expected_intent": "daily_info",
        "required_reply_tokens": ["DeepSeek API", "判断：", "下一步："],
        "forbidden_reply_tokens": ["DEEPSEEK_API_KEY", "状态边界", "VELA 市场简报", "Market & World Briefing"],
        "max_reply_chars": 260,
    },
    {
        "id": "daily_info_now_app_update_uses_deepseek_chain",
        "message": "现在ChatGPT有什么更新",
        "expected_intent": "daily_info",
        "required_reply_tokens": ["DeepSeek API", "判断：", "下一步："],
        "forbidden_reply_tokens": ["DEEPSEEK_API_KEY", "状态边界", "VELA 市场简报", "Market & World Briefing"],
        "max_reply_chars": 260,
    },
    {
        "id": "world_info_now_event_not_market",
        "message": "现在日本地震新闻",
        "expected_intent": "world_brief",
        "required_reply_tokens": ["DeepSeek API", "判断：", "下一步："],
        "forbidden_reply_tokens": ["DEEPSEEK_API_KEY", "A股快照", "VELA 市场简报", "状态边界", "Market & World Briefing"],
        "max_reply_chars": 260,
    },
    {
        "id": "weather_jinjiang",
        "message": "明天晋江会不会下雨，能不能出门",
        "expected_intent": "weather_query",
        "required_reply_tokens": ["实时源：未接入", "天气"],
    },
    {
        "id": "weather_new_york_cold",
        "message": "今天纽约冷吗，出门要不要加外套",
        "expected_intent": "weather_query",
        "required_reply_tokens": ["实时源：未接入", "天气"],
    },
    {
        "id": "weather_schedule_boundary",
        "message": "明天晋江要见客户，天气不准也给我出门风险",
        "expected_intent": "weather_query",
        "required_reply_tokens": ["实时源：未接入", "天气"],
    },
    {
        "id": "weather_trip_customer_plan",
        "message": "明天晋江出差，上午见客户，天气会不会影响行程？",
        "expected_intent": "weather_query",
        "required_reply_tokens": ["实时源：未接入", "天气"],
    },
    {
        "id": "weather_now_new_york_uses_deepseek_chain",
        "message": "现在纽约冷吗",
        "expected_intent": "weather_query",
        "required_reply_tokens": ["DeepSeek API", "实时源：未接入", "判断：", "下一步："],
        "forbidden_reply_tokens": ["DEEPSEEK_API_KEY", "状态边界", "VELA 市场简报", "Market & World Briefing"],
        "max_reply_chars": 360,
    },
    {
        "id": "market_add_position",
        "message": "我不想看新闻列表，A股今天先等还是冲",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["实时源", "判断：", "仓位"],
        "forbidden_reply_tokens": ["以下基于最近缓存", "VELA 市场简报", "状态边界：", "关键风险\n1."],
        "max_reply_chars": 620,
    },
    {
        "id": "market_current_a_share_realtime_compact",
        "message": "今天的A股市场如何",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["实时源", "判断：", "下一步："],
        "forbidden_reply_tokens": ["以下基于最近缓存", "VELA 市场简报", "状态边界：", "关键风险\n1.", "Market & World Briefing"],
        "max_reply_chars": 620,
    },
    {
        "id": "market_current_now_info_realtime_compact",
        "message": "现在的市场资讯",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["实时源：已接入", "A股快照", "判断：", "下一步："],
        "forbidden_reply_tokens": ["以下基于最近缓存", "VELA 市场简报", "状态边界：", "关键风险\n1.", "Market & World Briefing"],
        "max_reply_chars": 620,
    },
    {
        "id": "market_current_news_realtime_compact",
        "message": "当前市场新闻",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["实时源：已接入", "A股快照", "判断：", "下一步："],
        "forbidden_reply_tokens": ["不是实时直播；实时源：未接入", "60秒判断", "VELA 市场简报", "状态边界：", "关键风险\n1.", "Market & World Briefing"],
        "max_reply_chars": 620,
    },
    {
        "id": "market_current_us_info_not_a_share",
        "message": "现在美股资讯",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["实时源：暂不可用", "外盘实时源未接通", "全球", "判断：", "下一步："],
        "forbidden_reply_tokens": ["A股快照", "上证指数", "以下基于最近缓存", "VELA 市场简报", "状态边界：", "关键风险\n1.", "Market & World Briefing"],
        "max_reply_chars": 620,
    },
    {
        "id": "market_current_global_not_a_share",
        "message": "现在全球市场资讯",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["实时源：暂不可用", "外盘实时源未接通", "全球", "判断：", "下一步："],
        "forbidden_reply_tokens": ["A股快照", "上证指数", "以下基于最近缓存", "VELA 市场简报", "状态边界：", "关键风险\n1.", "Market & World Briefing"],
        "max_reply_chars": 620,
    },
    {
        "id": "market_no_raw_english",
        "message": "今天的资讯给我，但不要英文生肉新闻",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["不是实时直播", "实时源：未接入", "60秒判断", "下一观察点"],
        "forbidden_reply_tokens": ["VELA 市场简报", "关键风险\n1.", "Market & World Briefing"],
        "max_reply_chars": 900,
    },
    {
        "id": "market_expand_full_report_available",
        "message": "今天的资讯展开全部来源，我要完整报告",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["不是实时直播", "实时源：未接入", "VELA 市场简报", "关键风险"],
    },
    {
        "id": "market_policy_not_news_list",
        "message": "市场今天如果不是实时，就别装直播，给我仓位风险判断",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["实时源", "判断：", "仓位"],
    },
    {
        "id": "market_position_risk_not_news_list",
        "message": "今天A股如果不是实时就直说，我只要仓位风险，不要新闻列表",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["实时源", "判断：", "仓位"],
    },
    {
        "id": "market_impulse_brake",
        "message": "我今天有点上头，想直接满仓冲进去",
        "expected_intent": "market_brief",
        "required_reply_tokens": ["不是实时直播", "仓位", "撤退条件"],
        "forbidden_reply_tokens": ["VELA 市场简报", "关键风险\n1."],
        "max_reply_chars": 520,
    },
    {
        "id": "freshness_status",
        "message": "这是实时的吗？没有就明说",
        "expected_intent": "freshness_status",
        "required_reply_tokens": ["更新时间", "实时源：未接入"],
    },
    {
        "id": "codex_status_route_only",
        "message": "CODEX/",
        "expected_intent": "codex_task",
        "codex_summary": "Codex smoke：只验证路由与前台边界，不执行真实桥接。",
        "side_effects_allowed": False,
    },
    {
        "id": "codex_git_noise_boundary",
        "message": "Codex 状态，别把 Git 日志整段贴给我",
        "expected_intent": "codex_task",
        "codex_summary": "Codex smoke: route only, no raw Git log.",
        "side_effects_allowed": False,
    },
    {
        "id": "codex_progress_no_logs",
        "message": "CODEX/ 当前进展，别贴日志路径和 diff",
        "expected_intent": "codex_task",
        "codex_summary": "Codex smoke: current progress summary without logs or paths.",
        "side_effects_allowed": False,
    },
    {
        "id": "project_augsun_continue",
        "message": "继续 AugSun 项目，别讲愿景，给三条风险",
        "expected_intent": "project_assistant",
        "required_reply_tokens": ["风险：", "下一步："],
        "min_risk_bullets": 3,
    },
    {
        "id": "project_followup_minimum_action",
        "message": "继续 AugSun，先别开大工程，给最小推进动作",
        "expected_intent": "project_assistant",
        "required_reply_tokens": ["最小闭环", "新模块", "触发", "反馈"],
        "forbidden_reply_tokens": ["把 Codex 输出当产品判断", "需要代码执行时再交给 /CODEX"],
        "max_reply_chars": 620,
    },
    {
        "id": "project_minimum_loop",
        "message": "继续 AugSun，但不要开新模块，先查最小闭环",
        "expected_intent": "project_assistant",
        "required_reply_tokens": ["最小闭环", "新模块", "触发", "反馈"],
        "forbidden_reply_tokens": ["把 Codex 输出当产品判断", "需要代码执行时再交给 /CODEX"],
        "max_reply_chars": 620,
    },
    {
        "id": "deep_autopsy_vela",
        "message": "地狱验尸一下 VELA 为什么不智能",
        "expected_intent": "deep_analysis",
        "required_reply_tokens": ["根因", "修正路径", "误判点", "上下文断点"],
        "forbidden_reply_tokens": [
            "经验沉淀判断",
            "候选经验",
            "长期记忆",
            "长期记忆是空的",
            "写进短期笔记",
            "如果你愿意",
            "你可以再试",
            "事实包",
            "router",
            "context",
            "reply engine",
            "fallback",
            "last_response",
            "adapter",
        ],
        "max_reply_chars": 520,
    },
    {
        "id": "deep_root_cause_not_mysticism",
        "message": "根因验尸：为什么 VELA 听不懂我真正意思",
        "expected_intent": "deep_analysis",
        "required_reply_tokens": ["根因", "修正路径", "误判点", "上下文断点"],
        "forbidden_reply_tokens": [
            "经验沉淀判断",
            "候选经验",
            "长期记忆",
            "长期记忆是空的",
            "写进短期笔记",
            "如果你愿意",
            "你可以再试",
            "事实包",
            "router",
            "context",
            "reply engine",
            "fallback",
            "last_response",
            "adapter",
        ],
        "max_reply_chars": 520,
    },
    {
        "id": "identity_memory_boundary",
        "message": "VELA 你到底是 DeepSeek 还是 Codex？记忆放哪",
        "expected_intent": "memory_related",
    },
    {
        "id": "memory_market_preference_candidate",
        "message": "记住：以后市场分析默认先看A股、美股、韩国",
        "expected_intent": "memory_related",
        "required_reply_tokens": ["待确认偏好"],
        "forbidden_reply_tokens": ["候选记忆", "候选类型", "长期记忆", "刻碑", "schema"],
        "max_reply_chars": 150,
    },
    {
        "id": "sensitive_memory_guard",
        "message": "记住：我的密码是 测试占位，之后别忘",
        "expected_intent": "memory_related",
        "required_reply_tokens": ["敏感", "不写"],
    },
    {
        "id": "style_feedback_no_customer_voice",
        "message": "别客服话术，像个真伙伴一样说",
        "expected_intent": "style_feedback",
        "required_reply_tokens": ["说人话", "先听懂", "真实意思", "结论", "重切"],
        "forbidden_reply_tokens": ["候选", "候选记录", "长期记忆", "已收进", "已校准", "不永久写死", "下一轮我", "你可以再试"],
        "max_reply_chars": 120,
    },
    {
        "id": "style_feedback_say_human",
        "message": "你刚刚还是像客服，下一句别解释身份，直接说人话",
        "expected_intent": "style_feedback",
        "required_reply_tokens": ["说人话", "先听懂", "真实意思", "结论", "重切"],
        "forbidden_reply_tokens": ["候选", "候选记录", "长期记忆", "已收进", "已校准", "不永久写死", "下一轮我", "你可以再试"],
        "max_reply_chars": 120,
    },
]


ENTRYPOINT_ONLY_CASES = [
    {
        "id": "market_refresh_entry",
        "message": "刷新最新市场资讯",
        "expected_intent": "market_refresh",
        "required_reply_tokens": ["实时源：未接入", "前台先返回状态"],
        "side_effects_allowed": False,
    },
]

ENTRYPOINT_SEQUENCE_CASES = [
    {
        "id": "entrypoint_repeated_hello_no_silent_drop",
        "message": "你好",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["在", "听着", "醒着"],
        "forbidden_reply_tokens": ["市场", "Codex", "debug", "schema", "DEEPSEEK_API_KEY"],
        "max_reply_chars": 60,
    },
]


TWO_TURN_CASES = [
    {
        "id": "feedback_smarter_then_hello",
        "feedback": "我需要你更智能",
        "followup": "你好",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["我在", "在。", "听着", "慢慢说", "递过来"],
        "forbidden_reply_tokens": ["少菜单", "直接给判断", "不解释身份", "废话收短", "机械味", "不像提示牌", "已校准"],
    },
    {
        "id": "feedback_misread_then_hello",
        "feedback": "你没懂我",
        "followup": "你好",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["我在", "在。", "听着", "慢慢说", "递过来"],
        "forbidden_reply_tokens": ["少菜单", "直接给判断", "不解释身份", "废话收短", "机械味", "不像提示牌", "已校准"],
    },
    {
        "id": "feedback_push_then_continue",
        "feedback": "继续推进，不要拖",
        "followup": "继续",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["继续", "上一轮", "阻塞", "一个动作", "接着来"],
        "forbidden_reply_tokens": ["少菜单", "直接给判断", "不解释身份", "废话收短", "机械味", "不像提示牌", "不摆路牌", "少解释"],
    },
    {
        "id": "feedback_too_long_then_continue",
        "feedback": "太长了，别写论文，直接给我下一步",
        "followup": "继续",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["继续", "上一轮", "阻塞", "一个动作", "接着来"],
        "forbidden_reply_tokens": ["少菜单", "直接给判断", "不解释身份", "废话收短", "机械味", "不像提示牌", "不摆路牌", "少解释"],
    },
    {
        "id": "feedback_too_cold_then_hello",
        "feedback": "你刚才太冷了，像把我当任务单",
        "followup": "你好",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["我在", "听着", "慢慢说", "先不推你"],
        "forbidden_reply_tokens": ["目标", "卡点", "切开", "开刀", "任务单", "少菜单", "不解释身份", "废话收短", "机械味", "已校准"],
        "max_reply_chars": 80,
    },
    {
        "id": "feedback_customer_voice_then_continue",
        "feedback": "你刚刚还是像客服，下一句别解释身份，直接说人话",
        "followup": "继续",
        "expected_intent": "normal_chat",
        "required_reply_tokens": ["继续", "上一轮", "阻塞", "一个动作", "接着来"],
        "forbidden_reply_tokens": ["少菜单", "直接给判断", "不解释身份", "废话收短", "机械味", "不像提示牌", "不摆路牌", "少解释"],
    },
]


MEMORY_CONFIRMATION_CASES = [
    {
        "id": "memory_confirm_market_preference",
        "setup": "记住：以后市场分析默认先看A股、美股、韩国",
        "confirmation": "确认，把这条偏好固定下来",
        "expected_intent": "memory_related",
        "required_reply_tokens": ["固定", "A股"],
        "forbidden_reply_tokens": ["候选记忆", "候选类型", "schema", "jsonl"],
        "max_reply_chars": 180,
    },
]


def supporting_context_for(intent: str, message: str) -> str:
    if intent == "weather_query":
        return router.render_weather_reply(message)
    if intent == "market_brief":
        return router.render_cached_market_reply(message)
    if intent == "freshness_status":
        return router.render_freshness_reply(message)
    return ""


def latest_iteration_signal(log_dir: Path) -> dict[str, Any]:
    paths = sorted(log_dir.glob("human-iteration-*.jsonl"))
    if not paths:
        return {}
    rows = [line for line in paths[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return {}
    try:
        return json.loads(rows[-1])
    except json.JSONDecodeError:
        return {}


def latest_quality_log(log_dir: Path) -> dict[str, Any]:
    paths = sorted(log_dir.glob("reply-quality-*.jsonl"))
    if not paths:
        return {}
    rows = [line for line in paths[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return {}
    try:
        return json.loads(rows[-1])
    except json.JSONDecodeError:
        return {}


def find_leaks(text: str) -> list[str]:
    all_tokens = (*LEAK_TOKENS, *SOURCE_NAME_LEAK_TOKENS)
    raw_text = str(text or "")
    lower_text = raw_text.lower()
    leaks = [token for token in all_tokens if token.lower() in lower_text]
    if any(token in raw_text for token in MOJIBAKE_TOKENS):
        leaks.append("mojibake")
    if WINDOWS_PATH_RE.search(raw_text):
        leaks.append("windows_path")
    return leaks


def preview(text: str, limit: int = 260) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def runtime_check(ok: bool, detail: str = "") -> dict[str, Any]:
    return {"ok": bool(ok), "detail": detail}


def latest_session_reply_detail(latest_reply: dict[str, Any], *, max_session_age_hours: int) -> str:
    content = str(latest_reply.get("content") or "")
    leaks = list(latest_reply.get("leaks") or [])
    age = latest_reply.get("age_hours")
    if not content:
        return "no VELA assistant reply found; send a fresh WeChat prompt to verify live foreground"
    if leaks:
        return "latest VELA assistant reply has foreground leak markers; do not treat live check as clean"
    if not isinstance(age, (int, float)):
        return "latest VELA assistant reply timestamp is unreadable; send a fresh WeChat prompt to verify live foreground"
    if age > max_session_age_hours:
        return (
            f"latest VELA assistant reply is stale ({age:.1f}h > {max_session_age_hours}h); "
            "send a fresh WeChat prompt to verify live foreground"
        )
    return "recent and clean"


def runtime_next_action(failed: list[str]) -> dict[str, Any]:
    if "inbound_to_reply" in failed or "weixin_command_dispatch" in failed:
        return {
            "kind": "inspect_weixin_reply_dispatch",
            "checks": [
                "weixin_command_dispatch",
                "inbound_to_reply",
                "weixin_dispatch_trace",
                "latest_session_reply",
                "cc_connect_process",
            ],
            "verify_command": "python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json",
            "wait_command": "python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json --wait-live-seconds 90",
        }
    if "weixin_inbound_seen" in failed or "latest_session_reply" in failed:
        return {
            "kind": "send_weixin_prompt",
            "prompts": [
                "你好 VELA",
                "现在DeepSeek有什么新消息",
                "现在小米汽车有什么公告",
                "现在ChatGPT有什么更新",
                "现在帮我查这个政策",
                "今天的A股市场如何",
                "这是实时的吗？",
                "CODEX/",
            ],
            "verify_command": "python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json",
            "wait_command": "python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json --wait-live-seconds 90",
        }
    if failed:
        return {
            "kind": "inspect_failed_checks",
            "checks": failed,
            "verify_command": "python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json",
            "wait_command": "",
        }
    return {"kind": "none", "prompts": [], "verify_command": "", "wait_command": ""}


def deepseek_runtime_status(env: dict[str, str] | None = None) -> dict[str, Any]:
    status = reply_engine.reply_engine_status(env or os.environ)
    adapter = str(status.get("adapter") or "fallback")
    model = str(status.get("model") or "").strip()
    config_source = str(status.get("config_source") or "")
    if adapter == "deepseek_chat":
        source_label = "canonical_env" if config_source == "DEEPSEEK_API_KEY" else "runtime_env"
        detail = f"adapter=deepseek_chat; source={source_label}; model={model or 'unknown'}"
    elif adapter == "fallback":
        detail = "adapter=fallback; DeepSeek key not configured; foreground must not claim DeepSeek is live"
    else:
        detail = f"adapter={adapter}; source={config_source or 'runtime'}"
        if model:
            detail += f"; model={model}"
    return runtime_check(True, detail)


def detect_cc_connect_process() -> bool:
    return detect_cc_connect_process_count() > 0


def detect_cc_connect_process_count() -> int:
    if os.name == "nt":
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process cc-connect,cc-connect-patched -ErrorAction SilentlyContinue | Measure-Object).Count",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=5,
            check=False,
        )
        try:
            return max(0, int((completed.stdout or "0").strip() or "0"))
        except ValueError:
            return 0
    completed = subprocess.run(
        ["pgrep", "-f", "cc-connect"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=5,
        check=False,
    )
    if completed.returncode != 0:
        return 0
    return len([line for line in (completed.stdout or "").splitlines() if line.strip()])


def detect_cc_connect_process_started_at() -> datetime | None:
    if os.name != "nt":
        return None
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "$p=Get-Process cc-connect,cc-connect-patched -ErrorAction SilentlyContinue | "
            "Sort-Object StartTime -Descending | Select-Object -First 1; "
            "if ($p) { $p.StartTime.ToUniversalTime().ToString('o') }",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=5,
        check=False,
    )
    return parse_timestamp((completed.stdout or "").strip())


def cc_connect_process_check(
    *,
    process_running: bool | None = None,
    process_count: int | None = None,
) -> dict[str, Any]:
    if process_count is None:
        if process_running is not None:
            process_count = 1 if process_running else 0
        else:
            process_count = detect_cc_connect_process_count()
    process_count = max(0, int(process_count))
    if process_count == 0:
        return runtime_check(False, "not running")
    if process_count > 1:
        return runtime_check(False, f"multiple cc-connect processes detected; count={process_count}; keep one service instance")
    return runtime_check(True, "running; count=1")


def parse_timestamp(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def split_config_command(command: str) -> list[str]:
    try:
        parts = shlex.split(str(command or ""), posix=os.name != "nt")
    except ValueError:
        return []
    return [part.strip("\"'") for part in parts if part.strip("\"'")]


def router_command_dry_run(intent_router: dict[str, Any]) -> dict[str, Any]:
    command = str(intent_router.get("command") or "").strip()
    args = split_config_command(command)
    if not args:
        return runtime_check(False, "router command missing or unparsable")
    if "--intent" not in args:
        args.append("--intent")
    work_dir = Path(str(intent_router.get("work_dir") or ROOT))
    timeout_raw = intent_router.get("timeout_seconds")
    try:
        timeout = int(timeout_raw)
    except (TypeError, ValueError):
        timeout = 10
    timeout = max(3, min(timeout, 10))
    try:
        completed = subprocess.run(
            args,
            input="你好 VELA",
            cwd=str(work_dir) if work_dir.exists() else str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return runtime_check(False, f"router command failed to start: {type(exc).__name__}")
    output = " ".join((completed.stdout or completed.stderr or "").split())[:240]
    ok = completed.returncode == 0 and "normal_chat" in output and not find_leaks(output)
    return runtime_check(ok, output or f"exit={completed.returncode}")


def latest_session_reply(sessions_dir: Path) -> dict[str, Any]:
    candidates: list[tuple[datetime, float, Path, str]] = []
    if not sessions_dir.exists():
        return {"content": "", "timestamp": "", "path": "", "age_hours": None, "leaks": []}
    for path in sessions_dir.glob("VELA*.json"):
        if ".bak-" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for session in (data.get("sessions") or {}).values():
            for item in session.get("history", []):
                if item.get("role") != "assistant" or not item.get("content"):
                    continue
                parsed = parse_timestamp(str(item.get("timestamp") or item.get("created_at") or ""))
                if parsed is None:
                    parsed = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                candidates.append((parsed, path.stat().st_mtime, path, str(item["content"])))
    if not candidates:
        return {"content": "", "timestamp": "", "path": "", "age_hours": None, "leaks": []}
    timestamp, _mtime, path, content = sorted(candidates, key=lambda item: (item[0], item[1]))[-1]
    age_hours = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600)
    return {
        "content": content,
        "timestamp": timestamp.isoformat(),
        "path": str(path),
        "age_hours": round(age_hours, 2),
        "leaks": find_leaks(content),
    }


def latest_inbound_message(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"timestamp": "", "found": False}
    latest: datetime | None = None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"timestamp": "", "found": False}
    for line in lines:
        if 'msg="message received"' not in line:
            continue
        match = CC_LOG_TIME_RE.search(line)
        parsed = parse_timestamp(match.group(1) if match else "")
        if parsed and (latest is None or parsed > latest):
            latest = parsed
    if latest is None:
        return {"timestamp": "", "found": False}
    return {"timestamp": latest.isoformat(), "found": True}


def weixin_command_dispatch(log_path: Path, inbound_time: datetime | None) -> dict[str, Any]:
    if inbound_time is None:
        return runtime_check(True, "no inbound to trace")
    if not log_path.exists():
        return runtime_check(False, "cc-connect log missing; cannot prove vela-router dispatch")
    latest: datetime | None = None
    latest_route = "vela-router"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return runtime_check(False, "cc-connect log unreadable; cannot prove vela-router dispatch")
    for line in lines:
        if 'msg="audit: command_executed"' not in line:
            continue
        if "project=VELA" not in line:
            continue
        routed_by_command = "command=vela-router" in line
        routed_by_inbound_router = "type=inbound_router" in line or "command=inbound-router" in line
        if not (routed_by_command or routed_by_inbound_router):
            continue
        match = CC_LOG_TIME_RE.search(line)
        parsed = parse_timestamp(match.group(1) if match else "")
        if parsed and parsed >= inbound_time and (latest is None or parsed > latest):
            latest = parsed
            latest_route = "inbound-router" if routed_by_inbound_router else "vela-router"
    if latest is None:
        return runtime_check(False, "no logged vela-router dispatch after latest Weixin inbound")
    return runtime_check(True, f"{latest_route} dispatched at {latest.isoformat()}")


def latest_path_mtime(paths: Iterable[Path]) -> datetime | None:
    latest: datetime | None = None
    for path in paths:
        try:
            if not path.exists() or not path.is_file():
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if latest is None or mtime > latest:
            latest = mtime
    return latest


def weixin_state_dir(vela_project: dict[str, Any]) -> Path | None:
    platforms = [item for item in vela_project.get("platforms", []) if isinstance(item, dict)]
    weixin = next((item for item in platforms if item.get("type") == "weixin"), {})
    options = weixin.get("options") if isinstance(weixin.get("options"), dict) else {}
    state_dir_raw = str(options.get("state_dir") or "").strip()
    return Path(state_dir_raw) if state_dir_raw else None


def _after_inbound_label(mtime: datetime | None, inbound_time: datetime, *, unknown_when_missing: bool = False) -> str:
    if mtime is None:
        return "unknown" if unknown_when_missing else "missing"
    return "yes" if mtime >= inbound_time else "no"


def weixin_dispatch_trace(
    *,
    cc_home: Path,
    vela_project: dict[str, Any],
    inbound_time: datetime | None,
    reply_time: datetime | None,
) -> dict[str, Any]:
    if inbound_time is None:
        return runtime_check(True, "no inbound to trace")
    if reply_time and reply_time >= inbound_time:
        return runtime_check(True, "reply newer/equal than inbound")

    session_mtime = latest_path_mtime(
        path for path in (cc_home / "sessions").glob("VELA*.json") if ".bak-" not in path.name
    )
    state_dir = weixin_state_dir(vela_project)
    context_mtime = latest_path_mtime([state_dir / "context_tokens.json"]) if state_dir else None
    session_label = _after_inbound_label(session_mtime, inbound_time)
    context_label = _after_inbound_label(context_mtime, inbound_time, unknown_when_missing=state_dir is None)
    any_runtime_state_moved = session_label == "yes" or context_label == "yes"
    detail = (
        "inbound observed; "
        f"session_file_after_inbound={session_label}; "
        f"context_tokens_after_inbound={context_label}"
    )
    return runtime_check(any_runtime_state_moved, detail)


def weixin_poll_state(vela_project: dict[str, Any], *, max_age_minutes: int = 15) -> dict[str, Any]:
    state_dir = weixin_state_dir(vela_project)
    if not state_dir:
        return runtime_check(False, "weixin state_dir missing")
    poll_file = state_dir / "get_updates.buf"
    if not poll_file.exists():
        return runtime_check(False, "weixin poll buffer missing")
    try:
        mtime = datetime.fromtimestamp(poll_file.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return runtime_check(False, "weixin poll buffer unreadable")
    age_minutes = max(0.0, (datetime.now(timezone.utc) - mtime).total_seconds() / 60)
    fresh = age_minutes <= max_age_minutes
    detail = f"poll buffer {'fresh' if fresh else 'stale'}: {age_minutes:.1f}m"
    return runtime_check(fresh, detail)


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines[-50:]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def learning_loop_state(log_dir: Path | None = None) -> dict[str, Any]:
    log_dir = log_dir or (ROOT / "VELA" / "learning-loop")
    if not log_dir.exists():
        return runtime_check(False, "learning loop missing")
    if not log_dir.is_dir():
        return runtime_check(False, "learning loop path is not a directory")
    try:
        with tempfile.NamedTemporaryFile(prefix=".audit-", suffix=".tmp", dir=log_dir, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(b"ok")
        temp_path.unlink(missing_ok=True)
    except OSError:
        return runtime_check(False, "learning loop not writable")

    categories: set[str] = set()
    if any(_jsonl_rows(path) for path in log_dir.glob("session-notes-*.jsonl")):
        categories.add("Session Notes")
    if any(_jsonl_rows(path) for path in log_dir.glob("interaction-*.jsonl")):
        categories.add("Interaction Log")
    if any(_jsonl_rows(path) for path in log_dir.glob("human-iteration-*.jsonl")):
        categories.add("Next-turn Feedback Signal")

    for path in log_dir.glob("memory-candidates-*.jsonl"):
        for row in _jsonl_rows(path):
            level = str(row.get("level") or "")
            classification = str(row.get("classification") or "")
            if level == "Preference Candidate":
                categories.add("Preference Candidate")
            if classification in {"style_feedback", "relationship_repair", "behavior_preference"}:
                categories.add("Style Feedback Candidate")
            if level == "Strategic Memory Candidate" or classification == "strategic_goal":
                categories.add("Strategic Memory Candidate")
    if any(_jsonl_rows(path) for path in log_dir.glob("strategic-memory-*.jsonl")):
        categories.add("Strategic Memory")

    expected = {
        "Session Notes",
        "Interaction Log",
        "Preference Candidate",
        "Style Feedback Candidate",
        "Strategic Memory",
    }
    missing = sorted(expected - categories)
    detail = "categories: " + ", ".join(sorted(categories)) if categories else "categories: none"
    if missing:
        detail += "; missing: " + ", ".join(missing)
    else:
        detail += "; writable"
    return runtime_check(not missing, detail)


def run_runtime_audit(
    *,
    cc_home: Path | None = None,
    process_running: bool | None = None,
    process_count: int | None = None,
    process_started_at: datetime | str | None = None,
    max_session_age_hours: int = 48,
    learning_loop_dir: Path | None = None,
) -> dict[str, Any]:
    cc_home = cc_home or DEFAULT_CC_CONNECT_HOME
    config_path = cc_home / "config.toml"
    checks: dict[str, dict[str, Any]] = {}
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            checks["config"] = runtime_check(True, "cc-connect config loaded")
        except tomllib.TOMLDecodeError as exc:
            checks["config"] = runtime_check(False, f"config parse failed: {exc}")
    else:
        checks["config"] = runtime_check(False, "cc-connect config missing")

    projects = [item for item in config.get("projects", []) if isinstance(item, dict)]
    vela_project = next((item for item in projects if item.get("name") == "VELA"), {})
    intent_router = vela_project.get("intent_router") or {}
    router_command = str(intent_router.get("command") or "")
    checks["router_config"] = runtime_check(
        bool(intent_router.get("enabled")) and "vela_router.py" in router_command and "--stdin" in router_command,
        router_command,
    )
    checks["router_command_dry_run"] = (
        router_command_dry_run(intent_router)
        if checks["router_config"]["ok"]
        else runtime_check(False, "router config is not valid enough to dry-run")
    )
    checks["deepseek_runtime"] = deepseek_runtime_status()
    checks["learning_loop_state"] = learning_loop_state(learning_loop_dir)

    commands = {item.get("name"): item for item in config.get("commands", []) if isinstance(item, dict)}
    command_names = ("vela-router", "vela-talk")
    commands_ok = all("vela_router.py" in str((commands.get(name) or {}).get("exec") or "") for name in command_names)
    checks["commands"] = runtime_check(commands_ok, ", ".join(name for name in command_names if name in commands))
    checks["weixin_poll_state"] = weixin_poll_state(vela_project)

    checks["cc_connect_process"] = cc_connect_process_check(
        process_running=process_running,
        process_count=process_count,
    )
    if isinstance(process_started_at, str):
        service_started_at = parse_timestamp(process_started_at)
    else:
        service_started_at = process_started_at
    if service_started_at is None and process_running is None and process_count is None:
        service_started_at = detect_cc_connect_process_started_at()

    latest_reply = latest_session_reply(cc_home / "sessions")
    age = latest_reply.get("age_hours")
    reply_recent = isinstance(age, (int, float)) and age <= max_session_age_hours
    reply_clean = bool(latest_reply.get("content")) and not latest_reply.get("leaks")
    latest_reply_detail = latest_session_reply_detail(
        latest_reply,
        max_session_age_hours=max_session_age_hours,
    )
    checks["latest_session_reply"] = runtime_check(
        reply_recent and reply_clean,
        latest_reply_detail,
    )

    inbound = latest_inbound_message(cc_home / "cc-connect.log")
    latest_inbound_time = parse_timestamp(str(inbound.get("timestamp") or ""))
    inbound_time = latest_inbound_time
    inbound_before_current_service = bool(
        latest_inbound_time and service_started_at and latest_inbound_time < service_started_at
    )
    if inbound_before_current_service:
        inbound_time = None
    checks["weixin_inbound_seen"] = runtime_check(
        bool(inbound_time),
        (
            f"Weixin inbound observed at {inbound_time.isoformat()}"
            if inbound_time
            else (
                "latest Weixin inbound is older than current cc-connect process start; "
                "send a fresh WeChat prompt to verify live foreground"
                if inbound_before_current_service
                else "no Weixin inbound message in cc-connect log; send a fresh WeChat prompt to verify live foreground"
            )
        ),
    )
    reply_time = parse_timestamp(str(latest_reply.get("timestamp") or ""))
    checks["weixin_command_dispatch"] = weixin_command_dispatch(cc_home / "cc-connect.log", inbound_time)
    inbound_ok = True
    inbound_detail = "no inbound message in cc-connect log"
    if inbound_time:
        inbound_ok = bool(reply_time and reply_time >= inbound_time)
        inbound_detail = (
            f"message received at {inbound_time.isoformat()} has a newer/equal session reply"
            if inbound_ok
            else f"message received at {inbound_time.isoformat()} is newer than latest VELA session reply"
        )
    checks["inbound_to_reply"] = runtime_check(inbound_ok, inbound_detail)
    checks["weixin_dispatch_trace"] = weixin_dispatch_trace(
        cc_home=cc_home,
        vela_project=vela_project,
        inbound_time=inbound_time,
        reply_time=reply_time,
    )
    dispatch_detail = str(checks["weixin_command_dispatch"].get("detail") or "")
    direct_inbound_router_path = (
        bool(inbound_time)
        and checks["weixin_command_dispatch"]["ok"]
        and checks["weixin_dispatch_trace"]["ok"]
        and "inbound-router" in dispatch_detail
    )
    if direct_inbound_router_path and not inbound_ok:
        checks["latest_session_reply"] = runtime_check(
            True,
            "inbound-router direct foreground path observed; session history is not the proof surface for this route",
        )
        checks["inbound_to_reply"] = runtime_check(
            True,
            "latest Weixin inbound has logged inbound-router dispatch; direct replies may not write VELA session history",
        )

    failed = [name for name, check in checks.items() if not check["ok"]]
    return {
        "ok": not failed,
        "cc_home": str(cc_home),
        "checks": checks,
        "failed": failed,
        "next_action": runtime_next_action(failed),
        "latest_reply": {
            "timestamp": latest_reply.get("timestamp") or "",
            "age_hours": latest_reply.get("age_hours"),
            "preview": preview(str(latest_reply.get("content") or "")),
            "leaks": latest_reply.get("leaks") or [],
        },
        "latest_inbound": {
            **inbound,
            "current_window_timestamp": inbound_time.isoformat() if inbound_time else "",
            "service_started_at": service_started_at.isoformat() if service_started_at else "",
        },
    }


def wait_for_runtime_audit(
    *,
    cc_home: Path,
    timeout_seconds: float,
    poll_seconds: float = 2.0,
    process_running: bool | None = None,
    max_session_age_hours: int = 48,
    audit_fn=run_runtime_audit,
    sleep_fn=time.sleep,
    monotonic_fn=time.monotonic,
) -> dict[str, Any]:
    timeout_seconds = max(0.0, float(timeout_seconds))
    poll_seconds = max(0.2, float(poll_seconds))
    start = monotonic_fn()
    deadline = start + timeout_seconds
    attempts = 0
    status = "timed_out"
    report: dict[str, Any] = {}
    while True:
        attempts += 1
        report = audit_fn(
            cc_home=cc_home,
            process_running=process_running,
            max_session_age_hours=max_session_age_hours,
        )
        now = monotonic_fn()
        if report.get("ok"):
            status = "satisfied"
            break
        if now >= deadline:
            break
        sleep_fn(min(poll_seconds, max(0.0, deadline - now)))
    elapsed = max(0.0, monotonic_fn() - start)
    report = dict(report)
    report["wait"] = {
        "enabled": True,
        "status": status,
        "attempts": attempts,
        "timeout_seconds": round(timeout_seconds, 2),
        "elapsed_seconds": round(elapsed, 2),
    }
    return report


def required_tokens_present(text: str, tokens: list[str] | None) -> bool:
    if not tokens:
        return True
    return any(token in text for token in tokens)


def output_constraints(text: str, case: dict[str, Any]) -> dict[str, Any]:
    reply_chars = len(str(text or ""))
    max_chars_raw = case.get("max_reply_chars")
    max_chars: int | None = None
    if max_chars_raw is not None:
        try:
            max_chars = int(max_chars_raw)
        except (TypeError, ValueError):
            max_chars = None
    forbidden = [
        str(token)
        for token in (case.get("forbidden_reply_tokens") or [])
        if str(token) and str(token) in str(text or "")
    ]
    risk_bullets = section_bullet_count(str(text or ""), "风险：", "下一步：")
    min_risk_raw = case.get("min_risk_bullets")
    min_risk_bullets: int | None = None
    if min_risk_raw is not None:
        try:
            min_risk_bullets = int(min_risk_raw)
        except (TypeError, ValueError):
            min_risk_bullets = None
    return {
        "reply_chars": reply_chars,
        "max_reply_chars": max_chars,
        "max_reply_chars_ok": max_chars is None or reply_chars <= max_chars,
        "forbidden_reply_tokens_found": forbidden,
        "risk_bullets": risk_bullets,
        "min_risk_bullets": min_risk_bullets,
        "min_risk_bullets_ok": min_risk_bullets is None or risk_bullets >= min_risk_bullets,
    }


def section_bullet_count(text: str, heading: str, next_heading: str) -> int:
    if heading not in text:
        return 0
    section = text.split(heading, 1)[1]
    if next_heading in section:
        section = section.split(next_heading, 1)[0]
    return len([line for line in section.splitlines() if line.startswith("- ")])


def route_case(message: str) -> Any:
    return router.classify_intent(message)


def case_latency_budget_ms(intent: str) -> int | None:
    if intent in {"normal_chat", "daily_info", "weather_query", "freshness_status", "memory_related", "style_feedback"}:
        return 2000
    if intent in {"market_brief", "market_refresh", "world_brief"}:
        return 8000
    return None


def attach_latency(case_result: dict[str, Any], started_at: float) -> dict[str, Any]:
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    budget_ms = case_latency_budget_ms(str(case_result.get("intent") or ""))
    latency_ok = budget_ms is None or latency_ms <= budget_ms
    case_result["latency_ms"] = max(0, latency_ms)
    case_result["latency_budget_ms"] = budget_ms
    case_result["latency_ok"] = latency_ok
    case_result["ok"] = bool(case_result.get("ok")) and latency_ok
    return case_result


def run_single_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    started_at = time.perf_counter()
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    intent = route_case(case["message"])
    supporting_context = supporting_context_for(intent.name, case["message"])
    result = run_layered_response(
        case["message"],
        intent=intent.name,
        codex_summary=case.get("codex_summary", ""),
        log_dir=case_log_dir,
        reply_adapter=FallbackReplyAdapter(),
        supporting_context=supporting_context,
    )
    leaks = find_leaks(result.text)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(result.text, case.get("required_reply_tokens"))
    constraints = output_constraints(result.text, case)
    tool_boundary_ok = True
    if intent.name not in {"market_brief", "market_refresh"} and intent.market_allowed:
        tool_boundary_ok = False
    if intent.name != "codex_task" and intent.codex_allowed:
        tool_boundary_ok = False
    return attach_latency({
        "id": case["id"],
        "kind": "single_turn",
        "message": case["message"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": bool(case.get("side_effects_allowed", True)),
        "bridge_executed": False,
        "reply_preview": preview(result.text),
        "latest_iteration_signal": latest_iteration_signal(case_log_dir),
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        **constraints,
        "ok": (
            route_ok
            and required_ok
            and tool_boundary_ok
            and constraints["max_reply_chars_ok"]
            and constraints["min_risk_bullets_ok"]
            and not constraints["forbidden_reply_tokens_found"]
            and not leaks
        ),
    }, started_at)


def run_entrypoint_single_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    started_at = time.perf_counter()
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    intent = route_case(case["message"])
    original_run = router.run_layered_response
    original_refresh = router.schedule_market_refresh
    original_codex = router.render_codex_bridge

    def run_with_case_log(message: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("log_dir", case_log_dir)
        kwargs.setdefault("reply_adapter", FallbackReplyAdapter())
        return original_run(message, *args, **kwargs)

    def fake_refresh(_text: str) -> Any:
        return router.MarketRefreshJob(started=True, in_progress=False, pid=12345, reason="smoke_stub")

    def fake_codex(_text: str = "") -> str:
        return "K，VELA · CODEX 产品判断摘要\n事实：- Codex smoke 只验证路由。\n判断：路由正确，不执行真实桥接。"

    router.run_layered_response = run_with_case_log
    router.schedule_market_refresh = fake_refresh
    router.render_codex_bridge = fake_codex
    try:
        reply = router.reply_for(case["message"])
    finally:
        router.run_layered_response = original_run
        router.schedule_market_refresh = original_refresh
        router.render_codex_bridge = original_codex

    leaks = find_leaks(reply)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(reply, case.get("required_reply_tokens"))
    constraints = output_constraints(reply, case)
    tool_boundary_ok = True
    if intent.name not in {"market_brief", "market_refresh"} and intent.market_allowed:
        tool_boundary_ok = False
    if intent.name != "codex_task" and intent.codex_allowed:
        tool_boundary_ok = False
    return attach_latency({
        "id": case["id"],
        "kind": "entrypoint_single_turn",
        "message": case["message"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": bool(case.get("side_effects_allowed", True)),
        "bridge_executed": False,
        "reply_preview": preview(reply),
        "latest_iteration_signal": latest_iteration_signal(case_log_dir),
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        **constraints,
        "ok": (
            route_ok
            and required_ok
            and tool_boundary_ok
            and constraints["max_reply_chars_ok"]
            and constraints["min_risk_bullets_ok"]
            and not constraints["forbidden_reply_tokens_found"]
            and not leaks
        ),
    }, started_at)


def run_entrypoint_sequence_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    started_at = time.perf_counter()
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    intent = route_case(case["message"])
    original_run = router.run_layered_response

    def run_with_case_log(message: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("log_dir", case_log_dir)
        kwargs.setdefault("reply_adapter", FallbackReplyAdapter())
        return original_run(message, *args, **kwargs)

    router.run_layered_response = run_with_case_log
    try:
        first = router.reply_for(case["message"])
        second = router.reply_for(case["message"])
    finally:
        router.run_layered_response = original_run

    combined = "\n".join([first, second])
    leaks = find_leaks(combined)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(first, case.get("required_reply_tokens")) and required_tokens_present(
        second,
        case.get("required_reply_tokens"),
    )
    constraints = output_constraints(second, case)
    nonempty = bool(first.strip()) and bool(second.strip())
    changed = first.strip() != second.strip()
    tool_boundary_ok = not intent.market_allowed and not intent.codex_allowed
    return attach_latency({
        "id": case["id"],
        "kind": "entrypoint_sequence",
        "message": case["message"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": False,
        "bridge_executed": False,
        "reply_preview": preview(second),
        "first_reply_preview": preview(first),
        "second_reply_preview": preview(second),
        "nonempty_replies": nonempty,
        "changed_reply": changed,
        "latest_iteration_signal": latest_iteration_signal(case_log_dir),
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        **constraints,
        "ok": (
            route_ok
            and required_ok
            and nonempty
            and changed
            and tool_boundary_ok
            and constraints["max_reply_chars_ok"]
            and not constraints["forbidden_reply_tokens_found"]
            and not leaks
        ),
    }, started_at)


def run_two_turn_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    started_at = time.perf_counter()
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    run_layered_response(
        case["feedback"],
        intent="style_feedback",
        log_dir=case_log_dir,
        reply_adapter=FallbackReplyAdapter(),
    )
    intent = route_case(case["followup"])
    result = run_layered_response(
        case["followup"],
        intent=intent.name,
        log_dir=case_log_dir,
        reply_adapter=FallbackReplyAdapter(),
    )
    signal = latest_iteration_signal(case_log_dir)
    leaks = find_leaks(result.text)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(result.text, case.get("required_reply_tokens"))
    adapted = "preference_or_feedback_adapted" in signal.get("response_quality_signals", [])
    return attach_latency({
        "id": case["id"],
        "kind": "two_turn",
        "message": case["followup"],
        "feedback": case["feedback"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": True,
        "bridge_executed": False,
        "reply_preview": preview(result.text),
        "latest_iteration_signal": signal,
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        "ok": route_ok and required_ok and adapted and not leaks,
    }, started_at)


def run_entrypoint_two_turn_case(case: dict[str, Any], base_log_dir: Path) -> dict[str, Any]:
    started_at = time.perf_counter()
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    original_run = router.run_layered_response

    def run_with_case_log(message: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("log_dir", case_log_dir)
        kwargs.setdefault("reply_adapter", FallbackReplyAdapter())
        return original_run(message, *args, **kwargs)

    router.run_layered_response = run_with_case_log
    try:
        router.reply_for(case["feedback"])
        intent = route_case(case["followup"])
        reply = router.reply_for(case["followup"])
    finally:
        router.run_layered_response = original_run

    signal = latest_iteration_signal(case_log_dir)
    leaks = find_leaks(reply)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(reply, case.get("required_reply_tokens"))
    adapted = "preference_or_feedback_adapted" in signal.get("response_quality_signals", [])
    return attach_latency({
        "id": case["id"],
        "kind": "entrypoint_two_turn",
        "message": case["followup"],
        "feedback": case["feedback"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": True,
        "bridge_executed": False,
        "reply_preview": preview(reply),
        "latest_iteration_signal": signal,
        "latest_quality_log": latest_quality_log(case_log_dir),
        "leaks": leaks,
        "ok": route_ok and required_ok and adapted and not leaks,
    }, started_at)


def confirmed_preference_rows(log_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("confirmed-preferences-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def run_memory_confirmation_case(
    case: dict[str, Any],
    base_log_dir: Path,
    *,
    use_entrypoint: bool = False,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    case_log_dir = base_log_dir / case["id"]
    case_log_dir.mkdir(parents=True, exist_ok=True)
    confirmation = case["confirmation"]

    if use_entrypoint:
        original_run = router.run_layered_response

        def run_with_case_log(message: str, *args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("log_dir", case_log_dir)
            kwargs.setdefault("reply_adapter", FallbackReplyAdapter())
            return original_run(message, *args, **kwargs)

        router.run_layered_response = run_with_case_log
        try:
            router.reply_for(case["setup"])
            intent = route_case(confirmation)
            reply = router.reply_for(confirmation)
        finally:
            router.run_layered_response = original_run
    else:
        run_layered_response(
            case["setup"],
            intent="memory_related",
            log_dir=case_log_dir,
            reply_adapter=FallbackReplyAdapter(),
        )
        intent = route_case(confirmation)
        result = run_layered_response(
            confirmation,
            intent=intent.name,
            log_dir=case_log_dir,
            reply_adapter=FallbackReplyAdapter(),
        )
        reply = result.text

    rows = confirmed_preference_rows(case_log_dir)
    context = build_reply_context("今天市场怎么看", intent="market_brief", log_dir=case_log_dir)
    preference_context = " ".join(context.user_preferences)
    confirmed_written = any(
        row.get("confirmed") and all(token in str(row.get("summary") or "") for token in ("A股", "美股", "韩国"))
        for row in rows
    )
    context_uses_confirmed = all(token in preference_context for token in ("A股", "美股", "韩国")) and "候选偏好" not in preference_context
    constraints = output_constraints(reply, case)
    leaks = find_leaks(reply)
    route_ok = intent.name == case["expected_intent"]
    required_ok = required_tokens_present(reply, case.get("required_reply_tokens"))
    return attach_latency({
        "id": case["id"],
        "kind": "entrypoint_memory_confirmation" if use_entrypoint else "memory_confirmation",
        "message": confirmation,
        "setup": case["setup"],
        "intent": intent.name,
        "expected_intent": case["expected_intent"],
        "market_allowed": intent.market_allowed,
        "codex_allowed": intent.codex_allowed,
        "side_effects_allowed": True,
        "bridge_executed": False,
        "reply_preview": preview(reply),
        "latest_iteration_signal": latest_iteration_signal(case_log_dir),
        "latest_quality_log": latest_quality_log(case_log_dir),
        "confirmed_preference_written": confirmed_written,
        "confirmed_preference_in_context": context_uses_confirmed,
        "leaks": leaks,
        **constraints,
        "ok": (
            route_ok
            and required_ok
            and confirmed_written
            and context_uses_confirmed
            and constraints["max_reply_chars_ok"]
            and not constraints["forbidden_reply_tokens_found"]
            and not leaks
        ),
    }, started_at)


def run_smoke_suite(
    log_dir: Path | None = None,
    *,
    use_entrypoint: bool = False,
    fake_deepseek_env: bool = False,
) -> dict[str, Any]:
    created_tmp: tempfile.TemporaryDirectory[str] | None = None
    if log_dir is None:
        created_tmp = tempfile.TemporaryDirectory()
        base_log_dir = Path(created_tmp.name)
    else:
        base_log_dir = Path(log_dir)
        base_log_dir.mkdir(parents=True, exist_ok=True)
    old_deepseek = os.environ.get("DEEPSEEK_API_KEY")
    if fake_deepseek_env:
        os.environ["DEEPSEEK_API_KEY"] = "smoke-deepseek-key"
    try:
        single_cases = [*SINGLE_TURN_CASES]
        if use_entrypoint:
            single_cases.extend(ENTRYPOINT_ONLY_CASES)
            cases = [run_entrypoint_single_case(case, base_log_dir) for case in single_cases]
            cases.extend(run_entrypoint_sequence_case(case, base_log_dir) for case in ENTRYPOINT_SEQUENCE_CASES)
            cases.extend(run_entrypoint_two_turn_case(case, base_log_dir) for case in TWO_TURN_CASES)
            cases.extend(run_memory_confirmation_case(case, base_log_dir, use_entrypoint=True) for case in MEMORY_CONFIRMATION_CASES)
        else:
            cases = [run_single_case(case, base_log_dir) for case in single_cases]
            cases.extend(run_two_turn_case(case, base_log_dir) for case in TWO_TURN_CASES)
            cases.extend(run_memory_confirmation_case(case, base_log_dir) for case in MEMORY_CONFIRMATION_CASES)
        failed = [case["id"] for case in cases if not case["ok"]]
        return {
            "ok": not failed,
            "entrypoint": use_entrypoint,
            "fake_deepseek_env": fake_deepseek_env,
            "case_count": len(cases),
            "failed": failed,
            "log_dir": str(base_log_dir),
            "cases": cases,
        }
    finally:
        if fake_deepseek_env:
            if old_deepseek is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old_deepseek
        if created_tmp is not None:
            created_tmp.cleanup()


def render_text_report(report: dict[str, Any]) -> str:
    lines = [
        f"VELA acceptance smoke: {'OK' if report['ok'] else 'FAIL'}",
        f"cases: {report['case_count']}",
    ]
    if report["failed"]:
        lines.append("failed: " + ", ".join(report["failed"]))
    for case in report["cases"]:
        mark = "OK" if case["ok"] else "FAIL"
        lines.append(f"- {mark} {case['id']} [{case['intent']}] {case['reply_preview']}")
    return "\n".join(lines)


def render_runtime_report(report: dict[str, Any]) -> str:
    lines = [
        f"VELA cc-connect runtime audit: {'OK' if report['ok'] else 'FAIL'}",
        f"cc_home: {report['cc_home']}",
    ]
    if report["failed"]:
        lines.append("failed: " + ", ".join(report["failed"]))
    for name, check in report["checks"].items():
        mark = "OK" if check["ok"] else "FAIL"
        detail = str(check.get("detail") or "")
        lines.append(f"- {mark} {name}: {detail}")
    latest = report.get("latest_reply") or {}
    if latest.get("preview"):
        lines.append(f"latest_reply: {latest['preview']}")
    wait = report.get("wait") or {}
    if wait.get("enabled"):
        lines.append(
            f"wait: {wait.get('status')} after {wait.get('attempts')} attempts "
            f"({wait.get('elapsed_seconds')}s/{wait.get('timeout_seconds')}s)"
        )
    next_action = report.get("next_action") or {}
    if next_action.get("kind") and next_action.get("kind") != "none":
        lines.append(f"next_action: {next_action['kind']}")
        prompts = next_action.get("prompts") or []
        if prompts:
            lines.append("prompts: " + " / ".join(str(item) for item in prompts))
        if next_action.get("verify_command"):
            lines.append(f"verify: {next_action['verify_command']}")
        if next_action.get("wait_command"):
            lines.append(f"wait_verify: {next_action['wait_command']}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VELA local foreground acceptance smoke scenarios.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--entrypoint", action="store_true", help="Run through router.reply_for with safe stubs.")
    parser.add_argument("--fake-deepseek-env", action="store_true", help="Set a temporary DeepSeek key sentinel during smoke.")
    parser.add_argument("--log-dir", type=Path, default=None, help="Use this learning-loop directory instead of a temp dir.")
    parser.add_argument("--runtime-audit", action="store_true", help="Audit local cc-connect runtime config/process/session state.")
    parser.add_argument("--cc-home", type=Path, default=DEFAULT_CC_CONNECT_HOME, help="cc-connect home directory for runtime audit.")
    parser.add_argument("--max-session-age-hours", type=int, default=48, help="Maximum acceptable age for latest VELA session reply.")
    parser.add_argument("--wait-live-seconds", type=float, default=0.0, help="When auditing runtime, wait this long for a fresh Weixin inbound and reply.")
    parser.add_argument("--wait-poll-seconds", type=float, default=2.0, help="Polling interval for --wait-live-seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.runtime_audit:
        if args.wait_live_seconds > 0:
            report = wait_for_runtime_audit(
                cc_home=args.cc_home,
                timeout_seconds=args.wait_live_seconds,
                poll_seconds=args.wait_poll_seconds,
                max_session_age_hours=args.max_session_age_hours,
            )
        else:
            report = run_runtime_audit(
                cc_home=args.cc_home,
                max_session_age_hours=args.max_session_age_hours,
            )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(render_runtime_report(report))
        return 0 if report["ok"] else 1
    report = run_smoke_suite(
        log_dir=args.log_dir,
        use_entrypoint=args.entrypoint,
        fake_deepseek_env=args.fake_deepseek_env,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
