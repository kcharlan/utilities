# Local Web Server with Docker Compose

This project provides a versatile local web server environment orchestrated with Docker Compose. It features an Nginx reverse proxy, a dynamic directory listing service (Node.js), a Python FastAPI backend, and a Node.js Express backend. This setup is ideal for local development, testing various backend services, and serving static content with a browsable index.

## Architecture Overview

The web server is composed of several interconnected services:

*   **Nginx (`web` service):** Acts as the primary entry point, serving static files from a designated `webroot` directory and routing requests to the appropriate backend services.
*   **Dynamic Index (`index` service):** A Node.js application that generates a browsable directory listing for the `webroot` content, including inferred titles for HTML files.
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
    # You can place your HTML, CSS, JS, images, etc., here.
    # Example: echo "<h1>Hello from webroot!</h1>" > ~/webroot/index.html
    ```
    **Important:** The `docker-compose.yml` file is configured to mount `/Users/${USER}/webroot` into the containers. Ensure this path matches where you create your `webroot` directory. If your username is different or you prefer a different path, you'll need to edit `docker-compose.yml` accordingly.

2.  **Start the services:**
    Use the provided `up.sh` script to build the Docker images and start all services in detached mode.
    ```bash
    ./up.sh
    ```
    This command will:
    *   Build the `app_node` and `index` Docker images (if not already built or if changes are detected).
    *   Pull the `nginx:alpine` and `tiangolo/uvicorn-gunicorn-fastapi:python3.11` images.
    *   Start all four services.

## Usage

Once the services are running, you can access the web server and APIs:

*   **Web Server (Dynamic Index/Static Files):** Open your web browser and navigate to `http://localhost:7711`.
    *   You should see a dynamic listing of the contents of your `~/webroot` directory.
    *   If you place an `index.html` in `~/webroot`, it will be served directly.
    *   You can navigate into subdirectories within `~/webroot` through the dynamic index.

*   **Python API:** Access the sample endpoint at `http://localhost:7711/api/py/hello`.
    *   Expected response: `{"ok":true,"from":"python"}`

*   **Node.js API:** Access the sample endpoint at `http://localhost:7711/api/node/hello`.
    *   Expected response: `{"ok":true,"from":"node"}`

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
    If you make changes to the `Dockerfile`s or `package.json`/`api.js`/`main.py` files, you might need to rebuild the images. The `up.sh` script includes `--build`, so simply running `./up.sh` again will rebuild necessary images.

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
    ```
    Remember to replace `/path/to/your/webroot` with the actual absolute path.

### `nginx/default.conf`

This file configures how Nginx routes requests.

*   **Static File Root:** The `root /usr/share/nginx/html;` directive specifies where Nginx looks for static files. This corresponds to your mounted `webroot`.
*   **API Endpoints:**
    *   `location /api/py/`: Routes requests to the Python FastAPI service (now on port 80).
    *   `location /api/node/`: Routes requests to the Node.js Express service.
    *   `location /` and `location @dynamic_index`: Route requests for the root path and static file fallbacks to the Node.js dynamic index service.

    You can modify these `location` blocks to change API paths, add new proxy rules, or adjust caching headers. After modifying, you'll need to restart the `web` service:
    ```bash
    docker-compose restart web
    ```

### `app_node_Dockerfile`

The `app_node_Dockerfile` is a standalone Dockerfile for the `app_node` service. It is not used in the `docker-compose.yml` setup, which defines the service directly. It can be used for building a standalone image of the `app_node` service.

## Extending and Customization

### Theming the Index

The dynamic index generated by the `index` service uses inline CSS. To make it "prettier" or theme it:

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

*   **Dynamic index not updating:**
    *   Ensure the `index` service is running.
    *   If you modified `index/server.js`, ensure you rebuilt and restarted the `index` service.
    *   Verify the `webroot` volume mount for the `index` service is correct.
