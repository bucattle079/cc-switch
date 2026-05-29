# VELA Runtime Config

VELA's WeChat reply engine can use a live DeepSeek chat-completions adapter.
Keep secrets in the user or process environment, not in this repository.

## DeepSeek

- `DEEPSEEK_API_KEY`: required for live DeepSeek replies.
- `VELA_DEEPSEEK_MODEL`: optional; defaults to `deepseek-v4-flash`.
- `VELA_DEEPSEEK_BASE_URL`: optional; defaults to `https://api.deepseek.com/chat/completions`.
  If a proxy root such as `https://proxy.example/v1` is supplied, VELA appends `/chat/completions`.
- `VELA_DEEPSEEK_TIMEOUT_SECONDS`: optional; defaults to `20`, clamped to `5..45`.
- `VELA_DEEPSEEK_THINKING`: optional; `disabled` by default for short WeChat replies, or `enabled` when deeper reasoning is useful.

Adapter priority is:

1. `VELA_GPT_COMMAND`
2. `DEEPSEEK_API_KEY`
3. `VELA_OPENAI_API_KEY`
4. `OPENAI_API_KEY`
5. deterministic fallback replies

