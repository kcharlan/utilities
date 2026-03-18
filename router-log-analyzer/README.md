# Router Log Analyzer

`router_log_analyze.py` is a standalone NETGEAR router log analyzer with persistent SQLite-backed learning. It ingests PDF or plain-text log exports, tracks known devices and behavioral baselines over time, and flags anomalies such as unknown devices, timing drift, event spikes, and cluster gaps.

## Quick Start

The utility is intentionally portable. The main script is:

- [`router_log_analyze.py`](/Users/kevinharlan/source/utilities/router-log-analyzer/router_log_analyze.py)

Make it executable and put it somewhere on your `PATH`, for example `~/Library/Scripts`:

```zsh
chmod +x router_log_analyze.py
cp router_log_analyze.py ~/Library/Scripts/router_log_analyze.py
```

Or symlink it during development:

```zsh
ln -sf /Users/kevinharlan/source/utilities/router-log-analyzer/router_log_analyze.py ~/Library/Scripts/router_log_analyze.py
```

On the first real run, it bootstraps a private runtime under `~/.router-log-analyzer/` and installs its PDF parsing dependencies automatically.

## Requirements

- Python 3.11+
- `venv` and `pip`
- Network access on first run so it can install `PyMuPDF` and `pypdf`

## Baseline And Config

The analyzer requires an active baseline before normal log analysis can run. You can either import one ahead of time or pass a baseline JSON on the first analysis command.

If a `router-security-config.md` file lives next to the log file or baseline file, the script auto-detects and imports it unless you pass `--config` explicitly.

## Usage

Import a baseline:

```zsh
router_log_analyze.py --import-baseline baseline.json
```

Import a router access-control export:

```zsh
router_log_analyze.py --import-config router-security-config.md
```

Analyze a log after a baseline has already been imported:

```zsh
router_log_analyze.py router-log.pdf
```

Analyze a log and bootstrap the baseline in the same command:

```zsh
router_log_analyze.py router-log.pdf baseline.json
```

Write report files instead of console output:

```zsh
router_log_analyze.py router-log.pdf --report markdown,html,json --report-dir ./reports
```

## State Storage

All persistent state lives under `~/.router-log-analyzer/`:

- `bootstrap_state.json` - runtime refresh marker
- `network.db` - learned baseline, imported config, and analysis history
- `venv/` - private Python environment used for execution

## Notes

- The tool is self-contained and does not import local modules from this repo at runtime.
- Default output is a text report. `--report` can emit `markdown`, `html`, and `json` report files.
- `--help` and `--version` do not trigger runtime bootstrapping.
