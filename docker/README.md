# Docker Projects

This directory now groups all Docker-focused projects that previously lived at the repository root.

## Current Contents

- `actual-data/` - Local Actual Budget server data and helper scripts.
- `excalidraw/` - Docker Compose setup for a local Excalidraw instance.
- `llm_collector/` - LLM usage collector service, browser extension, and container runtime files.
- `llm_proxy/` - Modular OpenAI-compatible proxy for non-standard LLM providers (currently T3.chat).
- `mermaid/` - Shell scripts for running the Mermaid Live Editor container.
- `webserver/` - Multi-service local web stack (Nginx + FastAPI + Express + index/config UI).

## Structure Change

These directories were moved from repo root into `docker/`:

- `actual-data` -> `docker/actual-data`
- `excalidraw` -> `docker/excalidraw`
- `llm_collector` -> `docker/llm_collector`
- `mermaid` -> `docker/mermaid`
- `webserver` -> `docker/webserver`

`llm_proxy` was created directly under `docker/`.

If you have personal scripts, aliases, or automations using the old root paths, update them to the new `docker/...` locations.
