# Output Directory

This directory is volume-mounted from the Docker container (`./output:/output`). The proxy regenerates these files at every container startup based on the providers and models it discovers.

## Files

| File | Purpose |
|------|---------|
| `opencode_provider_t3chat.json` | Provider + model config ready to merge into OpenCode |
| `update_opencode_config.sh` | Script that merges the provider JSON into your OpenCode config |
| `t3chat_bookmarklet.html` | Browser bookmarklet for credential extraction (alternative to the shell scripts) |

## Setup Steps

### Prerequisites

1. The proxy container is running (`docker compose up -d`)
2. You have `T3_CHAT_CREDS` exported in your shell (see [`../scripts/README.md`](../scripts/README.md))

### 1. Merge models into OpenCode

The update script merges the provider and model definitions into your OpenCode config file. It creates the file if it doesn't exist.

```bash
# Default target: ~/.config/opencode/opencode.json
./output/update_opencode_config.sh

# Or specify a custom path:
./output/update_opencode_config.sh /path/to/opencode.json
```

This adds (or updates) the `t3chat` entry under the `provider` key with all 13 discovered models. It does not modify any other providers already in your config.

### 2. Verify the config

After running the update script, your `opencode.json` will contain a provider block like:

```json
{
  "provider": {
    "t3chat": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "T3 Chat",
      "options": {
        "baseURL": "http://localhost:4141/t3chat/v1",
        "apiKey": "{env:T3_CHAT_CREDS}"
      },
      "models": {
        "gemini-3-flash": {"name": "Gemini 3 Flash", "limit": {"context": 200000, "output": 16000}},
        ...
      }
    }
  }
}
```

Verify OpenCode sees the models:

```bash
opencode models t3chat
```

### 3. Verify the proxy is reachable

```bash
# Health check
curl http://localhost:4141/health

# List registered providers
curl http://localhost:4141/providers

# List T3 models (no auth required)
curl http://localhost:4141/t3chat/v1/models
```

### 4. Test with credentials

```bash
curl -X POST http://localhost:4141/t3chat/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $T3_CHAT_CREDS" \
  -d '{"model": "gemini-3-flash", "messages": [{"role": "user", "content": "hello"}], "stream": false}'
```

## Refreshing Models

If T3.chat adds or removes models, restart the container to re-run discovery:

```bash
docker compose restart
```

The output files are regenerated on every startup. Run `update_opencode_config.sh` again afterward to sync the new model list into OpenCode.
