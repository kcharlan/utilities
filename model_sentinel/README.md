# Model Sentinel

Model Sentinel is a local CLI utility for tracking model-list availability changes across LLM providers over time.

It fetches each configured provider's authenticated model-list endpoint, compares the current result to a saved baseline, reports additions/removals/metadata drift, and can persist snapshots for later history queries.

Provider identity is first-class. OpenRouter and Abacus.AI are tracked independently even when they expose similarly named upstream models.

## Status

The initial CLI implementation is in place.

Current scope:

- `scan` command with compare-only default behavior
- explicit `--save` baseline persistence
- SQLite-backed saved snapshots and change history
- `history` queries for a provider/model pair
- `providers` config inspection
- `healthcheck` runtime/config validation
- text, JSON, and Markdown output
- macOS notifications on changes or actionable errors
- bounded gzip log rotation

## Runtime Model

This implementation is stdlib-only at runtime. There is no third-party bootstrap dependency layer to install before the tool can run.

Repo-local usage:

```bash
cd model_sentinel
./model-sentinel --help
```

The shebang launcher is the simplest local entry point.

You can also run the module directly:

```bash
python3 -m model_sentinel --help
```

Why not `./model_sentinel`?

- the project directory itself is already named `model_sentinel`
- a filesystem path cannot be both that directory and an executable file
- `./model-sentinel` is the closest clean shebang-based form without renaming the project folder

## Configuration

Initialize the local config files with:

```bash
./setup.sh
```

Optional launchd automation files can be seeded with:

```bash
./setup_launchd.sh
```

The live config files are stored in the runtime home:

```text
~/.model_sentinel/providers.env
~/.model_sentinel/settings.env
```

`providers.env` defines which providers exist, whether they are enabled, which environment variable each provider uses for credentials, and how provider-returned pricing is converted into Model Sentinel's canonical unit of price per 1M tokens.

`settings.env` defines runtime behavior such as:

- log rotation size
- retained log generations
- notification defaults
- default report directory

Secrets do not belong in either file.

`setup.sh` is idempotent:

- it creates `~/.model_sentinel/providers.env` and `~/.model_sentinel/settings.env` from the templates if they do not exist
- it does not overwrite existing config files
- it prints the full paths you need to review and edit

After running setup:

1. review and edit `~/.model_sentinel/providers.env`
2. review and edit `~/.model_sentinel/settings.env`
3. start the secrets shell so the required credential env vars are present
4. run `./model-sentinel healthcheck`
5. create the first baseline with `./model-sentinel scan --save`

Each provider entry in `providers.env` must now include:

- `MODEL_SENTINEL_PROVIDER_<ID>_PRICE_MULTIPLIER`
- `MODEL_SENTINEL_PROVIDER_<ID>_PRICE_DIVISOR`

The conversion rule is:

```text
canonical_price = raw_provider_price * PRICE_MULTIPLIER / PRICE_DIVISOR
```

Example:

- OpenRouter raw per-token pricing: `1000000 / 1`
- Abacus raw per-1M-token pricing: `1 / 1`

## Required Credential Environment Variables

The initial providers expect:

- `OPENROUTER_AI_CREDS`
- `ABACUS_AI_CREDS`

If an enabled provider's credential environment variable is missing, the tool halts immediately and lists the missing variable names.

In your workflow that means the secrets shell alias must already have been invoked before running the utility or any automation around it.

## Commands

### Default Compare Run

With no subcommand, Model Sentinel behaves like `scan` in compare-only mode:

```bash
./model-sentinel
```

That will:

- fetch enabled providers
- compare against the previous saved baseline
- print a report to stdout
- not save a new snapshot

If no baseline exists yet, it prints a descriptive message telling you to create one explicitly.

### Save a Baseline

```bash
./model-sentinel scan --save
```

On the first save, the current results become the initial baseline. Later save runs persist new snapshots and record field-level changes relative to the selected baseline.

### Query History

```bash
./model-sentinel history --provider openrouter --model chatgpt-5.2
./model-sentinel history --provider openrouter --model chatgpt-5.2 --since 2025-01-01 --until 2025-12-31
```

`--since` and `--until` are inclusive and can be used together to bracket a date range.

### Inspect Configured Providers

```bash
./model-sentinel providers
```

This lists configured providers and useful status fields, including whether each credential env var is currently present.

### Validate Runtime Readiness

```bash
./model-sentinel healthcheck
```

This validates:

- `~/.model_sentinel/providers.env`
- `~/.model_sentinel/settings.env`
- enabled provider definitions
- required credential env vars
- runtime directories
- SQLite readiness

## Help

Built-in help is intended to be complete:

```bash
./model-sentinel --help
./model-sentinel scan --help
./model-sentinel history --help
./model-sentinel providers --help
./model-sentinel healthcheck --help
```

## launchd Automation

Model Sentinel includes a user-level `launchd` setup path for macOS.

Seed the runtime-home launchd files with:

```bash
./setup_launchd.sh
```

That creates or preserves:

```text
~/.model_sentinel/launchd.env
~/.model_sentinel/install_launchd.sh
```

Then:

1. edit `~/.model_sentinel/launchd.env` to source your secrets bootstrap or export the required credential env vars
2. edit `~/.model_sentinel/install_launchd.sh` if you want to change the schedule or command
3. run `~/.model_sentinel/install_launchd.sh install`

From then on, rerun the runtime-home installer after edits to reload the LaunchAgent.

If your secrets bootstrap changes `PATH`, make sure `python3` still resolves to the interpreter you use for manual runs. In this environment that meant exporting `/opt/homebrew/bin` before sourcing the secrets file.

See [`docs/LAUNCHD.md`](./docs/LAUNCHD.md) for the full flow.

## Logging

Logs are stored under:

```text
~/.model_sentinel/logs/
```

Rotation is controlled by `settings.env`:

- `MODEL_SENTINEL_LOG_MAX_BYTES`
- `MODEL_SENTINEL_LOG_KEEP_FILES`

The active log stays uncompressed. Rotated archives are kept as `.gz`.

## Notifications

Notifications are intentionally simple:

- no notification on clean no-change runs
- notify on detected changes or actionable errors
- include the report path in the notification message
- do not auto-open Finder or the report as a side effect of sending the notification
- if `terminal-notifier` is installed, notification clicks can open the configured file or folder target
- otherwise macOS falls back to a passive notification path without a reliable click-through action

When notifications fire and you did not explicitly supply `--output`, Model Sentinel writes a report into the configured report directory so the alert has a concrete artifact to point at.

## Testing

Run the project test suite from this directory:

```bash
pytest
```

## Documents

- [`docs/DESIGN.md`](./docs/DESIGN.md)
- [`docs/LAUNCHD.md`](./docs/LAUNCHD.md)
