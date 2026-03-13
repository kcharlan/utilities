# Model Sentinel Design

## 1. Purpose

Model Sentinel is a local CLI utility that tracks model-list changes across LLM providers over time.

The tool periodically fetches the authenticated provider model list, stores normalized snapshots, computes diffs, and reports changes relevant to compatibility tracking and provider drift monitoring.

Primary goals:

- detect newly added models
- detect removed models
- detect metadata changes on existing models
- preserve provider-specific visibility
- support historical queries for a provider/model pair

Non-goals for v1:

- proving invocation success by making follow-up model calls
- cross-provider canonical deduplication
- a web UI
- storing raw provider responses by default

## 2. Naming

Project name: `model_sentinel`

Rationale:

- "sentinel" clearly communicates watchfulness and periodic monitoring
- the name is distinctive without implying a web service
- it fits the intended CLI-first behavior

Provider/model visibility is explicit in the design and is not abstracted away by the name.

## 3. Source of Truth

For each enabled provider, the source of truth is the authenticated provider API response for the "list models" endpoint intended to enumerate models that can be selected for subsequent API calls.

Interpretation rules:

- if a model is present in that list, it is considered available for tracking purposes
- Model Sentinel does not attempt follow-up invocation to verify operational success
- the authenticated response is assumed to reflect the account's usable model set

## 4. Identity Model

Provider identity is a first-class dimension.

The unique model identity in v1 is:

- `provider_id`
- `provider_model_id`

Implications:

- the same apparent upstream model on two providers is stored as two independent tracked entities
- if a provider changes the model ID, the change is treated as `removed + added`
- display names are descriptive metadata, not identity keys

## 5. Storage Model

SQLite is the system of record.

Default runtime home:

```text
~/.model_sentinel/
  model_sentinel.db
  logs/
  debug/
```

Raw provider responses are not stored by default.

### 5.1 Logging

The implementation should keep local file logs with bounded rotation.

The defaults may be 10 MB and 3 total generations, but these must be configurable through an external runtime settings file rather than hardcoded.

Initial settings to expose:

- `MODEL_SENTINEL_LOG_MAX_BYTES`
- `MODEL_SENTINEL_LOG_KEEP_FILES`

Expected behavior:

- current active log remains uncompressed
- older rotated logs are compressed archives
- rotation and retention honor the configured values

Example shape when configured for 10 MB and 3 total files:

```text
~/.model_sentinel/logs/
  model_sentinel.log
  model_sentinel.log.1.gz
  model_sentinel.log.2.gz
```

When rotation occurs:

- `model_sentinel.log` rolls to a compressed archive
- only the configured number of archived generations are retained
- older archives are deleted automatically

The logging system must not grow unbounded over time.

Debug mode may optionally write response payloads to disk for schema drift diagnosis:

```text
~/.model_sentinel/debug/<timestamp>/<provider>.json
```

## 6. Snapshot Strategy

Each successful fetch creates an in-memory normalized snapshot. Persistence is explicit.

Default run behavior:

- fetch current provider data
- compare against the chosen baseline
- emit report
- do not save

If no baseline exists for a provider:

- report that no saved baseline exists
- do not silently treat the current fetch as the baseline
- provide explicit guidance on how to save one
- continue reporting other providers when possible

Explicit save behavior:

- fetch current provider data
- compare against the chosen baseline
- emit report
- persist the new snapshot as the latest successful state

This prevents accidental baseline contamination during repeated same-day scans.

## 7. Baseline and Comparison

Default baseline:

- previous successful scrape for the same provider

Planned alternate baselines:

- previous successful scrape from a prior calendar day
- exact saved scrape date lookup with nearest prior/subsequent suggestions when absent

Date lookup behavior should be operator-friendly:

- if the requested date exists, use it
- if it does not exist, explain that clearly
- also show the nearest prior and nearest subsequent available scrape dates when present

The baseline selector should operate per provider, since scrape timing may differ across providers.

### 7.1 First-run behavior

When a provider has no saved prior successful scrape, the tool should produce a descriptive first-run message.

Recommended behavior:

- identify the provider with no baseline
- state that compare-only mode has nothing persisted to compare against
- suggest an explicit baseline creation command
- exit non-zero only if that behavior is treated as operationally important by the final CLI contract

Suggested wording pattern:

```text
No saved baseline exists for provider 'openrouter'.
Run `model_sentinel scan --save` to create the initial baseline, then re-run compare mode.
```

If multiple providers are missing baselines, the report should list each one clearly.

## 8. Data Capture

Model Sentinel should capture as much model metadata as providers expose, while maintaining a stable minimal common model.

### 8.1 Common normalized fields

The normalized model record should include, when exposed:

