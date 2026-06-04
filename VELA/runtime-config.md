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

Weather prompts keep their `weather_query` intent so they do not fall into casual chat. They first use the realtime weather evidence layer, then the dialogue adapter renders VELA's concise answer when configured. If the source is unavailable, the foreground must say so and fall back to conservative travel-risk guidance; VELA must not invent temperature, rain probability, or precise forecast data.

Weather provider MVP is enabled only when both env vars are present:

- `VELA_WEATHER_PROVIDER`: currently supports `weatherapi`.
- `VELA_WEATHER_API_KEY`: WeatherAPI provider key. Keep it in the process/user environment, never in this repo.
- `VELA_DEFAULT_WEATHER_LOCATION`: optional local context fallback for prompts such as "今天适合出门吗". If unset and the user gives no place, VELA asks for a city instead of guessing.

No provider/key behavior is explicit: VELA says it has not connected a real weather source and cannot give realtime weather. Raw connector flags stay inside tests/logs; WeChat output must not show `provider_not_configured`, `connector_unavailable`, `source_type`, or `evidence_id`.

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

## Final Reply Humanizer

The final foreground pass runs after persona rendering and guardrails. It is not a template generator; it is the last quality gate for WeChat-facing language. `router.reply_for()` and `run_layered_response()` both pass WeChat-visible text through this last-mile foreground filter, including Codex, weather, market, current-info, ordinary chat, and fallback paths.

- Answer-first questions, especially `现在...`, `多久`, `能不能`, `为什么`, `过滤啥`, and direct correction prompts, must put the useful answer before status or explanation.
- Time and factual lanes must remove self-proving meta lines such as local-computation explanations, "not a chat template" claims, or tool-chain bragging. If the fact is available, keep the fact and a human next-sentence; drop defensive proof labels. Example: a New York time query should answer with the clock, date/UTC offset, and a practical time-window judgment, not a meta explanation of how the clock was computed.
- DeepSeek API is the dialogue/reasoning adapter, not an automatic external search source. If the user asks why DeepSeek cannot "directly retrieve资料", explain the model-vs-retrieval boundary in plain Chinese and name the missing retrieval layer: search, webpage capture, market/weather data source, or another verified source.
- Realtime/cache boundaries must be translated into plain Chinese: `实时源暂不可用`, `实时源未接入`, `有本地缓存可参考`, and the practical next step. Raw `数据来源：`, `状态边界：`, `缓存摘要`, `模型仅生成`, API status, schema keys, and internal paths stay out of WeChat.
- Style feedback such as "太像机器人", "太刻板", "没懂我", or "不是这个意思" is a next-turn behavior signal. The next reply should reduce fixed openings, answer the core first, and repair the misunderstanding by performance, not by saying it has calibrated itself.
- Fixed `K，` openings are not identity proof and should not be required by tests. The fallback engine and last-mile output should prefer short natural openings such as `在。你说。`, `我在。听着。`, or a direct factual answer.

## Memory Safety

Learning-loop candidates are soft context, not permanent truth. Sensitive memory instructions are not persisted as candidates; VELA should state the boundary in plain Chinese and wait for explicit confirmation before any sensitive storage path is considered. Non-sensitive preference candidates can shape the next reply, but they must remain marked as unconfirmed until the user confirms them. When the user explicitly confirms the latest non-sensitive preference candidate, VELA promotes it to `confirmed-preferences-*.jsonl` and stops injecting the duplicate unconfirmed candidate into reply context.

Session notes are short-term local context, not permanent memory. Each foreground reply writes a session note, and the context builder reads recent session notes alongside interaction logs, candidate preferences, human-iteration next-turn signals, and strategic memory before the next reply. This lets VELA continue a thread without promoting temporary context into long-term truth.

Strategic memory candidates, such as project goals or persona direction, are read as unconfirmed strategic context. They must not be promoted to `Strategic Memory` unless explicitly confirmed. When explicitly confirmed, VELA writes the item to `strategic-memory-*.jsonl` with its memory type and hides the old strategic candidate from active context.

Interaction logs are local diagnostic memory. They mark repeated messages, feedback type, candidate-memory status, response latency, foreground lane, and response quality issues so the next turn can adapt without exposing raw schema or promoting one-off feedback into permanent truth.

Project A completion-loop memory adds a separate backstage need-research layer under `VELA/learning-loop`:

