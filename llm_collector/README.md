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

1.  **Configure the API Key:**
    *   Before launching the collector or extension, you must set an API key. This key is used to secure the communication between the browser extension and the collector server.
    *   Choose a strong, random string for your API key.
    *   Update the placeholder `<your key here>` in the following files:
        *   `llm_collector_container/docker-compose.yml`
        *   `extension/background.js`
        *   `MY_API_KEY.txt`
        *   `reset_collector.sh`

2.  **Start the collector:**
    *   Navigate to the `llm_collector_container` directory.
    *   Run `docker-compose --build up -d` to start the data collection server in the background.

3.  **Install the extension:**
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