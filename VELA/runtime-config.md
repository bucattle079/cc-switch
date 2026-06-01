# VELA Runtime Config

VELA's WeChat reply engine can use a live DeepSeek chat-completions adapter.
Keep secrets in the user or process environment, not in this repository.

## DeepSeek

- `DEEPSEEK_API_KEY`: required for live DeepSeek replies.
- `DEEPSEEK_MODEL`: optional; defaults to `deepseek-v4-flash`. `VELA_DEEPSEEK_MODEL` remains supported as a legacy alias.
- `DEEPSEEK_BASE_URL`: optional; defaults to `https://api.deepseek.com/chat/completions`. `VELA_DEEPSEEK_BASE_URL` remains supported as a legacy alias.
  If a proxy root such as `https://proxy.example/v1` is supplied, VELA appends `/chat/completions`.
- `VELA_DEEPSEEK_TIMEOUT_SECONDS`: optional; defaults to `20`, clamped to `5..45`.
- `VELA_DEEPSEEK_FAST_TIMEOUT_SECONDS`: optional; defaults to `2`, clamped to `1..2` for fast foreground dialogue before fallback.
- `VELA_DEEPSEEK_DEEP_TIMEOUT_SECONDS`: optional; defaults to `8`, clamped to `5..8` for deep foreground analysis before fallback/status-safe behavior.
- `VELA_DEEPSEEK_THINKING`: optional; `disabled` by default for short WeChat replies, or `enabled` when deeper reasoning is useful.

Adapter priority is:

1. `DEEPSEEK_API_KEY`
2. `VELA_GPT_COMMAND`
3. `VELA_OPENAI_API_KEY`
4. `OPENAI_API_KEY`
5. deterministic fallback replies

Daily dialogue should use DeepSeek when `DEEPSEEK_API_KEY` is present. Command/Codex adapters are fallback or engineering lanes, not the default ordinary chat brain.
Except for Codex-related instructions, ordinary WeChat-facing dialogue should go through the DeepSeek dialogue adapter when configured. Hard status lanes are stricter: freshness status, market refresh state, and weather source boundaries keep local foreground wording so a model cannot blur cache, realtime availability, or unavailable data.
The local cc-connect startup script maps canonical `DEEPSEEK_MODEL` and `DEEPSEEK_BASE_URL` into the legacy `VELA_DEEPSEEK_*` aliases for compatibility; the canonical names stay authoritative.

## Weather

Weather does not require a dedicated weather API in this VELA runtime. Weather prompts keep their `weather_query` intent so they do not fall into casual chat, but they do not enable external retrieval. VELA must not invent realtime temperature, rain probability, or precise forecast data. The model should answer as a risk-framing companion: state the boundary, then give practical actions such as umbrella, temperature-gap caution, and schedule buffer.

## Companion Core

Every WeChat-facing reply should carry internal context that is not exposed to the user:

- `need_interpretation`: the user's hidden need behind the surface intent, such as style-feedback reassurance, project continuity, or market risk judgement.
- `humanization_layer_enabled=true`
- `persona_distillation_mode=mechanism_only`
- `copyrighted_quote_storage=false`
- `character_roleplay=false`
- `local_learning_update=true`
- `deepseek_adapter_enabled=true`
- `response_mode`: one of `daily_companion`, `strategic_depth`, `relationship_repair`, `quiet_support`, `boundary_pushback`, `identity_continuity`, `project_operator`, or `market_brief`.
- `human_tone_vector`: local control values for warmth, directness, strategic depth, emotional presence, clarification need, and memory reference need.
- `pressure_scenario`: the current conversational pressure, such as fatigue, chaos, mechanical-tone correction, or strategic judgement.
- `active_persona_capabilities`: the active subset of Evidence Gate, Meaning Decoder, Identity Core, Boundary Engine, and Witty Correction.
- `detected_user_state`: the current user state inferred from the message, such as fatigue, misread frustration, risk pressure, or identity calibration.
- `inferred_hidden_need`: the hidden need that should shape the reply before wording.
- `response_behavior_mode`: the behavior mode used by the reply engine, aligned with but more explicit than `response_mode`.
- `should_clarify`, `should_push_back`, `should_use_evidence_gate`, `should_reference_memory`: boolean behavior controls for the next reply.
- `tone_adjustment_reason`: short internal reason for the tone shift.
- `user_preferences`: confirmed preferences plus recent non-sensitive preference candidates, clearly marked as unconfirmed when they are not permanent memory.
- `strategic_memories`: confirmed long-term project/persona/decision memory, used only when relevant.
- `human_iteration_signal`: local post-reply learning row with `user_message_type`, `detected_user_state`, `inferred_hidden_need`, `active_persona_capabilities`, `response_behavior_mode`, `response_quality_signals`, `user_feedback_type`, `correction_needed`, `memory_update_candidate`, `tone_adjustment_candidate`, and `next_turn_improvement`.