- `interaction-log-*.jsonl`: sanitized per-turn trace with query type, explicit request summary, inferred hidden need, source types, evidence summary, final answer summary, uncertainty/boundary, feedback type, next-turn improvement, and confirmation need.
- `style-feedback-candidates-*.jsonl`: unconfirmed expression candidates such as `reduce_template_tone`, `answer_first`, `avoid_self_explanation`, `repair_previous_answer_without_defense`, `avoid_fixed_k_prefix`, or `warmer_partner_tone`.
- `need-profile-candidates-*.jsonl`: unconfirmed need-profile candidates such as `expects_proactive_context_understanding`, `retrieval_when_needed`, `memory_continuity`, `strategic_judgment`, `needs_evidence_boundary`, or `needs_financial_freshness_boundary`.
- `memory-candidates-*.jsonl`: non-sensitive reusable preference or behavior candidates. These remain unconfirmed until the user explicitly confirms them.
- `strategic-memory-*.jsonl`: confirmed long-term principles only; writes require explicit user confirmation.

The context builder reads recent style and need-profile candidates before the next reply. These candidates may change wording, reply shape, and repair behavior, but they must not fabricate facts, imply confirmed preferences, or expand into private user profiling. Stored values are short summaries/tags only; API keys, internal paths, long raw user text, and sensitive payloads are redacted or skipped.

## Factual Status Boundary

Market, weather, and realtime-info lanes must distinguish:

- `real_time_source_available`
- `cached_summary_available`
- `model_generated_only`
- `unavailable`

The raw field names stay inside local state and tests. WeChat output uses plain Chinese status labels, such as whether realtime source is connected, whether cache is available, whether the answer is only a model risk suggestion, and what the user can do next.

## Real-Time Intelligence Layer

Realtime-capable questions now pass through a local evidence layer before model/persona wording:

`User Message -> Intent Router -> Source Planner -> Connector Fetch -> Evidence Packet Builder -> Context Builder -> DeepSeek / Model Reasoning -> VELA Persona Renderer -> Final Reply Humanizer -> WeChat Output -> Local Learning Candidate`

The MVP implementation lives in `tools/vela_realtime_intelligence.py` and keeps four responsibilities separate:

- `SourcePlan`: decides whether the request needs outside material and which source families apply: `web_search`, `news`, `market_data`, `weather`, `local_memory`, `local_files`, `user_uploaded_context`, or `generic_tool_connector`.
- `RetrievalConnector`: a replaceable connector interface with `can_handle`, `fetch`, `normalize`, and `build_evidence_packet`. Current connectors are local/cache/MVP placeholders unless a real source is already configured.
- `EvidencePacket`: stores normalized source evidence for the model, including freshness status, key values, confidence, origin, and known limits.
- `Realtime Boundary Formatter`: translates source state into user-facing Chinese without leaking raw field names.

DeepSeek remains the reasoning/dialogue adapter. It is not treated as a search engine. If a source is missing, VELA must say the source is missing, use cache only when explicitly safe, and never invent current market numbers, weather values, account metrics, or web search results.

Web/news search is enabled only when both env vars are present:

- `VELA_SEARCH_PROVIDER`: currently supports `serper`.
- `VELA_SEARCH_API_KEY`: search provider key. Keep it in the process/user environment, never in this repo.

If either value is missing, VELA returns a plain boundary such as "网页/新闻搜索源未接入" and must not mock or imply realtime retrieval.

Weather source is enabled only when both env vars are present:

- `VELA_WEATHER_PROVIDER=weatherapi`
- `VELA_WEATHER_API_KEY`: provider key

Weather evidence packets include the normal evidence fields plus normalized weather values in `key_values`: `location`, `temperature`, `condition`, `precipitation_probability`, `wind`, `humidity`, `forecast_window`, optional `provider_updated_at`, `source_url_or_origin`, `confidence_level`, and `known_limits`. The foreground weather reply should start with a practical conclusion, then key data, then update time/boundary.

Market data is enabled only when both env vars are present:

- `VELA_MARKET_PROVIDER`: currently supports `alpha_vantage` for MVP provider-ready market data.
- `VELA_MARKET_API_KEY`: market provider key. Keep it in the process/user environment, never in this repo.

Alpha Vantage market support currently normalizes:

- USD/CNY style FX questions through `CURRENCY_EXCHANGE_RATE`.
- Mapped quote questions such as VIX/S&P/Nasdaq/DXY through `GLOBAL_QUOTE`.

If the market provider is missing, unsupported, or returns unusable payloads, VELA must not give a current number. It should return a five-part capability boundary: current usable data, unavailable data, what can still be judged, what cannot be determined, and the next provider/config step. If a provider returns data, the foreground answer must include data time, provider/source, delay/cache/realtime status, and a reminder that finance output is auxiliary judgment, not a deterministic buy/sell instruction.

