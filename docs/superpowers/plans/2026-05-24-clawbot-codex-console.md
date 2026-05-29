# Clawbot Codex Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local "VELA" console command for cc-connect/WeChat that can inspect desktop Codex projects, goal state, recent conversation content, and run with highest local Codex permissions.

**Architecture:** Keep cc-connect itself unchanged and add a focused local Python console script plus a PowerShell wrapper. Register the script as global cc-connect slash commands, and switch the Codex agent mode from `suggest` to `yolo` in the existing local config.

**Tech Stack:** Python standard library (`sqlite3`, `json`, `tomllib`), PowerShell wrapper, cc-connect TOML config.

---

### Task 1: Console Tests

**Files:**
- Create: `tests/test_clawbot_codex_console.py`

- [ ] **Step 1: Write failing tests**

Add tests for secret redaction, Codex status rendering, and rollout message extraction.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_clawbot_codex_console -v`
Expected: FAIL because `tools/clawbot_codex_console.py` does not exist yet.

### Task 2: Console Implementation

**Files:**
- Create: `tools/clawbot_codex_console.py`
- Create: `tools/clawbot-codex-console.ps1`

- [ ] **Step 1: Implement the console script**

Read Codex SQLite state from `%USERPROFILE%\.codex`, cc-connect config from `%USERPROFILE%\.cc-connect`, and print compact Chinese summaries capped for WeChat.

- [ ] **Step 2: Run tests**

Run: `python -m unittest tests.test_clawbot_codex_console -v`
Expected: PASS.

### Task 3: cc-connect Configuration

**Files:**
- Modify: `C:\Users\Admin\.cc-connect\config.toml`

- [ ] **Step 1: Switch Codex permission mode**

Set `[projects.agent.options].mode` to `yolo`.

- [ ] **Step 2: Register WeChat commands**

Add `/clawbot`, `/vela`, and Chinese aliases for quick status access.

- [ ] **Step 3: Validate command locally**

Run the PowerShell wrapper and confirm it prints a "VELA" console without exposing tokens.

### Task 4: Restart and Verify

**Files:**
- Read: `C:\Users\Admin\.cc-connect\cc-connect.log`

- [ ] **Step 1: Restart cc-connect**

Stop the existing `cc-connect.exe` process and start it again with the existing startup script.

- [ ] **Step 2: Verify process and log**

Confirm a new process is running and the log shows the Weixin platform starting without config errors.