- `provider_id`
- `provider_label`
- `provider_model_id`
- `display_name`
- `description`
- `model_family`
- `created_at` or provider-declared release timestamp
- `context_window`
- `max_output_tokens`
- `input_price`
- `output_price`
- `cache_read_price`
- `cache_write_price`
- `reasoning_supported`
- `tool_calling_supported`
- `vision_supported`
- `audio_supported`
- `image_supported`
- `structured_output_supported`
- `deprecated`
- `status`
- `metadata_json`

Price fields should be normalized at ingest into a canonical storage unit of price per 1M tokens.

Each provider config supplies:

- `PRICE_MULTIPLIER`
- `PRICE_DIVISOR`

Normalization rule:

```text
canonical_price = raw_provider_price * PRICE_MULTIPLIER / PRICE_DIVISOR
```

This keeps provider-specific unit handling out of the reporting layer.

### 8.2 Provider-specific metadata

Any provider fields without a dedicated normalized column should be preserved in `metadata_json`.

This supports:

- future reporting improvements without schema loss
- change detection for provider-specific fields
- flexible ingestion despite differing provider richness

## 9. Schema Outline

The exact schema can change during implementation, but the v1 design should resemble:

### 9.1 `providers`

One row per configured provider.

Suggested columns:

- `provider_id`
- `label`
- `kind`
- `base_url`
- `models_path`
- `credential_env_var`
- `enabled`
- `created_at`
- `updated_at`

### 9.2 `scrapes`

One row per fetch attempt.

Suggested columns:

- `scrape_id`
- `provider_id`
- `started_at`
- `completed_at`
- `status` (`success`, `error`)
- `baseline_mode`
- `baseline_scrape_id`
- `saved_snapshot` (`0` or `1`)
- `model_count`
- `error_message`

### 9.3 `snapshot_models`

One row per model observed in a persisted scrape.

Suggested columns:

- `scrape_id`
- `provider_id`
- `provider_model_id`
- normalized metadata columns
- `metadata_json`
- `first_seen_at`
- `last_seen_at`

### 9.4 `field_changes`

Optional but recommended for query performance and reporting.

One row per detected changed field between two scrapes.

Suggested columns:

- `change_id`
- `provider_id`
- `from_scrape_id`
- `to_scrape_id`
- `provider_model_id`
- `change_kind` (`added`, `removed`, `field_changed`)
- `field_name`
- `old_value_json`
- `new_value_json`
- `detected_at`

## 10. Diff Semantics

Change categories:

- `added`: model present in current snapshot, absent in baseline
- `removed`: model absent in current snapshot, present in baseline
- `field_changed`: model present in both, but one or more tracked fields differ

Change detection rules:

- compare normalized fields directly
- compare `metadata_json` as structured JSON, not raw string formatting
- treat `null` versus missing consistently after normalization
- preserve provider-specific field changes even when no common normalized field changed

## 11. Query Mode

V1 should include history queries over saved snapshots.

Primary use case:

- show the history of one provider/model pair over a selected time window

Example queries:

- show all changes to `openrouter / chatgpt-5.2` in the last year
- show current model inventory for `abacus`
- show first-seen and last-seen dates for a given model

Date-window semantics for history queries:

- `--since` is inclusive
- `--until` is inclusive
- using both options brackets an inclusive date range

Useful output forms:

- text table to stdout
- Markdown timeline
- JSON records for downstream analysis

## 12. Configuration Model

V1 should use two repo-local config files:

- `providers.env` derived from `providers.env.template`
- `settings.env` derived from `settings.env.template`

Reasons:

- minimal dependencies
- easy operator editing
- clear mapping between provider definitions and required secret env vars
- operational settings stay externalized and adjustable without code edits

Each provider definition should specify:

- provider enablement
- provider label
- provider kind
- base URL
- models path
- credential env var name

Secrets are not stored in `providers.env`.

The runtime settings file should define at least:

- log rotation size and retention
- default report directory
- notification defaults
- notification target behavior

At runtime, the tool should:

1. load provider definitions from `providers.env`
2. load runtime settings from `settings.env`
3. validate that required credential env vars are present for enabled providers
4. halt immediately with a clear message if any are missing

Initial credential env vars:

- `OPENROUTER_AI_CREDS`
- `ABACUS_AI_CREDS`

## 13. CLI Shape

The exact command names may still shift, but the behavior should look like this:

### 13.1 Default run

Default, switchless run:

```bash
model_sentinel
```

Behavior:

- fetch all enabled providers
- diff against baseline
- print text report
- do not save
- if no baseline exists, explain how to create one

### 13.2 Save run

Explicit persistence:

```bash
model_sentinel scan --save
```

Behavior:

- fetch all enabled providers
- diff against baseline
- print text report
- save the new snapshot
- if no prior baseline exists, this command creates the initial baseline explicitly

