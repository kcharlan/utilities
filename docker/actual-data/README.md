# Actual Budget - Local Docker Setup

This directory hosts the Docker configuration and data for [Actual Budget](https://actualbudget.com/), a local-first personal finance application.

**⚠️ IMPORTANT:** This directory contains your live financial data. Back up the `server-files` and `user-files` directories regularly.

## Usage

The following helper scripts are available to manage the container:

-   **`./start.sh`**: Starts the Docker container in detached mode.
-   **`./run.sh`**: Starts the container (via `./start.sh`) and attempts to open the interface in your browser.
-   **`./stop.sh`**: Stops and removes the `actual` container.
-   **`./update.sh`**: Pulls the latest image, recreates the container, and mounts the existing data volume.

## Access

Once running, the application is accessible at: **[http://localhost:5006](http://localhost:5006)**

## Directory Structure

-   `server-files/`: Contains the server-side database (`account.sqlite`) and other system files.
-   `user-files/`: Contains your budget data blobs and sqlite databases. **Do not delete.**
-   `*.sh`: Management scripts described above.

## Configuration Details

-   **Container Name:** `actual`
-   **Image:** `actualbudget/actual-server:latest`
-   **Port:** `5006` (mapped to container port `5006`)
-   **Volume:** Maps this project directory (`docker/actual-data`) to `/data` inside the container.

---
*Note: This runs locally on your machine. Ensure this directory is included in your system backups.*
