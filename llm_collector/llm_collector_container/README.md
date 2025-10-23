# LLM Collector Container

This directory contains the Docker configuration for running the data collection server.

## Functionality

This Docker configuration uses `docker-compose` to build and run the data collection server in a container. This is the recommended way to run the collector, as it simplifies deployment and ensures a consistent environment.

## Configuration

Before running the container, you need to configure the `docker-compose.yml` file:

1.  **API Key**: The API key is set as an environment variable in `docker-compose.yml`. You should change the value of `API_KEY` to your own secret key. Make sure this key matches the one in `MY_API_KEY.txt` in the project root and in `extension/background.js`.

2.  **Project Directory**: The `docker-compose.yml` file mounts the project directory into the container using a relative path. No changes are needed for this.

## Installation and Operation

1. **Build and start the container:**
   
   ```
   docker-compose up --build -d
   ```
   
   This will build the Docker image (if it doesn't already exist) and start the container in detached mode.

2. **View the logs:**
   
   ```
   docker-compose logs -f
   ```

3. **Stop the container:**
   
   ```
   docker-compose down
   ```

## Accessing the Data

Once the container is running, the collected data is stored in the `state.json` file in the root of the project. Snapshots of the data are stored in the `snapshots/` directory.

You can also access the collector's API endpoints directly:

*   **Counters:** `http://127.0.0.1:9000/counters` (requires `X-API-KEY` header)
*   **Reset:** `http://127.0.0.1:9000/reset` (requires `X-API-KEY` header)