### 13.3 Format selection

Suggested report interface:

```bash
model_sentinel scan --format text
model_sentinel scan --format json
model_sentinel scan --format markdown
```

Optional file output:

```bash
model_sentinel scan --format markdown --output report.md
```

### 13.4 Baseline selection

Suggested baseline interface:

```bash
model_sentinel scan --baseline previous
model_sentinel scan --baseline previous-day
model_sentinel scan --baseline-date 2025-10-31
```

### 13.5 Query interface

Suggested history interface:

```bash
model_sentinel history --provider openrouter --model chatgpt-5.2
model_sentinel history --provider abacus --model gpt-4.1 --since 2025-01-01
```

### 13.6 Diagnostics

Suggested support commands:

```bash
model_sentinel providers
model_sentinel healthcheck
```

`providers` should list configured providers and their effective configuration summary, including:

- provider ID
- provider label
- provider kind
- enabled or disabled status
- base URL
- models path
- credential env var name
- whether the referenced credential env var is currently present

`healthcheck` should validate:

- `providers.env` presence
- `settings.env` presence
- enabled provider config completeness
- required secret env vars presence
- database/runtime path readiness

### 13.7 Help output

The CLI should provide detailed built-in help for both top-level and subcommands.

The help text should cover:

- what the default switchless run does
- that default mode is compare-only and non-persisting
- how to create the first baseline
- how to save subsequent snapshots intentionally
- how to query history for a provider/model pair
- how to request JSON or Markdown output
- how to select a baseline by mode or date
- how to target one provider or all enabled providers
- how notification behavior interacts with report generation
- how to inspect configured providers
- how to run configuration and runtime validation

A representative top-level help shape:

```text
usage: model_sentinel [-h] [--format {text,json,markdown}]
                      [--notify | --no-notify]
                      [--baseline {previous,previous-day}]
                      [--baseline-date YYYY-MM-DD]
                      [--provider PROVIDER_ID]
                      [--output PATH]
                      [command]

Track LLM provider model-list changes over time.

Default behavior:
  Fetch enabled providers, compare to a saved baseline, print a report,
  and do not save a new snapshot unless explicitly requested.

Commands:
  scan         Fetch provider model lists, compare, and optionally save
  history      Query saved history for one provider/model pair
  providers    List configured providers and their status
  healthcheck  Validate config, secrets, and runtime readiness

Examples:
  model_sentinel
      Compare current provider lists to the previous saved baseline.

  model_sentinel scan --save
      Fetch provider lists and save a new baseline snapshot.

  model_sentinel scan --provider openrouter --baseline-date 2025-10-31
      Compare current OpenRouter data to a saved baseline from that date, or
      show the nearest surrounding saved dates if none exists.

  model_sentinel history --provider openrouter --model chatgpt-5.2
      Show saved history for one provider/model pair.

  model_sentinel history --provider openrouter --model chatgpt-5.2 --since 2025-01-01 --format json
      Emit structured history records for downstream analysis.

  model_sentinel providers
      Show configured providers, enabled status, and secret env presence.

  model_sentinel healthcheck
      Validate configuration, credentials, and runtime paths.

  model_sentinel scan --format markdown --output report.md
      Write a Markdown comparison report to a file.

First run:
  If no baseline exists yet, run:
      model_sentinel scan --save

options:
  -h, --help                    show this help message and exit
  --format {text,json,markdown}
                                output format for scan or history output
  --notify                      send macOS notifications when changes or actionable
                                errors are detected
  --no-notify                   disable macOS notifications for this run
  --baseline {previous,previous-day}
                                baseline selection mode for comparison
  --baseline-date YYYY-MM-DD    compare against a saved scrape from this date;
                                if absent, show the nearest prior/subsequent dates
  --provider PROVIDER_ID        limit the run to one configured provider
  --output PATH                 write the generated report to a file
```

Representative subcommand help should also be explicit.

### 13.7.1 `scan --help`

```text
usage: model_sentinel scan [-h] [--save] [--format {text,json,markdown}]
                           [--notify | --no-notify]
                           [--baseline {previous,previous-day}]
                           [--baseline-date YYYY-MM-DD]
                           [--provider PROVIDER_ID]
                           [--output PATH]

Fetch provider model lists, compare them to a saved baseline, and report
changes. By default this command does not save a new snapshot.

examples:
  model_sentinel scan
      Compare all enabled providers against the previous saved baseline.

  model_sentinel scan --save
      Save a new snapshot after reporting differences.

  model_sentinel scan --provider abacus --save --format json --output abacus.json
      Save a new Abacus snapshot and write a JSON report.

  model_sentinel scan --baseline-date 2025-10-31
      Compare against a saved scrape from October 31, 2025, or show the nearest
      surrounding saved dates if none exists.

options:
  -h, --help                    show this help message and exit
  --save                        persist the fetched snapshot as a new baseline entry
  --format {text,json,markdown}
                                output format for the comparison report
  --notify                      enable macOS notifications for this run
  --no-notify                   disable macOS notifications for this run
  --baseline {previous,previous-day}
                                choose the baseline selection strategy
  --baseline-date YYYY-MM-DD    compare against a saved scrape from this date;
                                if absent, show the nearest prior/subsequent dates
  --provider PROVIDER_ID        limit the scan to one configured provider
  --output PATH                 write the report to a file
```

