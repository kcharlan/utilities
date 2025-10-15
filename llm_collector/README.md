# LLM Usage Collector

This project is designed to collect and track usage data for Large Language Models (LLMs). It consists of a web browser extension, a data collection server, and a Docker container to run the server.

## Purpose

The primary purpose of this tool is to provide a self-hosted solution for tracking your own LLM usage across different web-based interfaces. This can be useful for:

*   Understanding your own usage patterns.
*   Cost analysis if you are using paid LLM services.
*   Research on LLM usage.

## Folder Structure

*   `collector/`: Contains the Python-based data collection server.
*   `extension/`: Contains the browser extension that captures LLM usage data.
*   `llm_collector_container/`: Contains the Docker configuration for running the collection server.
*   `snapshots/`: Contains snapshots of the collected usage data.

## Quick Start

Before you can run this project, you need to perform the following configuration steps:

1.  **Configure Paths**:
    *   In `reset_collector.sh`, set the `BASE_DIR` variable to the absolute path of the `llm_collector` project on your computer.
    *   In `llm_collector_container/docker-compose.yml`, update the volume mount path to the absolute path of the `llm_collector` project on your computer.

2.  **Configure the API Key**:
    *   Create a file named `MY_API_KEY.txt` in the root directory of this project and enter a secret key of your choice.
    *   In `llm_collector_container/docker-compose.yml`, update the `API_KEY` environment variable to match the key you put in `MY_API_KEY.txt`.
    *   In `extension/background.js`, update the `API_KEY` variable to match the key you put in `MY_API_KEY.txt`.

3.  **Start the collector:**
    *   Navigate to the `llm_collector_container` directory.
    *   Run `docker-compose --build up -d` to start the data collection server in the background.

4.  **Install the extension:**
    *   Open your web browser's extension management page.
    *   Enable "Developer mode".
    *   Click "Load unpacked" and select the `extension` directory.

## Usage

Once the collector and extension are running, the extension will automatically track your LLM usage in the browser. To view the collected data, you can access the following endpoints on the collector server:

*   **Counters:** `http://127.0.0.1:9000/counters` (requires `X-API-KEY` header)
*   **Reset:** `http://127.0.0.1:9000/reset` (requires `X-API-KEY` header)

The `reset_collector.sh` script is provided to reset the usage counters. It is configured to run at midnight.

## Contributing

Contributions are welcome! Please feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
