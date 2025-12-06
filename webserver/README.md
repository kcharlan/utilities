# Local Web Server with Docker Compose

This project provides a versatile local web server environment orchestrated with Docker Compose. It features an Nginx reverse proxy, a dynamic directory listing service (Node.js), a Python FastAPI backend, and a Node.js Express backend. This setup is ideal for local development, testing various backend services, and serving static content with a browsable index.

## Architecture Overview

The web server is composed of several interconnected services:

*   **Nginx (`web` service):** Acts as the primary entry point, serving static files from a designated `webroot` directory and routing requests to the appropriate backend services.
*   **Dynamic Index + Config (`index` service):** A Node.js Fastify app that serves a polished file browser for the `webroot`, and hosts the `/configure` UI for defining dynamic reverse-proxy endpoints. It also proxies requests for configured endpoints directly to your upstream services.
*   **Python API (`app_py` service):** A FastAPI application providing a sample API endpoint.
*   **Node.js API (`app_node` service):** An Express.js application providing another sample API endpoint.

![Architecture Diagram Placeholder]
(A diagram showing Nginx routing to index, app_py, and app_node, with webroot mounted to Nginx and index)



## Prerequisites

Before you begin, ensure you have the following installed:

*   **Docker:** [Install Docker](https://docs.docker.com/get-docker/)
*   **Docker Compose:** Docker Desktop usually includes Docker Compose. If not, [install Docker Compose](https://docs.docker.com/compose/install/)

## Installation and Setup

1.  **Create a `webroot` directory:**
    This directory will serve your static files and be indexed by the dynamic index service. Create it in your home directory or any other convenient location.
    ```bash
    mkdir -p ~/webroot
    mkdir -p ~/webroot/.webserver
    # You can place your HTML, CSS, JS, images, etc., here.
    # Example: echo "<h1>Hello from webroot!</h1>" > ~/webroot/index.html
    ```
    **Important:** The `docker-compose.yml` file is configured to mount `/Users/${USER}/webroot` into the containers. Ensure this path matches where you create your `webroot` directory. If your username is different or you prefer a different path, you'll need to edit `docker-compose.yml` accordingly.

2.  **Start the services:**
    Use the provided shell scripts to manage the services.
    *   `./up.sh`: Starts all services. If containers already exist, it just starts them.
    *   `./up-fresh.sh`: Rebuilds the Docker images and starts all services in detached mode. Use this when you've made changes to Dockerfiles or want a clean build.
    ```bash
    # To start the services for the first time or with a fresh build:
    ./up-fresh.sh
    ```
    This command will:
    This command will:
    *   Build the `app_py` Docker image.
    *   Pull the `nginx:1.27-alpine`, `node:24-alpine` images (if not present).
    *   Start all four services.


## Usage

Once the services are running, you can access the web server and APIs:

*   **Web Server (Static Files & File Browser):** Open your web browser and navigate to `http://localhost:7711`.
    *   If `~/webroot/index.html` exists it is served directly at `/`.
    *   The file browser is available at `http://localhost:7711/files`, providing a richer view of the same `~/webroot` content.
    *   Navigating into subdirectories works both through static file URLs and via the file browser interface.
    *   Manage reverse-proxy routes anytime at `http://localhost:7711/configure` (mirrors the file browser styling).

*   **Python API:** Access the sample endpoint at `http://localhost:7711/api/py/hello`.
    *   Expected response: `{"ok":true,"from":"python"}`

*   **Node.js API:** Access the sample endpoint at `http://localhost:7711/api/node/hello`.
    *   Expected response: `{"ok":true,"from":"node"}`
*   **Configure UI:** Visit `http://localhost:7711/configure` to add/edit proxy routes that map a public path (e.g., `/searxng`) to an upstream target (e.g., `http://host.docker.internal:8081`).

## Maintenance

*   **Stopping the services:**
    To stop all running Docker containers for this project, use the `down.sh` script:
    ```bash
    ./down.sh
    ```

*   **Viewing logs:**
    To view the logs of all services:
    ```bash
    docker-compose logs -f
    ```
    To view logs for a specific service (e.g., `index`):
    ```bash
    docker-compose logs -f index
    ```

*   **Rebuilding services:**
    If you make changes to the `Dockerfile`s or application code (`api.js`, `main.py`, etc.), you'll need to rebuild the images. The `up-fresh.sh` script is designed for this.

    ```bash
    ./up-fresh.sh
    ```

## Configuration

### `docker-compose.yml`

*   **Port Mapping:** To change the host port, modify `ports` under the `web` service:
    ```yaml
    ports:
      - "127.0.0.1:YOUR_PORT:80" # Change YOUR_PORT
    ```
*   **`webroot` Path:** If you created your `webroot` directory at a different location, update the `volumes` for `web` and `index` services:
    ```yaml
    volumes:
      - /path/to/your/webroot:/usr/share/nginx/html:ro
      - /path/to/your/webroot:/mnt/webroot:ro
      - /path/to/your/webroot/.webserver:/mnt/config
    ```
    Remember to replace `/path/to/your/webroot` with the actual absolute path.
*   **Index service environment:** The `index` service reads environment variables to locate volumes and gateway behavior:
    * `WEBROOT=/mnt/webroot` – where the file browser reads from (must match the volume).
    * `CONFIG_ROOT=/mnt/config` – where the endpoint config JSON is stored.
    * `HOST_DOCKER_GATEWAY=host.docker.internal` – loopback remap target so containers can reach `localhost` services on the host. Set to a custom gateway name or leave unset to use the default.

### `nginx/default.conf`

This file configures how Nginx routes requests.

*   **Static File Root:** The `root /usr/share/nginx/html;` directive specifies where Nginx looks for static files. This corresponds to your mounted `webroot`.
*   **API Endpoints:**
    *   `location /api/py/`: Routes requests to the Python FastAPI service (now on port 80).
    *   `location /api/node/`: Routes requests to the Node.js Express service.
    *   `location = /` returns `index.html` when present and only falls back to the file browser when no static landing page exists.
    *   `location /` and `location @dynamic_index`: Route requests for any other missing static asset to the Node.js file browser service.

    You can modify these `location` blocks to change API paths, add new proxy rules, or adjust caching headers. After modifying, you'll need to restart the `web` service:
    ```bash
    docker-compose restart web
    ```

### Routing Design Contracts

When adjusting routing or the index service, keep these invariants intact:

* **Static-first landing page:** `location = /` must continue to use `try_files /index.html @dynamic_index;`. Pointing `/` directly at the file browser will expose directory listings even when a curated landing page exists.
* **`/files` as the browser entry point:** The file browser treats `/files` as an alias for the webroot. Do not create a real `webroot/files` directory or change the alias path without updating the breadcrumb/link builder logic in `index/server.js`.
* **Fallback ordering matters:** The catch-all `location /` block must keep `try_files $uri @dynamic_index;` so that real assets (like the calculators and bingo app) are served by Nginx, while missing paths fall back to the browser. Reversing the order or adding additional rewrites ahead of this block can break static asset delivery.
* **Shared volume expectations:** Both Nginx and the index service read from the same `/Users/${USER}/webroot` mount. If you relocate the mount, update it for *both* services or the browser will list different content than Nginx serves.
* **Config persistence:** The `/configure` UI writes to `/mnt/config/endpoints.json`. Mount a host folder you trust (default: `~/webroot/.webserver`) so custom routes survive container rebuilds.

### Dynamic Endpoint Manager (`/configure`)

Use the built-in control panel at `http://localhost:7711/configure` to create or maintain reverse-proxy endpoints without editing Nginx.

* **Live editing:** Adds, edits, or toggles endpoints in place. Changes take effect on the very next request without restarts.
* **Path handling:** Each entry can strip or preserve the public prefix when forwarding traffic. This makes it easy to host apps that expect to live at `/` as well as those that are path-aware.
* **Validation rails:** Reserved prefixes like `/files`, `/configure`, `/api/py`, and `/api/node` are blocked to protect the built-in routes.
* **Persistence:** Configuration is saved as JSON under `~/webroot/.webserver/endpoints.json`, so version it or back it up like any other project asset.
* **Host access:** Targets that use `http://localhost` or `http://127.0.0.1` automatically resolve to `host.docker.internal` so containers can proxy to apps running on your host OS. Override this mapping by setting `HOST_DOCKER_GATEWAY` on the `index` service if your Docker host exposes a different gateway name.
* **Transparent proxying:** Common request bodies (including `application/x-www-form-urlencoded`) are streamed through without server-side parsing, preserving full POST/PUT behavior for upstream apps.
* **Sticky routing for absolute paths:** When an app served from `/your-alias` makes follow-up requests to absolute paths (e.g., `/search`) while `Strip path` is enabled, the proxy remembers the client for a short window (5 minutes per IP+User-Agent) and continues routing those requests to the same upstream.
* **Sticky routing:** When an app served from `/your-alias` makes follow-up requests to absolute paths (e.g., `/search`), the proxy remembers which alias the client last used (for 5 minutes per IP+agent) so later requests continue to route back to the same upstream even without the prefix.

> **Future opportunities:** Now that a UI and API exist, it's straightforward to add niceties such as per-route auth, health checks, or custom header overrides in a follow-up phase.

### `app_node_Dockerfile`

The `app_node_Dockerfile` is a standalone Dockerfile for the `app_node` service. It is not used in the `docker-compose.yml` setup, which defines the service directly. It can be used for building a standalone image of the `app_node` service.

## Extending and Customization

### Theming the Index

The dynamic index generated by the `index` service uses inline CSS with a modern, responsive design (dark-mode aware table layout, breadcrumb navigation, and metadata badges). To further customize it:

1.  **Modify `index/server.js`:**
    *   Locate the HTML template string within the `app.get('/*'` route.
    *   You can directly edit the `<style>` block or add links to external CSS files (which would need to be served from your `webroot` or another Nginx location).
    *   You could also introduce a templating engine (like EJS or Handlebars) to `index/server.js` for more complex theming, though this would require adding dependencies and modifying the Node.js application logic.

2.  **Rebuild and Restart `index` service:**
    After modifying `index/server.js`, you'll need to rebuild the `index` service image and restart it:
    ```bash
    docker-compose up -d --build index
    ```

### Adding New Backend Services

To add another backend service (e.g., a Ruby on Rails app, a Go API):

1.  **Create a new directory** for your service (e.g., `app_ruby/`).
2.  **Add a new service block** to `docker-compose.yml`, similar to `app_py` or `app_node`.
    *   Define its image, working directory, volumes, and `expose` port.
3.  **Update `nginx/default.conf`** to add a new `location` block that proxies requests to your new service's exposed port.
4.  **Run `./up.sh`** to bring up the new service and apply Nginx changes.

### Adding More Static Content

Simply place your HTML, CSS, JavaScript, images, and other static assets directly into your `webroot` directory. Nginx will serve them, and the `index` service will list them.

## Troubleshooting

*   **"Page not found" or Nginx 502 Bad Gateway:**
    *   Check if all Docker containers are running: `docker-compose ps`
    *   Check the logs for the relevant service (e.g., `web`, `index`, `app_py`, `app_node`) for errors: `docker-compose logs <service_name>`
    *   Ensure the `webroot` path in `docker-compose.yml` is correct and the directory exists on your host machine.
    *   Verify Nginx configuration syntax: `docker-compose exec web nginx -t`

*   **API endpoints not working:**
    *   Confirm the `proxy_pass` URLs in `nginx/default.conf` match the service names and exposed ports in `docker-compose.yml`.
    *   Check the logs of the specific API service (`app_py` or `app_node`) for application-level errors.
*   **Custom endpoint posts 404/Not found:**
    *   Ensure the endpoint in `/configure` is Enabled and uses the correct `Strip path` setting for your upstream.
    *   If your upstream emits absolute paths (e.g., redirects or forms posting to `/search`), keep `Strip path` on; the proxy will use sticky routing to forward those to the same upstream.
    *   If your upstream runs on the host and your target uses `http://localhost:PORT`, set `HOST_DOCKER_GATEWAY` if `host.docker.internal` is not available on your platform.
*   **Unsupported Media Type on form posts:** The proxy streams `application/x-www-form-urlencoded` bodies without parsing. If you still see 415 errors, clear caches and rebuild the `index` service to ensure it is up to date.

*   **Dynamic index not updating:**
    *   Ensure the `index` service is running.
    *   If you modified `index/server.js`, ensure you rebuilt and restarted the `index` service.
    *   Verify the `webroot` volume mount for the `index` service is correct.
