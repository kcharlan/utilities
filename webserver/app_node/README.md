# Node.js Express API (`app_node`)

This directory contains a simple Node.js application built with Express.js. It serves as a basic example of a backend service that can be integrated into the main web server setup via Nginx.

## Overview

*   **`api.js`**: The main application file, defining an Express server and a single API endpoint.
*   **`package.json`**: Defines project metadata and dependencies (Express.js).

## Functionality

The `app_node` service exposes a single GET endpoint:

*   `GET /api/node/hello`
    *   **Description:** Returns a JSON object indicating the API is working and its origin.
    *   **Response:** `{"ok": true, "from": "node"}`

This service runs on port `4000` within its Docker container and is exposed externally via the Nginx reverse proxy under the `/api/node/` path.

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `app_node` service is defined using the `node:20-alpine` image.
*   It mounts the `./app_node` directory into the container at `/srv`.
*   `npm install` is run to install dependencies, and then `node api.js` starts the server.
*   Port `4000` is exposed internally for Nginx to access.

## How to Modify and Extend

1.  **Add New Endpoints:**
    *   Edit `api.js` to add more routes and logic using Express.js.
    *   Example:
        ```javascript
        app.get('/api/node/new-endpoint', (req, res) => {
          res.json({ message: 'This is a new endpoint!' });
        });
        ```

2.  **Add Dependencies:**
    *   If your new features require additional Node.js packages, add them to `package.json` under `dependencies`.
    *   Example:
        ```json
        "dependencies": {
          "express": "^4.19.2",
          "new-package": "^1.0.0"
        }
        ```

3.  **Rebuild and Restart:**
    After making changes to `api.js` or `package.json`, you need to rebuild the `app_node` service to apply them:
    ```bash
    docker-compose up -d --build app_node
    ```

4.  **Update Nginx (if necessary):**
    If you change the base path for your Node.js API (e.g., from `/api/node/` to `/my-node-app/`), you'll need to update the `nginx/default.conf` file accordingly and restart the `web` service:
    ```bash
    docker-compose restart web
    ```