### 13.7.2 `history --help`

```text
usage: model_sentinel history [-h] --provider PROVIDER_ID --model MODEL_ID
                              [--since YYYY-MM-DD]
                              [--until YYYY-MM-DD]
                              [--format {text,json,markdown}]
                              [--output PATH]

Show saved model history for one provider/model pair.

examples:
  model_sentinel history --provider openrouter --model chatgpt-5.2
      Show the saved history for that model on OpenRouter.

  model_sentinel history --provider abacus --model gpt-4.1 --since 2025-01-01
      Show changes since January 1, 2025.

  model_sentinel history --provider openrouter --model chatgpt-5.2 --since 2025-01-01 --until 2025-12-31
      Show changes within the inclusive 2025 date range.

  model_sentinel history --provider openrouter --model chatgpt-5.2 --format markdown --output history.md
      Write a Markdown timeline to a file.

options:
  -h, --help                    show this help message and exit
  --provider PROVIDER_ID        configured provider ID to query
  --model MODEL_ID              provider-local model ID to query
  --since YYYY-MM-DD            restrict results to dates on or after this date
                                (inclusive)
  --until YYYY-MM-DD            restrict results to dates on or before this date
                                (inclusive)
  --format {text,json,markdown}
                                output format for history results
  --output PATH                 write the result to a file
```

### 13.7.3 `providers --help`

```text
usage: model_sentinel providers [-h] [--format {text,json,markdown}]

List configured providers and their effective configuration summary.

examples:
  model_sentinel providers
      Show configured providers and whether they are enabled.

  model_sentinel providers --format json
      Emit provider configuration summary as JSON.

options:
  -h, --help                    show this help message and exit
  --format {text,json,markdown}
                                output format for the provider summary
```

### 13.7.4 `healthcheck --help`

```text
usage: model_sentinel healthcheck [-h] [--format {text,json,markdown}]

Validate configuration, required credential environment variables, and
runtime readiness.

examples:
  model_sentinel healthcheck
      Run a human-readable readiness check.

  model_sentinel healthcheck --format json
      Emit structured validation results.

options:
  -h, --help                    show this help message and exit
  --format {text,json,markdown}
                                output format for validation results
```

## 14. Failure Handling

Expected failures:

- missing config file
- missing credential env var
- network timeout
- auth failure
- unexpected provider schema change
- empty or malformed model list

Expected behavior:

- fail fast on configuration and credential issues
- record scrape errors when a fetch starts but does not complete successfully
- make provider-specific errors explicit in output
- allow one provider failure to be reported without silently hiding another
- make missing-baseline situations descriptive and actionable rather than cryptic

If multiple providers are enabled, the final implementation should define whether partial success exits non-zero. The current recommendation is:

- exit non-zero if any enabled provider fails
- still print all available provider results before exiting

## 15. Reporting

The default report should prioritize operator usefulness over raw verbosity.

Recommended text sections:

- summary by provider
- added models
- removed models
- changed models with per-field diffs

Markdown and JSON outputs should contain the same information, not a degraded subset.

## 16. Open Questions

These items are intentionally left open until implementation starts:

- exact provider adapter API surface in code
- exact normalization rules for price and capability fields
- whether unsaved compare-only runs should be written to an ephemeral temp scrape table for debugging

### 16.1 macOS notifications

macOS notifications are in scope for v1, but they should stay intentionally simple.

Required behavior:

- do not notify on clean no-change runs
- notify only when changes are detected or an actionable error occurs
- include the generated report path in the notification text

Preferred behavior:

- clicking the notification opens the generated report file
- if direct file open is not supported reliably, open the containing folder instead

Operational rules:

- notification delivery failure must not fail the scrape itself
- text output and saved reports remain the primary source of detail
- if notifications are enabled and no explicit report path was requested, the tool should save a report artifact in the configured report directory so the notification can point somewhere concrete

## 17. Implementation Guidance

When implementation begins, it should follow repo conventions:

- self-bootstrapping single entry point
- targeted README instructions
- explicit failure messages
- SQLite-backed local state
- tests added alongside behavior, not afterward
