# LLM Proxy

A modular, stateless proxy server that exposes non-standard LLM provider APIs as OpenAI-compatible endpoints. Runs as a single Docker container with path-based routing for multiple providers. Designed to integrate with [OpenCode](https://github.com/opencode-ai/opencode) (Charmbracelet Crush) as a custom `openai-compat` provider.

## Motivation

Many LLM aggregator services (T3.chat, etc.) offer access to dozens of models under a single subscription but lack official APIs. This proxy bridges that gap by translating their internal web APIs into the OpenAI `/v1/chat/completions` standard, making them usable from any OpenAI-compatible client.

## Architecture

```
OpenCode provider configs:
  t3chat.base_url   = http://localhost:4141/t3chat/v1
  future.base_url   = http://localhost:4141/future/v1
        |
        v
+---------------------------------------------+
|     LLM Proxy Container (:4141)             |
|                                             |
|  /t3chat/v1/*   -->  T3ChatAdapter          |
|  /future/v1/*   -->  FutureAdapter          |
|  /health        -->  health check           |
|  /providers     -->  list adapters          |
+---------------------------------------------+
        |
        v  (per-adapter upstream calls)
   T3.chat, Future Service, ...
```

## Current Providers

- **T3 Chat** (`/t3chat/v1/`): Translates T3.chat's internal SSE API into OpenAI-compatible completions. Supports streaming and non-streaming modes, reasoning content passthrough, and dynamic model discovery from the T3.chat frontend (with hardcoded fallback).

## Key Design Decisions

- **Stateless**: No auth stored in the proxy. Credentials are passed per-request via the `Authorization` header (base64-encoded JSON).
- **Modular**: Each backend provider is a self-contained adapter module in `src/llm_proxy/providers/`. Adding a new provider means adding one Python file and rebuilding the container.
- **Single container, path-based routing**: All adapters run in one container. OpenCode selects the provider via `base_url` path prefix.
- **OpenAI-compatible**: Speaks the `/v1/chat/completions` and `/v1/models` protocols, works with OpenCode, Continue, Cursor, or any OpenAI-compatible client.
- **Streaming-first**: Translates provider-specific SSE formats into OpenAI-compatible SSE in real time.
- **Dynamic model discovery**: T3 adapter scrapes available models from T3.chat at startup, with hardcoded fallback.
- **Config generation**: On startup, writes OpenCode provider JSON configs and an `update_opencode_config.sh` helper script to the `output/` volume.
- **Docker-only**: `docker compose up` is the primary interface.

## Usage

### Start the Proxy

```sh
docker compose up --build -d
```

The proxy listens on port `4141`.

### Credential Setup (T3.chat)

T3.chat credentials (browser cookies and session ID) must be base64-encoded as JSON and passed via the `Authorization: Bearer <token>` header. Two helper scripts are provided in `scripts/`:

- **`scripts/extract_from_curl.sh`**: Paste a cURL command copied from Chrome DevTools and the script extracts and encodes credentials automatically.
- **`scripts/extract_t3_creds.sh`**: Manual mode -- prompts you to paste the Cookie header value and convexSessionId separately.

Both scripts output an `export T3_CHAT_CREDS='...'` line to add to your shell profile.

### OpenCode Integration

On startup, the proxy generates OpenCode provider config files in the `output/` directory:

- `opencode_provider_t3chat.json` -- Provider definition with all discovered models.
- `update_opencode_config.sh` -- Merges the provider config into your `~/.config/opencode/opencode.json`.
- `t3chat_bookmarklet.html` -- Browser bookmarklet for extracting T3.chat credentials interactively.

### API Endpoints

- `GET /health` -- Health check.
- `GET /providers` -- List registered adapters and model counts.
- `POST /{provider_id}/v1/chat/completions` -- OpenAI-compatible chat completions (streaming and non-streaming).
- `GET /{provider_id}/v1/models` -- List available models for a provider.

## Directory Structure

```
llm_proxy/
  docker-compose.yml    # Container definition (port 4141, output volume)
  Dockerfile            # Python 3.12-slim, uvicorn entrypoint
  pyproject.toml        # Dependencies and build config (hatchling)
  docs/                 # Design document and implementation plan
  output/               # Generated OpenCode configs (mounted volume)
  scripts/
    extract_from_curl.sh    # Credential extractor (cURL paste mode)
    extract_t3_creds.sh     # Credential extractor (manual mode)
  src/llm_proxy/
    main.py                 # FastAPI app with lifespan, health, and provider listing
    config.py               # Settings (host, port, log_level, output_dir)
    auth.py                 # Base64 credential decoding from Authorization header
    models.py               # Pydantic models for OpenAI request/response types
    provider_base.py        # Abstract ProviderAdapter base class with router creation
    provider_registry.py    # Auto-discovery and registration of provider modules
    config_generator.py     # Writes OpenCode JSON configs and helper scripts on startup
    providers/
      t3chat.py             # T3.chat adapter (model discovery, SSE translation, session refresh)
  tests/
    test_auth.py
    test_config_generator.py
    test_models.py
    providers/
      test_t3chat.py
```

## Development

```sh
pip install -e ".[dev]"
pytest
```

Tests use `pytest-asyncio` and `pytest-httpx`. See `pyproject.toml` for full dev dependency list.
