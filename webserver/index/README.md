# Dynamic Index + Proxy Controller (`index`)

Fastify-based service that powers the rich file browser and reverse-proxy manager used by the Docker Compose web server stack. It handles directory listings, endpoint configuration, and request forwarding for user-defined upstreams.

## Capabilities

- **Directory Browser (`/files`)** – Recursively scans the mounted `WEBROOT` directory, infers HTML titles, and serves a responsive explorer that mirrors the look and feel of the static site. Requests for `/` and missing files fall back to this renderer.
- **Proxy Management UI (`/configure`)** – Polished single-page app for creating, editing, enabling/disabling, and deleting reverse-proxy routes. Routes are persisted to `CONFIG_FILE` so they survive container restarts.
- **REST API (`/configure/api`)** – CRUD endpoints backing the UI; scripts can POST new routes or automate edits.
- **Reverse Proxying** – Uses `@fastify/reply-from` to stream requests/responses to upstream services, with path stripping and query preservation that mirrors the UI settings.
- **Sticky Routing + Loopback Mapping** – Remembers recent client/user-agent pairs so follow-up absolute paths keep hitting the same upstream when strip-path is enabled. Targets that point at `localhost`/`127.0.0.1` automatically remap to `HOST_DOCKER_GATEWAY` for host ↔ container bridging.

## Important Files

- `server.js` – Main Fastify app implementing the file browser, proxy controller, persistence layer, and reverse-proxy handler.
- `package.json` – Declares dependencies (`fastify`, `@fastify/reply-from`, `cheerio`) and scripts.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `WEBROOT` | `/mnt/webroot` | Directory tree to scan for the file browser. Mounted from the host `~/webroot`. |
| `CONFIG_ROOT` | `/mnt/config` | Directory for persisted proxy metadata. |
| `CONFIG_FILE` | `/mnt/config/endpoints.json` | JSON document storing the configured routes. |
| `HOST_DOCKER_GATEWAY` | `host.docker.internal` | Hostname used when upstream targets point at loopback addresses. |

All values are configurable in `docker-compose.yml`.

## Running Locally

```bash
npm install
WEBROOT=/path/to/webroot \
CONFIG_ROOT=/path/to/config \
node server.js
```

Ensure the config directory is writable; the service atomically rewrites `endpoints.json` on every change.

## Customization Tips

- **Theming:** Edit the HTML template strings in `renderDirectoryHtml` and `renderConfigureHtml` inside `server.js`. Inline CSS keeps dependencies minimal, but you can link external styles served from `WEBROOT`.
- **Additional Metadata:** Extend `scanDir` to surface file hashes, media durations, or custom icons. Update the renderer to display the new fields.
- **Automation:** Interact with the REST API (`GET/POST/PUT/DELETE /configure/api/endpoints`) to seed routes from scripts or CI jobs. The API returns the same payload shape the UI uses.

Changes to `server.js` or `package.json` require rebuilding the Docker image when running under Compose:

```bash
docker-compose up -d --build index
```
