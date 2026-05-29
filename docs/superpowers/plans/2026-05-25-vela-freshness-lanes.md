# VELA Freshness Lanes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make VELA answer freshness/status questions quickly, serve market briefs from cache first, and keep explicit refresh work out of the foreground reply path.

**Architecture:** Add a market data freshness object in `tools/vela_market_briefing.py`, then route status, cached market, and refresh requests separately in `tools/vela_router.py`. Keep GPT/Codex out of Fast Lane and reduce command-adapter timeout so ordinary chat degrades quickly.

**Tech Stack:** Python unittest, existing VELA router/market/reply engine modules, cc-connect PowerShell startup script.

---

### Task 1: Red Tests For Freshness And Latency Lanes

**Files:**
- Modify: `tests/test_vela_intent_router.py`
- Modify: `tests/test_vela_reply_engine.py`

- [ ] **Step 1: Add failing router tests**

Add tests for:
- `这是实时的吗` routes to `freshness_status`.
- `刷新最新市场资讯` routes to `market_refresh`.
- `reply_for("你好")` stays under two seconds even when `VELA_GPT_COMMAND` points at a slow command.
- cached market replies include cache/freshness status and do not expose schema fields.

- [ ] **Step 2: Add failing timeout test**

Change command timeout expectations so GPT command defaults to a short foreground budget and clamps long configured values.

- [ ] **Step 3: Run red tests**

Run: `python -X utf8 -m unittest tests.test_vela_intent_router tests.test_vela_reply_engine`

Expected: failures showing missing freshness/refresh intents and old timeout behavior.

### Task 2: Data Freshness Layer

**Files:**
- Modify: `tools/vela_market_briefing.py`

- [ ] **Step 1: Add `MarketFreshnessStatus`**

Fields:
- `data_status`
- `last_updated`
- `source_type`
- `refresh_available`
- `refresh_in_progress`
- `confidence_note`
- `slot`
- `cache_path`

- [ ] **Step 2: Add cache-only helpers**

Implement:
- `load_latest_cached_brief()`
- `market_freshness_status()`
- `format_freshness_status()`
- `build_cached_market_brief()`

- [ ] **Step 3: Verify tests**

Run router tests and keep output Chinese-friendly.

### Task 3: Router Lanes

**Files:**
- Modify: `tools/vela_router.py`

- [ ] **Step 1: Add intent keywords**

Add status keywords for freshness questions and refresh keywords for explicit refresh requests.

- [ ] **Step 2: Implement lanes**

Fast Lane:
- freshness status
- simple greeting, using local fallback adapter only

Cached Market Lane:
- cache first
- include status line
- no network refresh in foreground

Refresh Lane:
- short status reply
- no fake async completion

- [ ] **Step 3: Verify tests**

Run router tests and 6 manual acceptance timings.

### Task 4: Timeout And Startup

**Files:**
- Modify: `tools/vela_reply_engine.py`
- Modify: `C:\Users\Admin\.cc-connect\start-cc-connect.ps1`

- [ ] **Step 1: Reduce foreground GPT command timeout**

Clamp foreground GPT command timeout to a short budget and fall back internally.

- [ ] **Step 2: Update cc-connect startup env**

Set `VELA_GPT_TIMEOUT_SECONDS` to `12`.

- [ ] **Step 3: Restart cc-connect**

Run the startup script and confirm a single patched process is active.

### Task 5: Final Verification

**Files:**
- Test-only command output

- [ ] **Step 1: Full unit tests**

Run: `python -X utf8 -m unittest discover -s tests -p "test_*.py"`

- [ ] **Step 2: Acceptance timings**

Measure the 6 user inputs:
- `这是实时的吗`
- `如果不是实时的重要资讯梳理给我`
- `给我现在的市场资讯`
- `刷新最新市场资讯`
- `你好`
- `今天A股怎么看`

- [ ] **Step 3: Report gaps**

State what still requires real external APIs/search and what is intentionally cache/status based.
