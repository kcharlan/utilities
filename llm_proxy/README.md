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

## Status

Under development. See `docs/` for design document and implementation plan.
