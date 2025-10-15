# Collector

This directory contains the Python-based data collection server. It is responsible for receiving and storing LLM usage data from the browser extension.

## Functionality

The collector is a simple Flask server that receives usage data from the browser extension and stores it in a `state.json` file. The server is the single source of truth for all usage data.

## API Endpoints

The collector exposes the following endpoints:

*   `GET /health`: A health check endpoint that returns `{"ok": true}` if the server is running.
*   `GET /counters`: Returns the current usage counters. Requires a valid API key in the `X-API-KEY` header.
*   `GET /client_status?client_id=<client_id>`: Returns the status of a specific client, including the last sequence number received. Requires a valid API key in the `X-API-KEY` header.
*   `POST /add`: The main endpoint for submitting usage data. This endpoint is idempotent and uses a sequence number to prevent duplicate submissions. Requires a valid API key in the `X-API-KEY` header.
*   `POST /reset`: Resets all usage counters to zero and creates a snapshot of the current totals. Requires a valid API key in the `X-API-KEY` header.
*   `POST /flush`: Manually triggers a save of the current in-memory state to the `state.json` file. Requires a valid API key in the `X-API-KEY` header.

## API Data Format

The `/add` endpoint expects a JSON payload with the following structure:

```json
{
  "client_id": "<unique_client_id>",
  "seq": <sequence_number>,
  "deltas": {
    "<hostname>": <token_count>,
    ...
  },
  "ts": <timestamp_ms_epoch>
}
```

*   `client_id`: A unique identifier for the browser extension instance.
*   `seq`: A monotonically increasing sequence number for each request from a given client. This is used to ensure that requests are processed in order and to prevent duplicate processing of retried requests.
*   `deltas`: An object where the keys are hostnames (e.g., `"chat.openai.com"`) and the values are the number of tokens to add to the total for that host.
*   `ts`: An optional timestamp in milliseconds since the Unix epoch.

## State Management

The collector maintains its state in a file named `state.json` in the root of the project. This file stores the total token counts for each host and the last seen sequence number for each client.

Snapshots of the totals are saved to the `snapshots/` directory whenever the `/reset` endpoint is called. These snapshots can then be rolled up into `snapshots.csv` by the `rollup_snapshots.py` script for easier analysis.

## Configuration

### API Key

The collector server authenticates requests using an API key. This key must be provided by clients in the `X-API-KEY` header.

When running the collector, the API key is passed to the application via the `API_KEY` environment variable.

If you are running the server directly for development, you can set the environment variable in your shell:
```bash
export API_KEY="your_secret_api_key_here"
```

When running with Docker (the recommended method), the `API_KEY` is set in the `llm_collector_container/docker-compose.yml` file.

The `reset_collector.sh` script and the browser extension are also clients of this server. Ensure the API key is consistent across all components.

## Installation

1.  Install the required Python packages:
    ```
    pip install -r requirements.txt
    ```
2.  Set the `API_KEY` environment variable to your desired API key.
3.  Run the collector:
    ```
    python collector.py
    ```

## Running with Docker

For easier deployment, it is recommended to run the collector using the provided Docker configuration in the `llm_collector_container` directory.