Source-specific boundaries:

- VIX/current market/add-position questions check `market_data` before judgment. Without a real realtime market connector, VELA gives no current number and no fake live trade signal.
- Real-time financial questions plan `market_data + news + web_search`, so the market value is not treated as the whole judgment.
- Sector discussion questions such as storage or optical modules plan `market_data + news + web_search`. If those sources are incomplete, VELA says the evidence gap instead of reusing broad A-share cache as sector heat.
- Weather questions remain in the weather lane and use the configured forecast provider path, with conservative travel-risk fallback if the source fails. If the prompt has no location, VELA uses `VELA_DEFAULT_WEATHER_LOCATION` only when configured; otherwise it asks for the city.
- Life/current public information queries such as nearby life info, public notices, latest discussion, and policy checks plan `news + web_search`. If search is unavailable, VELA says that plainly and does not claim to have searched.

`VELA/source-integration-plan.json` declares provider-ready or planned source surfaces for official announcements, judicial auction, court documents, execution info, enterprise query, Eastmoney/Xueqiu market info, and the mutual-finance listed-company watchlist. The file is a connector map and output-structure contract (`daily_brief`, `topic_radar`, `company_watchlist`, `risk_signal`, `decision_log`, `local_memory`); it is not proof that any source is already connected.

Learning-loop retrieval metadata:

- `interaction-*.jsonl` and `reply-quality-*.jsonl` may include `user_query_type`, `source_types_used`, `retrieved_at`, `evidence_summary`, `final_answer_summary`, `uncertainty_or_boundary`, `style_feedback_candidate`, and `next_turn_improvement`.
- These are local diagnostic/candidate fields. Do not display them in WeChat output and do not promote preference candidates to confirmed preferences without explicit user confirmation.

## Local Acceptance Smoke

Run `python -X utf8 tools/vela_acceptance_smoke.py` for a local, side-effect-safe smoke check of foreground behavior. It uses temporary learning-loop storage by default, verifies route boundaries, two-turn feedback adaptation, weather/market freshness wording, Codex route gating without executing the bridge, response-speed budgets, and foreground leakage checks. Use `--json --log-dir <dir>` when a machine-readable report or retained smoke logs are needed. Use `--entrypoint --fake-deepseek-env` to exercise `router.reply_for()` with safe stubs and verify hard status lanes stay local even when the DeepSeek environment is present. Fast-lane smoke cases must stay within 2000 ms; cached market/news cases must stay within 8000 ms. Deep-lane DeepSeek failures are rendered as a foreground status plus a usable fallback judgment, not as silent waiting or fake complete analysis.

Run `python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json` to audit the live cc-connect edge: local VELA router config, DeepSeek/default-dialogue runtime adapter state, local learning-loop category/writability state, a no-side-effect dry run of the configured router command, slash commands, Weixin poll-buffer freshness, cc-connect process count/state, and live foreground proof. The proof surface accepts either a fresh cc-connect inbound/session path or the newer direct foreground path: `VELA/send-once/last-claim.json` plus the matching `VELA/learning-loop/interaction-*.jsonl` reply and nearby Weixin state movement. Internal `cc-connect send` messages can prove the agent/session path, but they do not prove the Weixin foreground. A failing runtime audit can still mean the code path is correct; it means the WeChat bridge is not currently proven live. The report includes `next_action` with safe WeChat prompts, an immediate `verify_command`, and a waiting `wait_command`.

If Weixin inbound is observed but no newer VELA session reply or matching local foreground proof appears, `next_action.kind` becomes `inspect_weixin_reply_dispatch`; inspect cc-connect dispatch/session-writing before asking the user to keep sending messages.

For the final live check, start `python -X utf8 tools/vela_acceptance_smoke.py --runtime-audit --json --wait-live-seconds 90`, then send one of the `next_action.prompts` from WeChat. The command waits for a fresh clean foreground proof: either cc-connect inbound plus reply, or send-once claim plus matching learning-loop reply and nearby Weixin state movement.

## Persona Skeleton

The runtime persona skeleton is mechanism-only:

- `Evidence Gate`: evidence before judgement.
- `Meaning Decoder`: decode ambiguity and hidden need before answering.
- `Identity Core`: keep VELA coherent across local memory, DeepSeek, Codex, and tools.
- `Boundary Engine`: accompany without appeasing; brake reckless shortcuts and hype.
- `Witty Correction`: natural edge plus self-correction when evidence or feedback changes.

These are control signals for the model, not character skins. Runtime prompts must not include source quotes, source-role claims, or source-persona names.
