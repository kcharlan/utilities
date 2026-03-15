# LLM Proxy

A modular, stateless proxy server that exposes non-standard LLM provider APIs as OpenAI-compatible endpoints. Runs as a single Docker container with path-based routing for multiple providers. Designed to integrate with [OpenCode](https://github.com/opencode-ai/opencode) as a custom `openai-compatible` provider.

## Motivation

Many LLM aggregator services (T3.chat, etc.) offer access to dozens of models under a single subscription but lack official APIs. This proxy bridges that gap by translating their internal web APIs into the OpenAI `/v1/chat/completions` standard, making them usable from any OpenAI-compatible client.

## Architecture

```
OpenCode provider configs:
  t3chat.baseURL    = http://localhost:4141/t3chat/v1
  future.baseURL    = http://localhost:4141/future/v1
        │
        ▼
┌─────────────────────────────────────────┐
│     LLM Proxy Container (:4141)         │
│                                         │
│  /t3chat/v1/*   ──▶  T3ChatAdapter      │
│  /future/v1/*   ──▶  FutureAdapter      │
│  /health        ──▶  health check       │
│  /providers     ──▶  list adapters      │
└─────────────────────────────────────────┘
        │
        ▼  (per-adapter upstream calls)
   T3.chat, Future Service, ...
```

## Key Design Decisions

- **Stateless**: No auth stored in the proxy. Credentials are passed per-request via the `Authorization` header (base64-encoded JSON).
- **Modular**: Each backend provider is a self-contained adapter module. Adding a new provider means adding one Python file and rebuilding the container.
- **Single container, path-based routing**: All adapters run in one container. OpenCode selects the provider via `baseURL` path prefix.
- **OpenAI-compatible**: Speaks the `/v1/chat/completions` protocol, works with OpenCode, Continue, Cursor, or any OpenAI-compatible client.
- **Streaming-first**: Translates provider-specific SSE formats into OpenAI-compatible SSE in real time.
- **Dynamic model discovery**: T3 adapter scrapes available models from T3.chat at startup, with hardcoded fallback.
- **Docker-only**: `docker compose up` is the primary interface. No bare-metal run.

## Authentication Setup

Credentials are extracted from a live T3.chat browser session and passed per-request as a base64-encoded Bearer token. See [`scripts/README.md`](scripts/README.md) for detailed instructions.

Quick start:

```bash
# Save a "Copy as cURL" from Chrome DevTools to a file, then:
./scripts/extract_from_curl.sh ~/t3_curl.txt

# Add the output to your shell profile:
export T3_CHAT_CREDS='eyJjb29raWVzIjoi...'
```

## OpenCode Integration

The container writes provider config and a merge script to the `output/` volume on every startup. See [`output/README.md`](output/README.md) for detailed steps.

Quick start:

```bash
# Merge T3 models into OpenCode config:
./output/update_opencode_config.sh

# Verify the proxy is up:
curl http://localhost:4141/health
```

## Logging

The proxy defaults to `info` level logging (startup messages, warnings, errors). Set the `LOG_LEVEL` environment variable to adjust verbosity without rebuilding the container.

```bash
# Enable debug logging (tool names, JSON recovery, request details)
LOG_LEVEL=debug docker compose up -d

# Back to normal (default info level)
docker compose up -d
```

Available levels: `debug`, `info`, `warning`, `error`, `critical`.

## Tool Calling

The proxy translates OpenAI-format tool calling for providers that don't support it natively (like T3.chat). This enables OpenCode plugins and custom tools to work through the proxy.

**How it works:**

1. **Inbound**: Tool definitions from the `tools` parameter are injected into the system prompt so the model knows what tools are available.
2. **Model output**: When the model outputs `<tool_call>` XML blocks, the proxy parses them into structured OpenAI `tool_calls` deltas for the client to execute.
3. **Results**: When the client sends `role: "tool"` messages with results, the proxy converts them to `<tool_result>` XML that the upstream model can understand.

The parser handles common model quirks like malformed JSON (extra trailing braces) and partial tags split across streaming chunks.

## BYOK Auto-Retry

Some models on T3.chat require a user-provided API key (BYOK) at higher reasoning tiers. The proxy detects `api_key_required` errors and automatically retries with `reasoningEffort: "low"` on a per-model basis. Subsequent requests for the same model skip straight to low reasoning to avoid the failed first attempt.

## Convenience Scripts

- `up.sh` — Builds and starts the container (`docker-compose up -d --build`).
- `down.sh` — Stops the container (`docker-compose down`).

## Reasoning Content

For models that support extended thinking (e.g. Gemini thinking, GPT reasoning), the proxy streams `reasoning_content` deltas alongside regular `content` deltas, matching the OpenAI `reasoning_content` convention so compatible clients can display the model's chain-of-thought.

## Status

Under development. See `docs/` for the design document.
