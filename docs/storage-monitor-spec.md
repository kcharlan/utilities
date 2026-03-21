# Storage Monitor Utility Spec

## Goal

Build a local-first storage audit and cleanup utility that launches, performs a full storage scan automatically, presents findings graphically in a React SPA, and lets the user selectively launch safe cleanup/remediation actions.

Working name for now: `storage_monitor`.

## Recommended Delivery Form

Use the repository's self-bootstrapping local-web-app pattern:

- Python backend
- FastAPI + uvicorn
- embedded React SPA served from `/`
- runtime home under `~/.storage_monitor/`

Because this tool will likely grow beyond a trivial script, the best medium-term target is:

- multi-file Python app
- packaged as a single executable zipapp if/when distribution convenience matters

For first implementation, a normal multi-file project directory inside `~/source/utilities/storage_monitor/` is the most pragmatic starting point.

## Product Requirements

### On launch

Run the full scan automatically and stream progress to the UI.

Required launch-time probes:

1. APFS container and volume accounting.
2. Local snapshot inventory.
3. Visible live-data vs APFS-reported usage delta.
4. Top-level directory breakdown for:
   - Data volume
   - home directory
   - `~/Library`
5. Targeted category scans:
   - caches
   - application support
   - containers
   - group containers
   - model stores
   - downloads
   - large user files
6. Heuristic scans:
   - sparse files
   - cloud/file-provider placeholders
   - stale installer/update residues
   - duplicate-looking large files

### UI expectations

The initial dashboard should answer:

- Where is disk space actually going?
- How much is live user data versus snapshots/purgeable/system-managed?
- Which items are safe to remove?
- Which items are large but expected?
- Which cleanup actions are available right now?

## UX Structure

### 1. Overview

Cards:

- total container size
- used
- free
- purgeable/inferred reclaimable
- visible live data
- hidden/system-managed delta
- snapshot count
- candidate reclaim total

Charts:

- stacked bar: container usage by class
- treemap: top live-data directories
- donut: reclaimable categories

### 2. Findings

Table of findings with:

- label
- path
- class
- apparent size
- allocated size
- confidence
- risk level
- recommended action

Filter chips:

- `Safe cache purge`
- `Snapshot overhead`
- `Review manually`
- `App/runtime payload`
- `Likely stale`
- `Cloud placeholder`

### 3. Cleanup Actions

Action cards with:

- estimated reclaim size
- risk summary
- prerequisites
- dry-run output
- execute button

Examples:

- thin local snapshots
- clear Homebrew downloads
- clear pip cache
- clear npm cache
- clear Playwright cache
- clear browser/app caches
- delete stale Docker installer staging
- remove selected local models
- open folder in Finder

### 4. History

Persist scan results so the user can see:

- last scan summary
- trend over time
- cleanup actions performed
- before/after reclaimed space

## Backend Architecture

Suggested package layout:

```text
storage_monitor/
  README.md
  launcher.py
  app/
    __init__.py
    api.py
    server.py
    models.py
    settings.py
    storage/
      apfs.py
      du.py
      snapshots.py
      large_files.py
      sparse.py
      cloud_files.py
      caches.py
      models.py
      heuristics.py
    cleanup/
      actions.py
      snapshots.py
      caches.py
      docker.py
      models.py
    persistence/
      db.py
      scans.py
      actions.py
    ui/
      index_html.py
```

## Backend Data Model

Core entities:

### `ScanRun`

- `id`
- `started_at`
- `completed_at`
- `status`
- `host`
- `os_version`

### `ProbeResult`

- `probe_name`
- `status`
- `duration_ms`
- `raw_json`
- `warnings`

### `StorageEntity`

- `entity_id`
- `path`
- `label`
- `kind`
- `owner_scope`
- `apparent_bytes`
- `allocated_bytes`
- `reclaimable_bytes_estimate`
- `risk_level`
- `confidence`
- `tags`

### `CleanupAction`

- `action_id`
- `kind`
- `label`
- `target_selector`
- `estimated_reclaim_bytes`
- `requires_confirmation`
- `dry_run_supported`
- `command_preview`

### `ActionRun`

- `id`
- `action_id`
- `started_at`
- `completed_at`
- `status`
- `stdout_tail`
- `stderr_tail`
- `bytes_reclaimed`

## Probe Inventory

### APFS probes

- `diskutil apfs list`
- `diskutil info /`
- `diskutil info /System/Volumes/Data`
- `diskutil apfs listSnapshots /System/Volumes/Data`
- `tmutil listlocalsnapshots /`

Derived metrics:

- visible live data
- APFS-reported Data usage
- inferred snapshot/system-managed delta
- snapshot count
- oldest snapshot age

### Filesystem probes

- `du` top-level breakdowns
- targeted `du` scans for known heavy buckets
- `find` large-file scan
- `stat` for apparent vs allocated size

### Heuristic probes

- cache detector by known path patterns
- model detector:
  - `~/.lmstudio`
  - `~/.ollama`
  - Whisper caches
- stale installer detector:
  - Docker
  - app updater staging paths
- file-provider detector:
  - OneDrive
  - iCloud/CloudStorage paths

## Safety Model

Every cleanup action needs a risk tier:

- `low`: caches/download residues, dry-run by default
- `medium`: app-managed runtime payloads that can be regenerated
- `high`: user data, media, exports, project trees

Rules:

- default to dry-run preview where possible
- require explicit confirmation for medium/high actions
- show exact paths before execution
- log all actions to the local database
- never auto-delete user files on launch

## Technical Notes

### Apparent vs allocated size

This utility must record both.

Examples from the audit:

- `Docker.raw`
  - apparent size: `32 GB`
  - allocated size: `2.9 GB`
- OneDrive file-provider paths can show multi-GB metadata size while consuming `0 B` locally

If the tool only reports apparent size, it will produce misleading results.

### Scan execution model

Use background worker tasks with progress streaming:

- initial scan phases
- phase timing
- partial results as each probe completes

SSE is sufficient and consistent with other utilities in the repo.

### Persistence

Use SQLite under `~/.storage_monitor/`.

Persist:

- scan history
- finding snapshots
- cleanup history
- per-path trend data for recurring large buckets

## First Iteration Scope

Ship v1 with:

1. APFS accounting and snapshot detection.
2. Top-level `du` scans.
3. Large-file inventory.
4. Known-cache inventory.
5. A findings dashboard with charts and filters.
6. A small set of cleanup actions:
   - snapshot thinning
   - cache purges
   - open-in-Finder
   - reveal path in Terminal/Finder

Defer to later:

- duplicate-file content hashing at scale
- background scheduled scans via `launchd`
- smart cleanup recommendations based on historical drift
- notification/tray integration

## Candidate README Positioning

Suggested project summary:

`storage_monitor` is a local-first macOS disk-usage and cleanup console. It scans APFS volumes, local snapshots, caches, app data, model stores, and large user files, then presents the results in a React dashboard with graphical breakdowns, reclaim estimates, and explicit cleanup actions. It is self-bootstrapping, localhost-only, and stores scan history under `~/.storage_monitor/`.
