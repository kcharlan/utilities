# EditDB: World-Class SQLite Management

EditDB is a professional-grade, local web-based utility for managing SQLite databases. It combines the power of a Python backend with a high-performance, modern React-based frontend to deliver a "desktop-class" experience in your browser.

## 🚀 Quick Start (Global Utility)

EditDB is a **self-bootstrapping** utility. You don't need to manage virtual environments manually.

1. **Make it Global (Optional):**
   Link the script to your local bin to run it from anywhere:
   ```zsh
   ln -s "$(pwd)/editdb" /usr/local/bin/editdb
   ```

2. **Run:** Just launch it. On the first run, it will automatically set up its own hidden environment in `~/.editdb_venv`.
   ```zsh
   editdb data.sqlite
   ```

## 🍺 Homebrew & PEP 668 Friendly
Because macOS and Homebrew prevent global `pip` installs, EditDB handles its own dependencies in a private, isolated directory. This ensures:
- No "Externally Managed Environment" errors.
- No interference with your system Python.
- A "just works" experience like a Homebrew-installed binary.

## ✨ Key Features

- **Airtable-Style Data Grid:** A high-performance grid with sticky headers, and intuitive row editing. Optimized with combined API endpoints for sub-50ms table loading on localhost.
- **Advanced Schema Designer:** Add, rename, or delete columns and change data types. EditDB handles complex SQLite migrations (shadow-table pattern) automatically with transaction safety and mapping validation.
- **SQL Console:** A dedicated space for running raw SQL queries with history tracking (stored in localStorage).
- **Index Management:** Create and delete indexes with ease to optimize your query performance.
- **CLI-First Workflow:** Pass a database path directly via the terminal to open it instantly.
- **Zero-Build Frontend:** The UI is delivered as a single-file SPA using CDN-based React and Tailwind CSS, meaning no `node_modules` or complex build steps for you.

## 🔒 Security & Robustness

- **Localhost Only:** The server binds strictly to `127.0.0.1` to prevent unauthorized network access.
- **SQL Injection Protection:** All dynamic SQL identifiers (tables, columns, indexes) are validated and properly quoted.
- **Safe Migrations:** Structure changes use a shadow-table migration pattern wrapped in transactions. Column mappings are validated before execution to prevent data corruption.
- **Resource Limits:** Includes safeguards like CSV import size limits (50MB), query result truncation (10k rows), and connection timeouts.

## 🛠️ How It Works

### The Backend (FastAPI)
The backend is a lightweight Python server that provides:
- **REST API:** Endpoints for fetching schemas, rows, and executing migrations.
- **Shadow-Table Migrations:** Since SQLite's `ALTER TABLE` is limited, EditDB performs migrations by creating a temporary table, copying data, and swapping them—all within a safe transaction.
- **Auto-Browser Launch:** Automatically detects your OS and opens the default browser to the local server.

### The Frontend (React + Tailwind)
The UI is built with:
- **Tailwind CSS:** For a clean, modern aesthetic with native-feeling components.
- **Lucide Icons:** For crisp, recognizable interface elements.
- **Single-File Design:** For maximum portability, the entire frontend is embedded in the Python script.

## 🧑‍💻 Developer & Maintainer Notes

### Project Structure
- `editdb`: The unified entry point. Contains the FastAPI server, the CLI harness, and the embedded HTML/React frontend.
- `editdb_setup.sh`: Installation script for environment parity.

### Modifying the UI
The UI is embedded within the `HTML_TEMPLATE` constant at the bottom of the `editdb` file. This allows the utility to remain a "single-file" tool for easy portability while still delivering a complex web interface.

### Safety & Transactions
All schema changes are wrapped in SQLite transactions. If a migration fails during the data-copying phase, the changes are rolled back automatically to prevent data loss.

## ⚠️ Requirements
- Python 3.8+
- Automated setup of `fastapi`, `uvicorn`, `python-multipart` on first run.
- A modern web browser
