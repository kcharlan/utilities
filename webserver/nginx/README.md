# Nginx Configuration (`nginx`)

This directory contains the Nginx configuration files for the `web` service. Nginx acts as the reverse proxy and static file server for the entire web server setup.

## Overview

*   **`default.conf`**: The primary Nginx configuration file, defining server blocks, locations, and proxy rules.

## Functionality

The `default.conf` file configures Nginx to:

1.  **Listen on Port 80:** The Nginx server listens for incoming HTTP requests on port 80 (which is mapped to `localhost:7711` on your host machine).
2.  **Serve Static Files:** It serves static content directly from `/usr/share/nginx/html`, which is mounted from your host's `~/webroot` directory.
3.  **Cache Control:** Sets caching headers for common static assets (CSS, JS, images) to improve performance.
4.  **Reverse Proxy:** Routes requests to the appropriate backend services:
    *   **Dynamic Index:** Requests to the root path (`/`) or any path where a static file is not found are proxied to the `index` Node.js service (running on port `3000`).
    *   **Python API:** Requests to `/api/py/` are proxied to the `app_py` FastAPI service (running on port `80`).
    *   **Node.js API:** Requests to `/api/node/` are proxied to the `app_node` Express.js service (running on port `4000`).

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `web` service uses the `nginx:alpine` Docker image.
*   It mounts the `default.conf` file from this directory into the Nginx container at `/etc/nginx/conf.d/default.conf`, overriding the default Nginx configuration.
*   It also mounts your host's `~/webroot` directory to `/usr/share/nginx/html` inside the container, making your static files available to Nginx.

## How to Modify and Extend

### Modifying Nginx Configuration

To change how Nginx behaves, you will edit `default.conf`.

*   **Add New Proxy Rules:** To integrate new backend services, add new `location` blocks similar to those for `/api/py/` or `/api/node/`.
    *   Ensure the `proxy_pass` directive points to the correct service name and port as defined in `docker-compose.yml`.
*   **Adjust Caching:** Modify the `expires` and `Cache-Control` directives for static assets.
*   **Custom Error Pages:** You can configure custom error pages (e.g., `error_page 404 /404.html;`).
*   **HTTPS/SSL:** For production environments, you would configure SSL certificates here. This typically involves adding `listen 443 ssl;` and specifying `ssl_certificate` and `ssl_certificate_key` directives.

### Applying Changes

After modifying `default.conf`, you need to restart the Nginx `web` service for the changes to take effect:

```bash
docker-compose restart web
```

### Testing Nginx Configuration

Before restarting, you can test the syntax of your Nginx configuration to catch errors early:

```bash
docker-compose exec web nginx -t
```

This command will execute `nginx -t` inside the running `web` container, which checks the configuration file for syntax errors and then exits.
