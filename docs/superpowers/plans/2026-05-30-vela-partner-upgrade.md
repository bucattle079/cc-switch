# VELA Partner Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade VELA from a reply tool into a WeChat-facing AI partner loop with clear intent routing, DeepSeek-first dialogue, learning feedback, Codex boundaries, and clean foreground output.

**Architecture:** Keep the existing Python toolchain and add explicit partner-loop seams instead of replacing the whole system. The router owns intent lanes; product layers own context, tool selection, learning evaluation, persona rendering, and guardrails; the reply engine owns model adapters with DeepSeek as the default dialogue adapter when configured.

**Tech Stack:** Python standard library, unittest, existing VELA JSONL learning logs, existing cc-connect/Codex bridge scripts.

---

### Task 1: Foreground Contract

**Files:**
- Modify: `tests/test_vela_partner_upgrade.py`
- Modify: `tests/test_vela_intent_router.py`
- Modify: `tools/vela_market_briefing.py`
- Modify: `tools/vela_router.py`
- Modify: `tools/vela_product_layers.py`

- [x] Add tests proving freshness and refresh replies use Chinese user-facing labels and never expose `data_status`, `source_type`, `refresh_available`, `cache_path`, or raw schema keys.
- [x] Update the stale router tests that previously required schema keys in foreground replies.
- [x] Change freshness and refresh renderers to show cache/refresh state in VELA-facing language.
- [x] Extend the WeChat guardrail to remove schema/debug/runtime keys even if an adapter leaks them.

### Task 2: DeepSeek-First Dialogue

**Files:**
- Modify: `tests/test_vela_partner_upgrade.py`
- Modify: `tests/test_vela_reply_engine.py`
- Modify: `tools/vela_reply_engine.py`
- Modify: `VELA/runtime-config.md`

- [x] Add tests proving `DEEPSEEK_API_KEY` wins over `VELA_GPT_COMMAND` for daily dialogue when both are configured.
- [x] Keep command adapter support as a fallback when DeepSeek/OpenAI credentials are absent.
- [x] Update runtime documentation so adapter priority matches the actual behavior.

### Task 3: Partner Loop Seams

**Files:**
- Modify: `tests/test_vela_partner_upgrade.py`
- Modify: `tools/vela_product_layers.py`

- [x] Add `ToolSelection` and `LearningEvaluation` dataclasses.
- [x] Add `select_model_and_tools()` so every intent has an explicit lane, model/tool choice, and reason.
- [x] Add `evaluate_learning()` so feedback can affect the next reply without being promoted straight into strategic memory.
- [x] Integrate learning evaluation into `run_layered_response()` quality logs.

### Task 4: Acceptance Verification

**Files:**
- Test-only command output

- [x] Run focused tests for partner upgrade, router, reply engine, product layers, and Codex bridge.
- [x] Run all Python unit tests.
- [x] Run the eight WeChat acceptance prompts through `tools/vela_router.py` or `reply_for()` with send-once state isolated when needed.
- [x] Add runtime audit dispatch trace for Weixin inbound gaps: session file and context-token movement are reported without exposing message content, IDs, cursors, tokens, or local paths.
- [x] Report remaining production risks: live external search/API freshness, persistent cc-connect env injection, and any screenshot limitations.