These fields are prompt and learning inputs only. They must not appear in WeChat output as raw keys, schema names, paths, logs, or debug text.
Mechanism distillation is abstract behavior only: VELA keeps her own identity, stores no source lines, and never roleplays a source character.

## Memory Safety

Learning-loop candidates are soft context, not permanent truth. Sensitive memory instructions are not persisted as candidates; VELA should state the boundary in plain Chinese and wait for explicit confirmation before any sensitive storage path is considered. Non-sensitive preference candidates can shape the next reply, but they must remain marked as unconfirmed until the user confirms them.

Session notes are short-term local context, not permanent memory. Each foreground reply writes a session note, and the context builder reads recent session notes alongside interaction logs, candidate preferences, human-iteration next-turn signals, and strategic memory before the next reply. This lets VELA continue a thread without promoting temporary context into long-term truth.

Strategic memory candidates, such as project goals or persona direction, are read as unconfirmed strategic context. They must not be promoted to `Strategic Memory` unless explicitly confirmed.

Interaction logs are local diagnostic memory. They mark repeated messages, feedback type, candidate-memory status, response latency, foreground lane, and response quality issues so the next turn can adapt without exposing raw schema or promoting one-off feedback into permanent truth.

## Factual Status Boundary

Market, weather, and realtime-info lanes must distinguish:

- `real_time_source_available`
- `cached_summary_available`
- `model_generated_only`
- `unavailable`

The raw field names stay inside local state and tests. WeChat output uses plain Chinese status labels, such as whether realtime source is connected, whether cache is available, whether the answer is only a model risk suggestion, and what the user can do next.

## Local Acceptance Smoke

Run `python -X utf8 tools/vela_acceptance_smoke.py` for a local, side-effect-safe smoke check of foreground behavior. It uses temporary learning-loop storage by default, verifies route boundaries, two-turn feedback adaptation, weather/market freshness wording, Codex route gating without executing the bridge, response-speed budgets, and foreground leakage checks. Use `--json --log-dir <dir>` when a machine-readable report or retained smoke logs are needed. Use `--entrypoint --fake-deepseek-env` to exercise `router.reply_for()` with safe stubs and verify hard status lanes stay local even when the DeepSeek environment is present. Fast-lane smoke cases must stay within 2000 ms; cached market/news cases must stay within 8000 ms. Deep-lane DeepSeek failures are rendered as a foreground status plus a usable fallback judgment, not as silent waiting or fake complete analysis.

Run `python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json` to audit the live cc-connect edge: local VELA router config, DeepSeek/default-dialogue runtime adapter state, local learning-loop category/writability state, a no-side-effect dry run of the configured router command, slash commands, Weixin poll-buffer freshness, cc-connect process count/state, latest VELA session reply freshness/foreground cleanliness, whether a Weixin inbound message was observed, and whether a newer inbound WeChat message lacks a newer VELA session reply. Internal `cc-connect send` messages can prove the agent/session path, but they do not prove the Weixin foreground. A failing runtime audit can still mean the code path is correct; it means the WeChat bridge is not currently proven live. The report includes `next_action` with safe WeChat prompts, an immediate `verify_command`, and a waiting `wait_command`.

If Weixin inbound is observed but no newer VELA session reply appears, `next_action.kind` becomes `inspect_weixin_reply_dispatch`; inspect cc-connect dispatch/session-writing before asking the user to keep sending messages.

For the final live check, start `python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json --wait-live-seconds 90`, then send one of the `next_action.prompts` from WeChat. The command waits for both the Weixin inbound log and a fresh clean VELA session reply before returning success.

## Persona Skeleton

The runtime persona skeleton is mechanism-only:

- `Evidence Gate`: evidence before judgement.
- `Meaning Decoder`: decode ambiguity and hidden need before answering.
- `Identity Core`: keep VELA coherent across local memory, DeepSeek, Codex, and tools.
- `Boundary Engine`: accompany without appeasing; brake reckless shortcuts and hype.
- `Witty Correction`: natural edge plus self-correction when evidence or feedback changes.

These are control signals for the model, not character skins. Runtime prompts must not include source quotes, source-role claims, or source-persona names.
