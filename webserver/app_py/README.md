# Python FastAPI Application (`app_py`)

This directory contains a simple Python application built with FastAPI. It demonstrates a basic Python backend service that can be integrated into the main web server setup via Nginx.

## Overview

*   **`main.py`**: The main application file, defining a FastAPI application and a single API endpoint.

## Functionality

The `app_py` service exposes a single GET endpoint:

*   `GET /api/py/hello`
    *   **Description:** Returns a JSON object indicating the API is working and its origin.
    *   **Response:** `{"ok": True, "from": "python"}`

This service runs on port `80` within its Docker container and is exposed externally via the Nginx reverse proxy under the `/api/py/` path.

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `app_py` service uses the `tiangolo/uvicorn-gunicorn-fastapi:python3.11` Docker image, which is optimized for FastAPI deployments.
*   It mounts the `./app_py` directory into the container at `/app`.
*   Environment variables `MODULE_NAME` and `VARIABLE_NAME` are set to `main` and `app` respectively, to tell the Uvicorn/Gunicorn server how to load the FastAPI application.
*   Port `80` is exposed internally for Nginx to access.

## How to Modify and Extend

1.  **Add New Endpoints:**
    *   Edit `main.py` to add more routes and logic using FastAPI.
    *   Example:
        ```python
        @app.get("/api/py/new-endpoint")
        def new_endpoint():
            return {"message": "This is a new Python endpoint!"}
        ```

2.  **Add Dependencies:**
    *   If your new features require additional Python packages, you would typically add them to a `requirements.txt` file in this directory. The base image `tiangolo/uvicorn-gunicorn-fastapi` supports installing dependencies from `requirements.txt` if present.
    *   After adding dependencies, you might need to rebuild the `app_py` service:
        ```bash
        docker-compose up -d --build app_py
        ```

3.  **Rebuild and Restart:**
    After making changes to `main.py` or adding new dependencies, you need to restart the `app_py` service to apply them:
    ```bash
    docker-compose restart app_py
    ```
    If you added new dependencies, you might need to rebuild the image as well:
    ```bash
    docker-compose up -d --build app_py
    ```

4.  **Update Nginx (if necessary):**
    If you change the base path for your Python API (e.g., from `/api/py/` to `/my-python-app/`), you'll need to update the `nginx/default.conf` file accordingly and restart the `web` service:
    ```bash
    docker-compose restart web
    ```
