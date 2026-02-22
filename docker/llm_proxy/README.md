# LLM Proxy

A modular, stateless proxy server that exposes non-standard LLM provider APIs as OpenAI-compatible endpoints. Runs as a single Docker container with path-based routing for multiple providers. Designed to integrate with [OpenCode](https://github.com/opencode-ai/opencode) (Charmbracelet Crush) as a custom `openai-compat` provider.

## Motivation

Many LLM aggregator services (T3.chat, etc.) offer access to dozens of models under a single subscription but lack official APIs. This proxy bridges that gap by translating their internal web APIs into the OpenAI `/v1/chat/completions` standard, making them usable from any OpenAI-compatible client.

## Architecture

```
OpenCode provider configs:
  t3chat.base_url   = http://localhost:4141/t3chat/v1
  future.base_url   = http://localhost:4141/future/v1
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
- **Single container, path-based routing**: All adapters run in one container. OpenCode selects the provider via `base_url` path prefix.
- **OpenAI-compatible**: Speaks the `/v1/chat/completions` protocol, works with OpenCode, Continue, Cursor, or any OpenAI-compatible client.
- **Streaming-first**: Translates provider-specific SSE formats into OpenAI-compatible SSE in real time.
- **Dynamic model discovery**: T3 adapter scrapes available models from T3.chat at startup, with hardcoded fallback.
- **Docker-only**: `docker compose up` is the primary interface. No bare-metal run.

## Status

Under development. See `docs/` for design document and implementation plan.
