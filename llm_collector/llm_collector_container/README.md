# LLM Collector Container

This directory contains the Docker configuration for running the data collection server.

## Functionality

This Docker configuration uses `docker-compose` to build and run the data collection server in a container. This is the recommended way to run the collector, as it simplifies deployment and ensures a consistent environment.

## Installation and Operation

1. **Configure the API Key:**

   Before building and starting the container, you must set your API key in the `docker-compose.yml` file. Replace the placeholder `<your key here>` with your actual API key.

2. **Build and start the container:**

   ```
   docker-compose up --build -d
   ```

   This will build the Docker image (if it doesn't already exist) and start the container in detached mode.

3. **View the logs:**

   ```
   docker-compose logs -f
   ```

4. **Stop the container:**

   ```
   docker-compose down
   ```

## Configuration

The `docker-compose.yml` file is configured to:

*   Build the Docker image from the `Dockerfile` in this directory.
*   Mount the parent directory (`../`) into the container at `/app`. This allows the container to access the `collector`, `snapshots`, and `state.json` files.
*   Expose port 9000 on the host machine and map it to port 9000 in the container.
*   Set the `API_KEY` environment variable from the value in the `docker-compose.yml` file.
*   Set the container name to `llm_collector_container`.

## Accessing the Data

Once the container is running, the collected data is stored in the `state.json` file in the root of the project. Snapshots of the data are stored in the `snapshots/` directory.

You can also access the collector's API endpoints directly:

*   **Counters:** `http://127.0.0.1:9000/counters` (requires `X-API-KEY` header)
*   **Reset:** `http://127.0.0.1:9000/reset` (requires `X-API-KEY` header)