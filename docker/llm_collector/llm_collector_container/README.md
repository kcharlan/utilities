# LLM Collector Container

This directory contains the Docker configuration for running the data collection server.

## Functionality

This Docker configuration uses Docker Compose to build and run the data collection server in a container. This is the recommended way to run the collector, as it simplifies deployment and ensures a consistent environment.

Python dependencies are installed at image build time from `collector/requirements.txt`. If you change collector dependencies, rebuild the image with `./up.sh` or `docker compose up --build -d`.

## Configuration

Before running the container, you need to configure the `docker-compose.yml` file:

1.  Run `../setup.sh` first. It writes `~/.config/llm_collector/secret.env` and generates `extension/config.local.js`.
2.  The project directory is still bind-mounted into the container for code.
3.  Runtime data is bind-mounted from the external `LLM_COLLECTOR_DATA_DIR` defined in `~/.config/llm_collector/secret.env`.

## Installation and Operation

Helper scripts are provided for convenience:

-   **`./up.sh`**: Loads the external config, then builds and starts the container in detached mode.
-   **`./down.sh`**: Stops and removes the container.

Or use Docker Compose directly:

1. **Build and start the container:**

   ```
   docker compose up --build -d
   ```

2. **View the logs:**

   ```
   docker compose logs -f
   ```

3. **Stop the container:**

   ```
   docker compose down
   ```

## Accessing the Data

Once the container is running, the collected data is stored in the `state.json` file in the root of the project. Snapshots of the data are stored in the `snapshots/` directory.

You can also access the collector's API endpoints directly:

*   **Counters:** `http://127.0.0.1:9000/counters` (requires `X-API-KEY` header)
*   **Reset:** `http://127.0.0.1:9000/reset` (requires `X-API-KEY` header)
