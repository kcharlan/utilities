# Dynamic Index Server (`index`)

This directory contains a Node.js application built with Fastify that provides a dynamic directory listing for the `webroot` content served by Nginx. It enhances the static file serving by offering a browsable interface with inferred titles for HTML files.

## Overview

*   **`server.js`**: The main application file, defining a Fastify server that scans a specified directory (`/mnt/webroot` within the container) and generates an HTML index page.
*   **`package.json`**: Defines project metadata and dependencies (Fastify, Cheerio).

## Functionality

The `index` service is responsible for:

1.  **Scanning `webroot`:** It reads the contents of the `/mnt/webroot` directory (which is mounted from your host's `~/webroot`).
2.  **Inferring Titles:** For HTML files, it attempts to extract the content of the `<title>` tag to provide a more descriptive link in the index.
3.  **Generating HTML Index:** It dynamically creates an HTML page listing directories and files, with links to navigate through the `webroot` structure.

This service runs on port `3000` within its Docker container and is accessed by Nginx for requests to the root path (`/`) or when static files are not found.

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `index` service is defined using the `node:20-alpine` image.
*   It mounts the `./index` directory into the container at `/srv`.
*   Crucially, it also mounts your host's `~/webroot` directory to `/mnt/webroot` inside the container, allowing the Node.js app to read its contents.
*   `npm install` is run to install dependencies, and then `node server.js` starts the server.
*   Port `3000` is exposed internally for Nginx to access.

## How to Modify and Extend

### Theming the Index

The dynamic index uses inline CSS and a basic HTML structure. To customize its appearance:

1.  **Edit `server.js`:**
    *   Locate the large HTML template string within the `app.get('/*'` route.
    *   You can directly modify the `<style>` block to change fonts, colors, layout, etc.
    *   For more advanced theming, you could:
        *   Add a link to an external CSS file. This CSS file would need to be placed in your `~/webroot` directory and referenced with a relative path (e.g., `<link rel="stylesheet" href="/styles.css"/>`).
        *   Introduce a templating engine (e.g., EJS, Handlebars) to `server.js` for cleaner separation of HTML and logic. This would require adding new dependencies to `package.json` and modifying the rendering logic.

2.  **Rebuild and Restart `index` service:**
    After making changes to `server.js` or `package.json`, you need to rebuild the `index` service to apply them:
    ```bash
    docker-compose up -d --build index
    ```

### Modifying Index Logic

*   **Change File/Directory Display:** You can modify the `scanDir` function in `server.js` to change how files and directories are filtered, sorted, or displayed.
*   **Add New Features:** For example, you could add search functionality, file upload capabilities (though this would require significant changes and security considerations), or different viewing modes.

## Dependencies

*   `fastify`: A fast and low-overhead web framework for Node.js.
*   `cheerio`: Used for parsing and manipulating HTML, specifically to infer titles from HTML files.
