# Storage Monitor UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Storage Monitor UI into a dense, dark-mode-capable dashboard with treemap+accordion breakdowns, progressive scan streaming, and a dedicated snapshot manager.

**Architecture:** Single-file self-bootstrapping Python app (`storage_monitor`, ~2155 lines). Backend is FastAPI with SSE. Frontend is an embedded React 18 SPA loaded via CDN (React, Babel Standalone, Tailwind, Lucide). All changes stay within this single file. Backend changes add granular SSE events, new API endpoints, and restructured report data. Frontend is a full HTML template rewrite.

**Tech Stack:** Python 3 / FastAPI / uvicorn (backend), React 18 / Tailwind CSS / Lucide Icons via CDN (frontend), SSE for real-time updates.

**Design Spec:** `docs/superpowers/specs/2025-07-19-ui-redesign-design.md`

**Validation commands:**
```bash
./storage_monitor --help
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473
# Then in another terminal:
curl -s http://127.0.0.1:8473/api/state | python3 -m json.tool
curl -s http://127.0.0.1:8473/api/breakdown?path=$HOME | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8473/api/refresh-metadata | python3 -m json.tool
```

---

## Task 1: Backend — Report Structure Changes & Scan Progress Simplification

**Context:** The current report mixes snapshots into `findings`. The scan status includes jumpy `completed_in_phase`/`total_in_phase` counters. This task restructures the report and simplifies progress tracking.

**File:** `storage_monitor` (lines 373-398 for AppState, lines 935-1250 for collect_scan_report, lines 1260-1320 for scan thread/start)

- [ ] **Step 1: Simplify AppState.scan_status initialization**

In class `AppState.__init__` (line 374), remove `phase_progress`, `completed_in_phase`, `total_in_phase` from `scan_status` dict. Keep: `running`, `phase`, `detail`, `started_at`, `updated_at`, `progress`, `error`.

```python
self.scan_status: Dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "detail": "Idle",
    "started_at": None,
    "updated_at": iso_now(),
    "progress": 0.0,
    "error": None,
}
```

- [ ] **Step 2: Simplify set_phase_progress**

In `collect_scan_report` (line 951), simplify `set_phase_progress` to only set `progress` (no `phase_progress`, `completed_in_phase`, `total_in_phase`):

```python
def set_phase_progress(phase_name: str, completed: int, total: int, detail: str) -> None:
    phase_weight = dict(phases)[phase_name]
    phase_ratio = 1.0 if total <= 0 else max(0.0, min(1.0, completed / total))
    progress = phase_offsets[phase_name] + (phase_weight * phase_ratio)
    set_scan_status(
        running=True,
        phase=phase_name,
        detail=detail,
        progress=progress,
        error=None,
    )
```

- [ ] **Step 3: Update run_scan_thread idle/error status dicts**

In `run_scan_thread` (lines 1266-1297), remove `phase_progress`, `completed_in_phase`, `total_in_phase` from both the success and error status dicts:

Success (line 1266):
```python
STATE.scan_status = {
    "running": False,
    "phase": "idle",
    "detail": "Idle",
    "started_at": None,
    "updated_at": iso_now(),
    "progress": 1.0,
    "error": None,
}
```

Error (line 1284):
```python
STATE.scan_status = {
    "running": False,
    "phase": "error",
    "detail": str(exc),
    "started_at": None,
    "updated_at": iso_now(),
    "progress": 0.0,
    "error": str(exc),
}
```

- [ ] **Step 4: Update start_scan status dict**

In `start_scan` (line 1304), remove the three fields:

```python
STATE.scan_status = {
    "running": True,
    "phase": "initializing",
    "detail": "Preparing task graph",
    "started_at": iso_now(),
    "updated_at": iso_now(),
    "progress": 0.0,
    "error": None,
}
```

- [ ] **Step 5: Add per-section timestamps to report and separate snapshots**

In `collect_scan_report`, at the report assembly section (around line 1219), modify the report dict to:
1. Add `updated_at` to each breakdown entry
2. Add `updated_at` to `findings`, `large_files`
3. Create a new top-level `snapshots` array (pulled out of findings)
4. Remove snapshot findings from the `findings` list

Replace the report construction (lines 1219-1248) with:

```python
now = iso_now()

# Build snapshots as separate top-level array
snapshots = []
for name in snapshot_names:
    token = parse_snapshot_token(name)
    if token is None:
        continue
    # Parse date from token: "YYYY-MM-DD-HHMMSS"
    try:
        parsed_date = datetime.strptime(token, "%Y-%m-%d-%H%M%S").replace(
            tzinfo=timezone.utc
        ).isoformat()
    except ValueError:
        parsed_date = None
    action_token = encode_action_token(
        {"kind": "delete_snapshot", "snapshot_name": name, "token": token}
    )
    snapshots.append({
        "snapshot_name": name,
        "parsed_date": parsed_date,
        "token": token,
        "action_token": action_token,
    })

# Build findings WITHOUT snapshots (only watchlist + large files)
findings: List[Dict[str, Any]] = []
for item in watchlist:
    if item["exists"]:
        findings.append({
            "label": item["label"],
            "path": item["path"],
            "category": item["category"],
            "risk": item["risk"],
            "description": item["description"],
            "apparent_bytes": item["apparent_bytes"],
            "allocated_bytes": item["allocated_bytes"],
            "estimated_reclaim_bytes": item["estimated_reclaim_bytes"],
            "actionable": item["actionable"],
            "cleanup_kind": item["cleanup_kind"],
            "action_token": item["action_token"],
        })
findings.extend(large_files)
findings.sort(
    key=lambda item: (
        bytes_or_zero(item.get("estimated_reclaim_bytes"))
        or bytes_or_zero(item.get("allocated_bytes")),
    ),
    reverse=True,
)
findings = findings[:MAX_FINDINGS]
for finding in findings:
    finding["actions"] = build_finding_actions(finding)

# Reclaimable sums (only from findings, snapshots don't have sizes)
safe_reclaimable_bytes = sum(
    bytes_or_zero(item.get("estimated_reclaim_bytes"))
    for item in findings
    if item.get("risk") == "low" and item.get("actionable")
)
medium_reclaimable_bytes = sum(
    bytes_or_zero(item.get("estimated_reclaim_bytes"))
    for item in findings
    if item.get("risk") == "medium" and item.get("actionable")
)

report = {
    "version": VERSION,
    "generated_at": now,
    "started_at": started_at,
    "warnings": warnings,
    "summary": {
        "container_size_bytes": apfs_container["container_size_bytes"] or data_volume["disk_size_bytes"],
        "container_used_bytes": apfs_container["container_used_bytes"],
        "container_free_bytes": data_volume["container_free_bytes"],
        "data_volume_used_bytes": data_volume["volume_used_bytes"],
        "system_volume_used_bytes": system_volume["volume_used_bytes"],
        "visible_data_bytes": visible_data_bytes,
        "hidden_delta_bytes": hidden_delta_bytes,
        "home_total_bytes": home_total_bytes,
        "applications_total_bytes": applications_total_bytes,
        "snapshot_count": len(snapshots),
        "safe_reclaimable_bytes": safe_reclaimable_bytes,
        "medium_reclaimable_bytes": medium_reclaimable_bytes,
    },
    "breakdowns": {
        "data_root": {"items": data_breakdown, "total_bytes": visible_data_bytes, "updated_at": now},
        "home_root": {"items": home_breakdown, "total_bytes": home_total_bytes, "updated_at": now},
        "library_root": {"items": library_breakdown, "total_bytes": library_breakdown_result["total_bytes"], "updated_at": now},
        "applications_root": {"items": applications_breakdown, "total_bytes": applications_total_bytes, "updated_at": now},
    },
    "watchlist": watchlist,
    "large_files": {"items": large_files, "updated_at": now},
    "findings": {"items": findings, "updated_at": now},
    "snapshots": {"items": snapshots, "updated_at": now},
    "checks": summarize_checks(checks),
}
```

Note: This changes the shape of `breakdowns`, `large_files`, `findings`, and adds `snapshots`. Each is now `{items: [...], updated_at: ...}` instead of a bare list. The frontend will be rewritten to consume this shape.

- [ ] **Step 6: Update resolve_action to check both findings and snapshots**

In `resolve_action` (line 1323), update to check action tokens from both findings and snapshots:

```python
def resolve_action(action_token: str) -> Dict[str, Any]:
    try:
        payload = decode_action_token(action_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid action token: {exc}") from exc
    with STATE.lock:
        report = STATE.report
    if report is None:
        raise HTTPException(status_code=400, detail="No scan report is loaded yet.")
    allowed_tokens = set()
    for finding in report.get("findings", {}).get("items", []):
        if finding.get("action_token"):
            allowed_tokens.add(finding["action_token"])
    for snapshot in report.get("snapshots", {}).get("items", []):
        if snapshot.get("action_token"):
            allowed_tokens.add(snapshot["action_token"])
    if action_token not in allowed_tokens:
        raise HTTPException(status_code=400, detail="Action token is not present in the latest report.")
    return payload
```

- [ ] **Step 7: Remove build_snapshot_findings function**

Delete the `build_snapshot_findings` function (lines 867-892) — snapshots are now built inline in `collect_scan_report` with the new structure. Also remove the `snapshot_findings = build_snapshot_findings(snapshot_names)` call and `findings.extend(snapshot_findings)` line from `collect_scan_report`.

- [ ] **Step 8: Smoke test**

```bash
./storage_monitor --help
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473 &
sleep 8
# Verify report structure
curl -s http://127.0.0.1:8473/api/state | python3 -c "
import sys, json
data = json.load(sys.stdin)
r = data['report']
# Check new structure
assert 'snapshots' in r, 'missing snapshots'
assert 'items' in r['snapshots'], 'snapshots missing items'
assert 'updated_at' in r['snapshots'], 'snapshots missing updated_at'
assert 'items' in r['findings'], 'findings missing items wrapper'
assert 'updated_at' in r['findings'], 'findings missing updated_at'
assert 'items' in r['large_files'], 'large_files missing items wrapper'
for key in r['breakdowns']:
    bd = r['breakdowns'][key]
    assert 'items' in bd, f'{key} missing items'
    assert 'updated_at' in bd, f'{key} missing updated_at'
    assert 'total_bytes' in bd, f'{key} missing total_bytes'
# Check scan_status simplified
ss = data['scan_status']
assert 'completed_in_phase' not in ss, 'completed_in_phase should be removed'
assert 'total_in_phase' not in ss, 'total_in_phase should be removed'
assert 'phase_progress' not in ss, 'phase_progress should be removed'
# Check no snapshots in findings
for f in r['findings']['items']:
    assert f.get('category') != 'snapshot', 'snapshot found in findings'
print('All structure checks passed')
"
kill %1 2>/dev/null
```

- [ ] **Step 9: Commit**

```bash
git add storage_monitor
git commit -m "Restructure report: separate snapshots, per-section timestamps, simplify scan progress"
```

---

## Task 2: Backend — New API Endpoints

**Context:** The frontend needs on-demand directory drill-down and lightweight metadata refresh after actions.

**File:** `storage_monitor` (add endpoints near the existing API section, lines 1400-1457)

- [ ] **Step 1: Add collect_metadata helper**

Add a new function after `reveal_path` (around line 1399) that runs only the diskutil probes:

```python
def collect_metadata() -> Dict[str, Any]:
    """Run only diskutil probes and return container/volume stats."""
    results = run_parallel_call_map({
        "apfs_list": lambda: run_command(["diskutil", "apfs", "list"], timeout=120),
        "data_info": lambda: run_command(["diskutil", "info", str(DATA_VOLUME)], timeout=120),
        "root_info": lambda: run_command(["diskutil", "info", "/"], timeout=120),
    })
    apfs = parse_apfs_list(results["apfs_list"]["stdout"] if results["apfs_list"]["ok"] else "")
    data_vol = parse_diskutil_info(results["data_info"]["stdout"] if results["data_info"]["ok"] else "")
    sys_vol = parse_diskutil_info(results["root_info"]["stdout"] if results["root_info"]["ok"] else "")
    return {
        "container_size_bytes": apfs["container_size_bytes"] or data_vol["disk_size_bytes"],
        "container_used_bytes": apfs["container_used_bytes"],
        "container_free_bytes": data_vol["container_free_bytes"],
        "data_volume_used_bytes": data_vol["volume_used_bytes"],
        "system_volume_used_bytes": sys_vol["volume_used_bytes"],
        "updated_at": iso_now(),
    }
```

- [ ] **Step 2: Add POST /api/refresh-metadata endpoint**

```python
@app.post("/api/refresh-metadata")
def api_refresh_metadata() -> Dict[str, Any]:
    metadata = collect_metadata()
    publish_event("metadata_ready", metadata)
    return metadata
```

- [ ] **Step 3: Add GET /api/breakdown endpoint**

Add path validation and the endpoint:

```python
ALLOWED_BREAKDOWN_ROOTS = [
    DATA_VOLUME.resolve(),
    HOME_DIR.resolve(),
    (HOME_DIR / "Library").resolve(),
    APPLICATIONS_DIR.resolve(),
]


def validate_breakdown_path(path_str: str) -> Path:
    """Validate that path is under an allowed root. Raise HTTPException if not."""
    try:
        path = Path(path_str).resolve()
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc
    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {path}")
    for root in ALLOWED_BREAKDOWN_ROOTS:
        try:
            path.relative_to(root)
            return path
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail="Path is not under an allowed root directory.",
    )


@app.get("/api/breakdown")
def api_breakdown(path: str) -> Dict[str, Any]:
    validated = validate_breakdown_path(path)
    result = list_root_breakdown(validated)
    return {
        "path": str(validated),
        "total_bytes": result["total_bytes"],
        "items": result["items"],
        "updated_at": iso_now(),
    }
```

- [ ] **Step 4: Update post-action flow to refresh metadata**

In `api_execute_action` (line 1432), after the action succeeds, call `collect_metadata` and publish before starting the full rescan:

```python
@app.post("/api/actions/execute")
def api_execute_action(payload: Dict[str, Any]) -> Dict[str, Any]:
    action_token = payload.get("action_token")
    if not action_token:
        raise HTTPException(status_code=400, detail="Missing action_token.")
    action = resolve_action(action_token)
    kind = action.get("kind")
    if kind == "trash_path":
        result = execute_trash_path(Path(action["path"]))
    elif kind == "delete_snapshot":
        result = execute_delete_snapshot(action["snapshot_name"], action["token"])
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action kind: {kind}")
    record_action(action, result)
    publish_event("action_result", result)
    # Lightweight metadata refresh for immediate free-space update
    try:
        metadata = collect_metadata()
        publish_event("metadata_ready", metadata)
    except Exception:
        logger.warning("Post-action metadata refresh failed", exc_info=True)
    start_scan()
    return result
```

- [ ] **Step 5: Smoke test new endpoints**

```bash
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473 &
sleep 8
# Test breakdown endpoint
curl -s "http://127.0.0.1:8473/api/breakdown?path=$HOME" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert 'items' in data, 'missing items'
assert 'total_bytes' in data, 'missing total_bytes'
assert 'updated_at' in data, 'missing updated_at'
assert len(data['items']) > 0, 'no items returned'
print(f'Breakdown: {len(data[\"items\"])} items, {data[\"total_bytes\"]} bytes')
"
# Test path validation rejects bad paths
curl -s "http://127.0.0.1:8473/api/breakdown?path=/etc" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert 'detail' in data, 'should reject /etc'
print(f'Rejected /etc: {data[\"detail\"]}')
"
# Test metadata refresh
curl -s -X POST http://127.0.0.1:8473/api/refresh-metadata | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert 'container_free_bytes' in data, 'missing container_free_bytes'
assert 'updated_at' in data, 'missing updated_at'
print(f'Metadata: {data[\"container_free_bytes\"]} free bytes')
"
kill %1 2>/dev/null
```

- [ ] **Step 6: Commit**

```bash
git add storage_monitor
git commit -m "Add breakdown drill-down and metadata refresh endpoints"
```

---

## Task 3: Backend — Granular SSE Events

**Context:** Instead of publishing one bulk `report` event at scan completion, the backend should stream incremental events as each scan phase produces results. This enables progressive UI updates.

**File:** `storage_monitor` (lines 935-1298, the scan pipeline and thread)

- [ ] **Step 1: Refactor collect_scan_report to publish streaming events**

The key change: after each phase completes, publish an SSE event with the partial result. The full report is still assembled at the end for caching, but the frontend gets data earlier.

In `collect_scan_report`, after the metadata phase completes and is parsed (after the checks are appended, around line 1027), add:

```python
# Publish metadata immediately
apfs_container = parse_apfs_list(apfs_list["stdout"] if apfs_list["ok"] else "")
data_volume = parse_diskutil_info(data_info["stdout"] if data_info["ok"] else "")
system_volume = parse_diskutil_info(root_info["stdout"] if root_info["ok"] else "")
snapshot_names = parse_local_snapshot_names(snapshot_info["stdout"] if snapshot_info["ok"] else "")

publish_event("metadata_ready", {
    "container_size_bytes": apfs_container["container_size_bytes"] or data_volume["disk_size_bytes"],
    "container_used_bytes": apfs_container["container_used_bytes"],
    "container_free_bytes": data_volume["container_free_bytes"],
    "data_volume_used_bytes": data_volume["volume_used_bytes"],
    "system_volume_used_bytes": system_volume["volume_used_bytes"],
    "updated_at": iso_now(),
})

# Publish snapshots immediately
for name in snapshot_names:
    token = parse_snapshot_token(name)
    if token is None:
        continue
    try:
        parsed_date = datetime.strptime(token, "%Y-%m-%d-%H%M%S").replace(
            tzinfo=timezone.utc
        ).isoformat()
    except ValueError:
        parsed_date = None
    action_token = encode_action_token(
        {"kind": "delete_snapshot", "snapshot_name": name, "token": token}
    )
    publish_event("snapshot_found", {
        "snapshot_name": name,
        "parsed_date": parsed_date,
        "token": token,
        "action_token": action_token,
    })
```

Move the `apfs_container`, `data_volume`, `system_volume`, `snapshot_names` parsing to right after the metadata phase (before the root phase starts), instead of at report assembly time. This way the metadata_ready event fires immediately.

- [ ] **Step 2: Publish breakdown_ready events as each root scan completes**

Replace the existing `phase_callback_builder` for the root phase. Instead of using `run_parallel_call_map` with a simple counter callback, use a callback that publishes `breakdown_ready` as each root's `du` finishes:

```python
def root_scan_callback(task_name: str, completed: int, total: int) -> None:
    set_phase_progress(root_phase, completed, total, f"{task_name.replace('_', ' ')} complete")
    # Publish individual breakdown as it arrives
    result = parallel_scans_results.get(task_name)
    if result is None:
        return
    breakdown_key_map = {
        "data_breakdown": "data_root",
        "library_breakdown": "library_root",
        "applications_breakdown": "applications_root",
        "home_breakdown_excl_library": "home_root",
    }
    key = breakdown_key_map.get(task_name)
    if key and isinstance(result, dict) and "items" in result:
        publish_event("breakdown_ready", {
            "root": key,
            "items": result["items"],
            "total_bytes": result.get("total_bytes"),
            "updated_at": iso_now(),
        })
```

This requires a small refactor: the parallel scan results need to be accessible from the callback. Change the approach to use a shared dict that futures populate:

```python
parallel_scans_results: Dict[str, Any] = {}

def root_scan_callback(task_name: str, completed: int, total: int) -> None:
    set_phase_progress(root_phase, completed, total, f"{task_name.replace('_', ' ')} complete")

parallel_scans = run_parallel_call_map(
    {
        "data_breakdown": lambda: list_root_breakdown(DATA_VOLUME),
        "library_breakdown": lambda: list_root_breakdown(HOME_DIR / "Library"),
        "applications_breakdown": lambda: list_root_breakdown(APPLICATIONS_DIR),
        "home_breakdown_excl_library": lambda: scan_immediate_child_breakdown(
            HOME_DIR, exclude_names=["Library"], injected_items=[],
        ),
        "watchlist": scan_watchlist,
    },
    max_workers=min(SCAN_WORKER_COUNT, 5),
    progress_callback=root_scan_callback,
)
```

Then after `run_parallel_call_map` returns, publish each breakdown:

```python
breakdown_key_map = {
    "data_breakdown": "data_root",
    "library_breakdown": "library_root",
    "applications_breakdown": "applications_root",
}
for task_name, key in breakdown_key_map.items():
    result = parallel_scans.get(task_name)
    if result and isinstance(result, dict) and "items" in result:
        publish_event("breakdown_ready", {
            "root": key,
            "items": result["items"],
            "total_bytes": result.get("total_bytes"),
            "updated_at": iso_now(),
        })

# Home breakdown needs library injected first
home_breakdown_excl_result = parallel_scans["home_breakdown_excl_library"]
library_breakdown_result = parallel_scans["library_breakdown"]
home_breakdown = list(home_breakdown_excl_result["items"])
if library_breakdown_result["total_bytes"] is not None:
    home_breakdown.append({
        "path": str(HOME_DIR / "Library"),
        "label": "Library",
        "allocated_bytes": library_breakdown_result["total_bytes"],
    })
home_breakdown.sort(key=lambda item: item["allocated_bytes"], reverse=True)
home_breakdown = home_breakdown[:MAX_TOP_ITEMS]
# ... compute home_total_bytes as before ...

publish_event("breakdown_ready", {
    "root": "home_root",
    "items": home_breakdown,
    "total_bytes": home_total_bytes,
    "updated_at": iso_now(),
})
```

- [ ] **Step 3: Publish findings as watchlist items are evaluated**

In `scan_watchlist`, the items are already evaluated in parallel. After the watchlist results are collected, publish each existing item:

```python
# After watchlist_result = parallel_scans["watchlist"]
watchlist = watchlist_result["items"]
for item in watchlist:
    if item["exists"]:
        finding = {
            "label": item["label"],
            "path": item["path"],
            "category": item["category"],
            "risk": item["risk"],
            "description": item["description"],
            "apparent_bytes": item["apparent_bytes"],
            "allocated_bytes": item["allocated_bytes"],
            "estimated_reclaim_bytes": item["estimated_reclaim_bytes"],
            "actionable": item["actionable"],
            "cleanup_kind": item["cleanup_kind"],
            "action_token": item["action_token"],
        }
        finding["actions"] = build_finding_actions(finding)
        publish_event("finding_added", finding)
```

- [ ] **Step 4: Publish large files as they're discovered**

In `scan_large_files`, after each root's files are collected, publish them individually:

After the large file scan completes, publish each file:

```python
large_files_result = scan_large_files(
    large_file_roots,
    progress_callback=phase_callback_builder(large_phase),
)
large_files = large_files_result["items"]
for lf in large_files:
    publish_event("large_file_found", lf)
```

- [ ] **Step 5: Keep scan_complete event with full report**

The `run_scan_thread` function already publishes `publish_event("report", report)` at the end. Rename this to `scan_complete` for clarity:

```python
publish_event("scan_complete", report)
```

The frontend will use this for final state reconciliation and caching.

- [ ] **Step 6: Smoke test streaming**

```bash
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473 &
sleep 2
# Listen to SSE stream and verify granular events arrive
timeout 30 curl -s -N http://127.0.0.1:8473/api/events | head -50 | python3 -c "
import sys
events = set()
for line in sys.stdin:
    line = line.strip()
    if line.startswith('data: '):
        import json
        try:
            packet = json.loads(line[6:])
            events.add(packet.get('type', 'unknown'))
        except json.JSONDecodeError:
            pass
print(f'Event types seen: {sorted(events)}')
expected = {'scan_status', 'metadata_ready', 'breakdown_ready'}
missing = expected - events
if missing:
    print(f'WARNING: missing expected events: {missing}')
else:
    print('All expected streaming events observed')
" || true
kill %1 2>/dev/null
```

- [ ] **Step 7: Commit**

```bash
git add storage_monitor
git commit -m "Stream granular SSE events during scan for progressive UI updates"
```

---

## Task 4: Frontend — CSS Foundation, Dark Mode & Theme Toggle

**Context:** Replace the entire `<style>` block and Tailwind config. Establish CSS custom properties for light/dark themes, remove decorative elements (grain, ticker, animated backgrounds), set up the system font stack and compact spacing tokens.

**File:** `storage_monitor` — the `HTML_TEMPLATE` string (lines 1459-2116)

- [ ] **Step 1: Replace the `<head>` section**

Replace everything in `<head>` from the opening `<meta>` tags through the closing `</style>` tag. Remove:
- Google Fonts imports (Archivo Black, Manrope, IBM Plex Mono)
- The entire Tailwind `config` block (custom font families, dossier colors, panel shadow)
- The entire `<style>` block (grain, panel, capsule, scan-bar, usage-track, chart-bar, ticker, sweep animation, etc.)

Replace with:

```html
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Storage Monitor</title>
<script src="https://unpkg.com/react@18/umd/react.development.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/lucide@0.321.0/dist/umd/lucide.min.js"></script>
<style>
  :root {
    --bg: #f4f5f7;
    --surface: #ffffff;
    --surface-hover: #f0f1f3;
    --border: rgba(0,0,0,0.08);
    --text-primary: #1a1b1e;
    --text-secondary: rgba(0,0,0,0.5);
    --accent: #c6512c;
    --accent-hover: #b54524;
    --success: #16a34a;
    --warning: #ca8a04;
    --danger: #dc2626;
    --success-bg: rgba(22,163,74,0.1);
    --warning-bg: rgba(202,138,4,0.1);
    --danger-bg: rgba(220,38,38,0.1);
    --shimmer-from: rgba(0,0,0,0.03);
    --shimmer-to: rgba(0,0,0,0.06);
  }
  [data-theme="dark"] {
    --bg: #0f1117;
    --surface: #1e2030;
    --surface-hover: #262838;
    --border: rgba(255,255,255,0.08);
    --text-primary: #e2e4e9;
    --text-secondary: rgba(255,255,255,0.5);
    --accent: #c6512c;
    --accent-hover: #d4663f;
    --success: #4ade80;
    --warning: #facc15;
    --danger: #f87171;
    --success-bg: rgba(74,222,128,0.12);
    --warning-bg: rgba(250,204,21,0.12);
    --danger-bg: rgba(248,113,113,0.12);
    --shimmer-from: rgba(255,255,255,0.03);
    --shimmer-to: rgba(255,255,255,0.06);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    background: var(--bg);
    color: var(--text-primary);
    transition: background 150ms ease, color 150ms ease;
  }
  .mono { font-family: ui-monospace, SFMono-Regular, monospace; font-variant-numeric: tabular-nums; }
  .surface { background: var(--surface); border: 1px solid var(--border); }
  .surface-hover:hover { background: var(--surface-hover); }

  /* Progress bar */
  .progress-bar { height: 3px; background: var(--border); overflow: hidden; }
  .progress-fill { height: 100%; background: var(--accent); transition: width 300ms ease; }

  /* Shimmer skeleton */
  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
  .shimmer {
    background: linear-gradient(90deg, var(--shimmer-from) 25%, var(--shimmer-to) 50%, var(--shimmer-from) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s ease infinite;
    border-radius: 6px;
  }

  /* Inline bar chart */
  .bar-track { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 3px; transition: width 300ms ease; }

  /* Treemap blocks */
  .treemap-block {
    border-radius: 6px;
    padding: 8px 10px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    transition: filter 150ms ease, outline 150ms ease;
    outline: 2px solid transparent;
    outline-offset: -2px;
    position: relative;
  }
  .treemap-block:hover { filter: brightness(1.1); }
  .treemap-block.active { outline-color: var(--text-primary); }
  .treemap-block.active::after {
    content: '';
    position: absolute;
    bottom: -6px;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: currentColor;
  }

  /* Tabs */
  .tab { padding: 7px 16px; font-size: 11px; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
  .tab.active { border-bottom-color: var(--accent); font-weight: 600; }
  .tab:not(.active) { opacity: 0.5; }
  .tab:hover:not(.active) { opacity: 0.75; }
</style>
<script>
  // Theme initialization (runs before React)
  (function() {
    var stored = localStorage.getItem('sm-theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var theme = stored || (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
      if (!localStorage.getItem('sm-theme')) {
        document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
      }
    });
  })();
</script>
```

- [ ] **Step 2: Replace the `<body>` opening**

Change from `<body class="grain">` to just `<body>`:

```html
<body>
  <div id="root"></div>
  <script type="text/babel">
```

- [ ] **Step 3: Verify the app still loads**

At this point the React JSX will be broken because it references old CSS classes and report shapes. That's expected — we're replacing it in the next tasks. For now, verify the server starts and serves the page:

```bash
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473 &
sleep 5
curl -s http://127.0.0.1:8473/ | head -5  # Should show <!DOCTYPE html>
kill %1 2>/dev/null
```

- [ ] **Step 4: Commit**

```bash
git add storage_monitor
git commit -m "Replace CSS foundation: dark mode custom properties, system fonts, compact tokens"
```

---

## Task 5: Frontend — Utility Functions & State Management Hook

**Context:** Replace the existing React code (formatBytes, useMonitorState, etc.) with updated versions that handle the new report structure, streaming SSE events, and relative time formatting.

**File:** `storage_monitor` — the `<script type="text/babel">` block inside HTML_TEMPLATE

- [ ] **Step 1: Write utility functions**

Replace everything from `const { useEffect, useMemo, useState } = React;` through the `categoryTone` object with:

```jsx
const { useCallback, useEffect, useMemo, useRef, useState } = React;

// ── Utilities ──────────────────────────────────────────
const formatBytes = (value) => {
  if (value === null || value === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let amount = Number(value);
  let i = 0;
  while (amount >= 1024 && i < units.length - 1) { amount /= 1024; i++; }
  return i === 0 ? `${Math.round(amount)} ${units[i]}` : `${amount.toFixed(1)} ${units[i]}`;
};

const formatRelativeTime = (isoString) => {
  if (!isoString) return null;
  const then = new Date(isoString);
  const now = Date.now();
  const diffMs = now - then.getTime();
  if (diffMs < 0) return 'just now';
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.floor(hr / 24);
  if (days < 2) return 'yesterday';
  if (days < 14) return `${days} days ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 8) return `${weeks} weeks ago`;
  return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const pct = (part, total) => {
  if (!part || !total) return 0;
  return Math.max(0, Math.min(100, (part / total) * 100));
};

const RISK_STYLES = {
  low:    { bg: 'var(--success-bg)', color: 'var(--success)', label: 'low' },
  medium: { bg: 'var(--warning-bg)', color: 'var(--warning)', label: 'med' },
  high:   { bg: 'var(--danger-bg)',  color: 'var(--danger)',  label: 'high' },
};

const ROOT_COLORS = {
  data_root:         '#c6512c',
  home_root:         '#1f4952',
  library_root:      '#5a7a3a',
  applications_root: '#8a6d3b',
};

const ROOT_LABELS = {
  data_root:         'Data Volume',
  home_root:         'Home',
  library_root:      'Library',
  applications_root: 'Applications',
};

const CATEGORY_COLORS = {
  snapshot: '#c6512c', cache: '#1f4952', cache_bucket: '#1f4952',
  app_cache: '#7f5b13', runtime_payload: '#7762ad', model_store: '#4c6c38',
  model_cache: '#4c6c38', stale_installer: '#8d2f2f', large_file: '#3c5f89',
  user_media: '#7a4d75', user_files: '#3c5f89', export_data: '#7a4d75',
  user_data: '#7a4d75',
};
```

- [ ] **Step 2: Write the useMonitorState hook**

Replace the existing `useMonitorState` function with a version that handles granular SSE events and accumulates streaming state:

```jsx
function useMonitorState() {
  const [metadata, setMetadata] = useState(null);
  const [breakdowns, setBreakdowns] = useState({});
  const [findings, setFindings] = useState({ items: [], updated_at: null });
  const [snapshots, setSnapshots] = useState({ items: [], updated_at: null });
  const [largeFiles, setLargeFiles] = useState({ items: [], updated_at: null });
  const [checks, setChecks] = useState([]);
  const [summary, setSummary] = useState({});
  const [scanStatus, setScanStatus] = useState({ running: true, phase: 'Booting', progress: 0 });
  const [busyToken, setBusyToken] = useState(null);
  const [message, setMessage] = useState('');

  // Apply a full report (from initial load or scan_complete)
  const applyReport = useCallback((report) => {
    if (!report) return;
    setSummary(report.summary || {});
    setBreakdowns(report.breakdowns || {});
    setFindings(report.findings || { items: [], updated_at: null });
    setSnapshots(report.snapshots || { items: [], updated_at: null });
    setLargeFiles(report.large_files || { items: [], updated_at: null });
    setChecks(report.checks || []);
    if (report.summary) {
      setMetadata({
        container_size_bytes: report.summary.container_size_bytes,
        container_used_bytes: report.summary.container_used_bytes,
        container_free_bytes: report.summary.container_free_bytes,
        data_volume_used_bytes: report.summary.data_volume_used_bytes,
        system_volume_used_bytes: report.summary.system_volume_used_bytes,
        updated_at: report.generated_at,
      });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/state')
      .then(r => r.json())
      .then(data => {
        if (cancelled) return;
        applyReport(data.report);
        setScanStatus(data.scan_status);
        if (!data.report && !data.scan_status?.running) {
          fetch('/api/scan', { method: 'POST' }).catch(() => {});
        }
      })
      .catch(() => {});

    const events = new EventSource('/api/events');
    events.onmessage = (event) => {
      try {
        const pkt = JSON.parse(event.data);
        switch (pkt.type) {
          case 'scan_status':
            setScanStatus(pkt.payload);
            // Reset streaming state when a new scan starts
            if (pkt.payload.phase === 'initializing') {
              setFindings({ items: [], updated_at: null });
              setSnapshots({ items: [], updated_at: null });
              setLargeFiles({ items: [], updated_at: null });
            }
            break;
          case 'metadata_ready':
            setMetadata(pkt.payload);
            break;
          case 'breakdown_ready':
            setBreakdowns(prev => ({
              ...prev,
              [pkt.payload.root]: {
                items: pkt.payload.items,
                total_bytes: pkt.payload.total_bytes,
                updated_at: pkt.payload.updated_at,
              },
            }));
            break;
          case 'finding_added':
            setFindings(prev => {
              const items = [...prev.items, pkt.payload];
              items.sort((a, b) => (b.estimated_reclaim_bytes || b.allocated_bytes || 0) - (a.estimated_reclaim_bytes || a.allocated_bytes || 0));
              return { items, updated_at: new Date().toISOString() };
            });
            break;
          case 'snapshot_found':
            setSnapshots(prev => ({
              items: [...prev.items, pkt.payload],
              updated_at: new Date().toISOString(),
            }));
            break;
          case 'large_file_found':
            setLargeFiles(prev => {
              const items = [...prev.items, pkt.payload];
              items.sort((a, b) => (b.allocated_bytes || 0) - (a.allocated_bytes || 0));
              return { items, updated_at: new Date().toISOString() };
            });
            break;
          case 'scan_complete':
          case 'report':
            applyReport(pkt.payload);
            break;
          case 'action_result':
            setMessage(pkt.payload.label || 'Action completed.');
            setBusyToken(null);
            break;
        }
      } catch (e) { console.error(e); }
    };
    return () => { cancelled = true; events.close(); };
  }, [applyReport]);

  const triggerScan = useCallback(async () => {
    setMessage('');
    await fetch('/api/scan', { method: 'POST' });
  }, []);

  const executeAction = useCallback(async (actionToken) => {
    setBusyToken(actionToken);
    setMessage('');
    try {
      const res = await fetch('/api/actions/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_token: actionToken }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Action failed');
      setMessage(data.label || 'Action completed.');
      // Optimistic removal
      if (data.source_path) {
        setFindings(prev => ({
          ...prev,
          items: prev.items.filter(f => f.path !== data.source_path),
        }));
      }
      if (data.snapshot_name) {
        setSnapshots(prev => ({
          ...prev,
          items: prev.items.filter(s => s.snapshot_name !== data.snapshot_name),
        }));
      }
    } catch (e) {
      setBusyToken(null);
      setMessage(e.message);
    }
  }, []);

  const revealPath = useCallback(async (path) => {
    try {
      const res = await fetch('/api/reveal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail); }
    } catch (e) { setMessage(e.message); }
  }, []);

  return {
    metadata, summary, breakdowns, findings, snapshots, largeFiles,
    checks, scanStatus, busyToken, message,
    triggerScan, executeAction, revealPath,
  };
}
```

- [ ] **Step 3: Add theme toggle helper**

```jsx
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('sm-theme', next);
}
```

- [ ] **Step 4: Commit**

```bash
git add storage_monitor
git commit -m "Rewrite React utilities and state hook for streaming SSE and new report structure"
```

---

## Task 6: Frontend — Zone 1 Header Bar Component

**Context:** The fixed header bar replaces the hero section and stat cards. Contains: app title, scan status dot, relative timestamp, usage bar, summary pills, rescan button, scan details toggle, dark mode toggle. Thin progress bar below.

**File:** `storage_monitor` — inside the `<script type="text/babel">` block

- [ ] **Step 1: Write the HeaderBar component**

```jsx
function HeaderBar({ metadata, summary, scanStatus, onRescan, onToggleTheme, checks }) {
  const [showChecks, setShowChecks] = useState(false);
  const containerSize = metadata?.container_size_bytes || summary?.container_size_bytes || 0;
  const usedBytes = metadata?.container_used_bytes || summary?.container_used_bytes || 0;
  const freeBytes = metadata?.container_free_bytes || summary?.container_free_bytes || 0;
  const hiddenBytes = summary?.hidden_delta_bytes || 0;
  const liveBytes = summary?.visible_data_bytes || 0;
  const reclaimable = (summary?.safe_reclaimable_bytes || 0) + (summary?.medium_reclaimable_bytes || 0);
  const isScanning = scanStatus?.running;
  const scanAge = formatRelativeTime(metadata?.updated_at || scanStatus?.updated_at);

  return (
    <header style={{ position: 'sticky', top: 0, zIndex: 50, background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px', gap: 12, flexWrap: 'wrap' }}>
        {/* Left: title + status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
          <span style={{ fontWeight: 700, fontSize: 14, whiteSpace: 'nowrap' }}>Storage Monitor</span>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: isScanning ? 'var(--warning-bg)' : 'var(--success-bg)',
            padding: '3px 10px', borderRadius: 12, fontSize: 10,
            color: isScanning ? 'var(--warning)' : 'var(--success)',
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
              background: isScanning ? 'var(--warning)' : 'var(--success)',
              animation: isScanning ? 'pulse 1.5s ease infinite' : 'none',
            }} />
            {isScanning ? `Scanning: ${scanStatus.phase}` : (scanAge ? `Scanned ${scanAge}` : 'Ready')}
          </div>
        </div>

        {/* Center: usage bar */}
        {containerSize > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, maxWidth: 360, minWidth: 200 }}>
            <span className="mono" style={{ fontSize: 9, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
              {formatBytes(usedBytes)} used
            </span>
            <div style={{ flex: 1, height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden', display: 'flex' }}>
              <div style={{ width: `${pct(liveBytes, containerSize)}%`, background: '#1f4952' }} />
              <div style={{ width: `${pct(hiddenBytes, containerSize)}%`, background: '#8a6d3b' }} />
            </div>
            <span className="mono" style={{ fontSize: 9, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
              {formatBytes(freeBytes)} free
            </span>
          </div>
        )}

        {/* Summary pills */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {[
            { label: 'CONTAINER', value: formatBytes(containerSize) },
            { label: 'USED', value: formatBytes(usedBytes), color: 'var(--accent)' },
            { label: 'FREE', value: formatBytes(freeBytes), color: 'var(--success)' },
            { label: 'RECLAIMABLE', value: formatBytes(reclaimable), color: 'var(--warning)' },
          ].map(p => (
            <div key={p.label} style={{
              background: 'var(--surface-hover)', padding: '4px 10px', borderRadius: 8,
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <span style={{ fontSize: 9, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{p.label}</span>
              <span className="mono" style={{ fontWeight: 600, fontSize: 12, color: p.color || 'var(--text-primary)' }}>{p.value}</span>
            </div>
          ))}
        </div>

        {/* Right: actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button onClick={onRescan} disabled={isScanning} style={{
            background: 'var(--surface-hover)', color: 'var(--text-primary)',
            border: '1px solid var(--border)', padding: '4px 12px', borderRadius: 6,
            fontSize: 11, cursor: 'pointer', opacity: isScanning ? 0.5 : 1,
          }}>Rescan</button>
          <span onClick={() => setShowChecks(!showChecks)} style={{ cursor: 'pointer', fontSize: 14, color: 'var(--text-secondary)' }} title="Scan details">&#9432;</span>
          <span onClick={onToggleTheme} style={{ cursor: 'pointer', fontSize: 16, color: 'var(--text-secondary)' }} title="Toggle dark mode">&#9790;</span>
        </div>
      </div>

      {/* Progress bar */}
      {isScanning && (
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${Math.max(2, (scanStatus.progress || 0) * 100)}%` }} />
        </div>
      )}

      {/* Checks panel (collapsible) */}
      {showChecks && checks.length > 0 && (
        <div style={{ padding: '8px 16px', borderTop: '1px solid var(--border)', fontSize: 11, maxHeight: 200, overflow: 'auto' }}>
          {checks.map(c => (
            <div key={c.label} style={{ display: 'flex', gap: 12, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ flex: 1 }}>{c.label}</span>
              <span className="mono" style={{ color: 'var(--text-secondary)' }}>{c.duration_ms != null ? `${c.duration_ms}ms` : ''}</span>
              <span style={{ color: c.ok ? 'var(--success)' : 'var(--danger)' }}>{c.ok ? 'ok' : 'warn'}</span>
            </div>
          ))}
        </div>
      )}
    </header>
  );
}
```

Also add this CSS keyframe inside the `<style>` block (after the existing `@keyframes shimmer`):

```css
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
```

- [ ] **Step 2: Commit**

```bash
git add storage_monitor
git commit -m "Add HeaderBar component with scan status, usage bar, pills, dark mode toggle"
```

---

## Task 7: Frontend — Zone 2 Treemap & Accordion Components

**Context:** The treemap is a CSS Grid of 4 proportional blocks. Clicking a block expands its accordion below showing directory children. Accordion rows are drillable via the `/api/breakdown` endpoint.

**File:** `storage_monitor` — inside the `<script type="text/babel">` block

- [ ] **Step 1: Write the Treemap component**

```jsx
function Treemap({ breakdowns, activeRoot, onSelectRoot, isScanning }) {
  const roots = ['data_root', 'home_root', 'library_root', 'applications_root'];
  const sizes = roots.map(r => breakdowns[r]?.total_bytes || 0);
  const total = sizes.reduce((a, b) => a + b, 0) || 1;
  // CSS grid columns proportional to sizes, minimum 0.15fr
  const cols = sizes.map(s => Math.max(0.15, s / total).toFixed(3) + 'fr').join(' ');

  return (
    <div style={{ display: 'grid', gridTemplateColumns: cols, gap: 3, marginBottom: 10 }}>
      {roots.map((root, i) => {
        const bd = breakdowns[root];
        const hasData = bd && bd.items && bd.items.length > 0;
        return (
          <div
            key={root}
            className={`treemap-block ${activeRoot === root ? 'active' : ''}`}
            onClick={() => onSelectRoot(activeRoot === root ? null : root)}
            style={{
              background: ROOT_COLORS[root],
              color: '#fff',
              minHeight: 90,
              opacity: hasData ? 1 : 0.5,
            }}
          >
            {hasData ? (
              <>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 13 }}>{ROOT_LABELS[root]}</div>
                  <div style={{ fontSize: 11, opacity: 0.85 }}>{formatBytes(bd.total_bytes)}</div>
                </div>
                <div style={{ fontSize: 9, opacity: 0.65, marginTop: 4 }}>
                  {bd.items.slice(0, 3).map(it => it.label).join(', ')}
                  {bd.items.length > 3 ? ` +${bd.items.length - 3}` : ''}
                </div>
              </>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                {isScanning ? <div className="shimmer" style={{ width: '60%', height: 12 }} /> : <span style={{ opacity: 0.5, fontSize: 11 }}>{ROOT_LABELS[root]}</span>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Write the AccordionBreakdown component with drill-down**

```jsx
function AccordionBreakdown({ rootKey, breakdown, isScanning }) {
  const [drillPath, setDrillPath] = useState([]);  // array of {path, label}
  const [drillData, setDrillData] = useState(null);
  const [drillLoading, setDrillLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const VISIBLE_COUNT = 10;

  // Reset drill state when root changes
  useEffect(() => {
    setDrillPath([]);
    setDrillData(null);
    setShowAll(false);
  }, [rootKey]);

  const currentItems = drillData ? drillData.items : (breakdown?.items || []);
  const currentTotal = drillData ? drillData.total_bytes : (breakdown?.total_bytes || 0);
  const displayItems = showAll ? currentItems : currentItems.slice(0, VISIBLE_COUNT);
  const maxBytes = displayItems.length > 0 ? displayItems[0].allocated_bytes : 0;
  const updatedAt = drillData?.updated_at || breakdown?.updated_at;

  const drillInto = async (item) => {
    setDrillLoading(true);
    try {
      const res = await fetch(`/api/breakdown?path=${encodeURIComponent(item.path)}`);
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail); }
      const data = await res.json();
      if (data.items && data.items.length > 0) {
        setDrillPath(prev => [...prev, { path: item.path, label: item.label }]);
        setDrillData(data);
        setShowAll(false);
      }
    } catch (e) {
      console.error('Drill-down failed:', e);
    }
    setDrillLoading(false);
  };

  const navigateBack = (index) => {
    if (index < 0) {
      // Back to root
      setDrillPath([]);
      setDrillData(null);
      setShowAll(false);
    } else {
      // Navigate to specific breadcrumb level
      const newPath = drillPath.slice(0, index + 1);
      setDrillPath(newPath);
      // Re-fetch that level
      fetch(`/api/breakdown?path=${encodeURIComponent(newPath[newPath.length - 1].path)}`)
        .then(r => r.json())
        .then(data => setDrillData(data))
        .catch(() => {});
    }
  };

  if (!breakdown || !breakdown.items) {
    return isScanning ? (
      <div style={{ padding: 16 }}>
        <div className="shimmer" style={{ height: 16, marginBottom: 8 }} />
        <div className="shimmer" style={{ height: 12, marginBottom: 6 }} />
        <div className="shimmer" style={{ height: 12, marginBottom: 6 }} />
        <div className="shimmer" style={{ height: 12 }} />
      </div>
    ) : null;
  }

  return (
    <div className="surface" style={{ borderRadius: 8, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '8px 12px', borderBottom: '1px solid var(--border)',
        background: `${ROOT_COLORS[rootKey]}15`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, flexWrap: 'wrap' }}>
          {/* Breadcrumb */}
          <span style={{ cursor: drillPath.length > 0 ? 'pointer' : 'default', fontWeight: 600, textDecoration: drillPath.length > 0 ? 'underline' : 'none' }}
                onClick={() => drillPath.length > 0 && navigateBack(-1)}>
            {ROOT_LABELS[rootKey]}
          </span>
          {drillPath.map((crumb, i) => (
            <span key={i}>
              <span style={{ opacity: 0.4, margin: '0 4px' }}>&gt;</span>
              <span style={{ cursor: i < drillPath.length - 1 ? 'pointer' : 'default', textDecoration: i < drillPath.length - 1 ? 'underline' : 'none' }}
                    onClick={() => i < drillPath.length - 1 && navigateBack(i)}>
                {crumb.label}
              </span>
            </span>
          ))}
          {drillLoading && <span style={{ fontSize: 10, opacity: 0.5 }}>loading...</span>}
        </div>
        <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>
          {formatBytes(currentTotal)} &middot; {currentItems.length} items
          {updatedAt && ` · ${formatRelativeTime(updatedAt)}`}
        </span>
      </div>

      {/* Item rows */}
      <div style={{ maxHeight: 320, overflowY: 'auto', fontSize: 11 }}>
        {displayItems.map((item) => (
          <div key={item.path} className="surface-hover"
               style={{ display: 'flex', alignItems: 'center', padding: '5px 12px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
               onClick={() => drillInto(item)}>
            <span style={{ width: 160, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {item.label}
            </span>
            <div style={{ flex: 1, margin: '0 10px' }}>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${pct(item.allocated_bytes, maxBytes)}%`, background: ROOT_COLORS[rootKey] }} />
              </div>
            </div>
            <span className="mono" style={{ width: 65, textAlign: 'right' }}>
              {formatBytes(item.allocated_bytes)}
            </span>
          </div>
        ))}
        {!showAll && currentItems.length > VISIBLE_COUNT && (
          <div onClick={() => setShowAll(true)}
               style={{ padding: '5px 12px', fontSize: 10, color: 'var(--text-secondary)', cursor: 'pointer' }}>
            Show all {currentItems.length} items...
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add storage_monitor
git commit -m "Add Treemap and AccordionBreakdown components with drill-down"
```

---

## Task 8: Frontend — Zone 3 Tabbed Action Panel (Findings, Snapshots, Large Files)

**Context:** Three tabs: Findings (compact sortable/filterable table), Snapshots (dedicated TM manager with bulk delete), Large Files (1GB+ files list).

**File:** `storage_monitor` — inside the `<script type="text/babel">` block

- [ ] **Step 1: Write the FindingsTab component**

```jsx
function FindingsTab({ findings, busyToken, onExecute, onReveal, isScanning }) {
  const [riskFilter, setRiskFilter] = useState('all');
  const [sortCol, setSortCol] = useState('size');
  const [sortAsc, setSortAsc] = useState(false);

  const items = useMemo(() => {
    let list = findings?.items || [];
    if (riskFilter !== 'all') list = list.filter(f => f.risk === riskFilter);
    const sorted = [...list];
    sorted.sort((a, b) => {
      let va, vb;
      if (sortCol === 'size') {
        va = a.estimated_reclaim_bytes || a.allocated_bytes || 0;
        vb = b.estimated_reclaim_bytes || b.allocated_bytes || 0;
      } else if (sortCol === 'risk') {
        const order = { low: 1, medium: 2, high: 3 };
        va = order[a.risk] || 0; vb = order[b.risk] || 0;
      } else {
        va = a.label?.toLowerCase() || ''; vb = b.label?.toLowerCase() || '';
      }
      if (va < vb) return sortAsc ? -1 : 1;
      if (va > vb) return sortAsc ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [findings, riskFilter, sortCol, sortAsc]);

  const handleSort = (col) => {
    if (sortCol === col) setSortAsc(!sortAsc);
    else { setSortCol(col); setSortAsc(false); }
  };

  const topReclaimPaths = useMemo(() => {
    const sorted = [...(findings?.items || [])].sort((a, b) =>
      (b.estimated_reclaim_bytes || 0) - (a.estimated_reclaim_bytes || 0)
    );
    return new Set(sorted.slice(0, 3).map(f => f.path));
  }, [findings]);

  return (
    <div style={{ fontSize: 11 }}>
      {/* Filter bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontSize: 9, color: 'var(--text-secondary)' }}>Filter:</span>
        {['all', 'low', 'medium', 'high'].map(r => (
          <span key={r} onClick={() => setRiskFilter(r)} style={{
            padding: '2px 8px', borderRadius: 4, fontSize: 9, cursor: 'pointer',
            background: riskFilter === r ? 'var(--accent)' : 'var(--surface-hover)',
            color: riskFilter === r ? '#fff' : 'var(--text-secondary)',
          }}>{r}</span>
        ))}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 9, color: 'var(--text-secondary)' }}>
          {items.length} items
          {findings?.updated_at && ` · ${formatRelativeTime(findings.updated_at)}`}
        </span>
      </div>

      {/* Column headers */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 70px 50px 70px 90px', gap: 4, padding: '6px 12px', borderBottom: '1px solid var(--border)', fontSize: 9, textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
        <span onClick={() => handleSort('name')} style={{ cursor: 'pointer' }}>Finding</span>
        <span>Category</span>
        <span onClick={() => handleSort('risk')} style={{ cursor: 'pointer' }} title="Low = safe to delete (caches). Medium = review first. High = manual review.">
          Risk &#9432;
        </span>
        <span onClick={() => handleSort('size')} style={{ cursor: 'pointer', textAlign: 'right' }}>Size</span>
        <span style={{ textAlign: 'right' }}>Actions</span>
      </div>

      {/* Rows */}
      <div style={{ maxHeight: 400, overflowY: 'auto' }}>
        {isScanning && items.length === 0 && (
          <div style={{ padding: 12 }}>
            <div className="shimmer" style={{ height: 14, marginBottom: 8 }} />
            <div className="shimmer" style={{ height: 14, marginBottom: 8 }} />
            <div className="shimmer" style={{ height: 14 }} />
          </div>
        )}
        {items.map((item) => {
          const risk = RISK_STYLES[item.risk] || {};
          const isTopReclaim = topReclaimPaths.has(item.path);
          return (
            <div key={item.path + item.label} className="surface-hover" style={{
              display: 'grid', gridTemplateColumns: '2fr 70px 50px 70px 90px', gap: 4,
              padding: '5px 12px', borderBottom: '1px solid var(--border)', alignItems: 'center',
              background: isTopReclaim ? `${ROOT_COLORS.data_root}08` : undefined,
            }}>
              <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={item.path}>
                {item.label}
              </span>
              <span style={{
                padding: '1px 6px', borderRadius: 4, fontSize: 9, textAlign: 'center',
                background: `${CATEGORY_COLORS[item.category] || '#666'}22`,
                color: CATEGORY_COLORS[item.category] || 'var(--text-secondary)',
              }}>{(item.category || '').replace(/_/g, ' ')}</span>
              <span style={{ padding: '1px 6px', borderRadius: 4, fontSize: 9, textAlign: 'center', background: risk.bg, color: risk.color }}>
                {risk.label}
              </span>
              <span className="mono" style={{ textAlign: 'right' }}>
                {formatBytes(item.estimated_reclaim_bytes || item.allocated_bytes)}
              </span>
              <span style={{ display: 'flex', gap: 3, justifyContent: 'flex-end' }}>
                {item.actions?.filter(a => a.kind === 'execute').map(a => (
                  <button key={a.label} disabled={busyToken === a.action_token}
                    onClick={() => onExecute(a.action_token)}
                    style={{ padding: '2px 7px', borderRadius: 4, fontSize: 9, border: 'none', cursor: 'pointer', background: 'var(--accent)', color: '#fff' }}>
                    {busyToken === a.action_token ? '...' : (a.label === 'Move to Trash' ? 'Trash' : a.label)}
                  </button>
                ))}
                <button onClick={() => onReveal(item.path)}
                  style={{ padding: '2px 7px', borderRadius: 4, fontSize: 9, border: '1px solid var(--border)', cursor: 'pointer', background: 'transparent', color: 'var(--text-secondary)' }}>
                  Reveal
                </button>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write the SnapshotsTab component**

```jsx
function SnapshotsTab({ snapshots, busyToken, onExecute, isScanning, onRefreshMeta }) {
  const [selected, setSelected] = useState(new Set());
  const [sortNewest, setSortNewest] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const items = useMemo(() => {
    const list = [...(snapshots?.items || [])];
    list.sort((a, b) => {
      const da = a.parsed_date || ''; const db = b.parsed_date || '';
      return sortNewest ? db.localeCompare(da) : da.localeCompare(db);
    });
    return list;
  }, [snapshots, sortNewest]);

  const toggleSelect = (name) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === items.length) setSelected(new Set());
    else setSelected(new Set(items.map(s => s.snapshot_name)));
  };

  const deleteSelected = async () => {
    if (!window.confirm(`Delete ${selected.size} snapshot${selected.size > 1 ? 's' : ''}? This cannot be undone.`)) return;
    setDeleting(true);
    for (const name of selected) {
      const snap = items.find(s => s.snapshot_name === name);
      if (snap?.action_token) {
        await onExecute(snap.action_token);
      }
    }
    setSelected(new Set());
    setDeleting(false);
  };

  const formatSnapshotDate = (isoDate) => {
    if (!isoDate) return 'Unknown date';
    const d = new Date(isoDate);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
      + ' at ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  };

  return (
    <div style={{ fontSize: 11 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <input type="checkbox" checked={selected.size === items.length && items.length > 0} onChange={selectAll} />
        <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{items.length} local snapshot{items.length !== 1 ? 's' : ''}</span>
        {selected.size > 0 && (
          <button onClick={deleteSelected} disabled={deleting}
            style={{ padding: '3px 10px', borderRadius: 4, fontSize: 10, border: 'none', cursor: 'pointer', background: 'var(--danger)', color: '#fff' }}>
            {deleting ? 'Deleting...' : `Delete ${selected.size}`}
          </button>
        )}
        <div style={{ flex: 1 }} />
        <span onClick={() => setSortNewest(!sortNewest)}
          style={{ fontSize: 9, color: 'var(--text-secondary)', cursor: 'pointer', textDecoration: 'underline' }}>
          {sortNewest ? 'newest first' : 'oldest first'}
        </span>
      </div>

      {/* Info note */}
      <div style={{ padding: '6px 12px', fontSize: 10, color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)', lineHeight: 1.5 }}>
        Snapshot space is managed by APFS and reclaimed as needed. Deleting old snapshots can free space, but the exact amount depends on shared block references.
      </div>

      {/* Rows */}
      <div style={{ maxHeight: 350, overflowY: 'auto' }}>
        {isScanning && items.length === 0 && (
          <div style={{ padding: 12 }}>
            <div className="shimmer" style={{ height: 14, marginBottom: 8 }} />
            <div className="shimmer" style={{ height: 14 }} />
          </div>
        )}
        {items.map((snap) => (
          <div key={snap.snapshot_name} style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px',
            borderBottom: '1px solid var(--border)',
          }}>
            <input type="checkbox" checked={selected.has(snap.snapshot_name)} onChange={() => toggleSelect(snap.snapshot_name)} />
            <span style={{ flex: 1 }}>{formatSnapshotDate(snap.parsed_date)}</span>
            <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{formatRelativeTime(snap.parsed_date)}</span>
            <button onClick={() => onExecute(snap.action_token)} disabled={busyToken === snap.action_token}
              style={{ padding: '2px 8px', borderRadius: 4, fontSize: 9, border: 'none', cursor: 'pointer', background: 'var(--danger-bg)', color: 'var(--danger)' }}>
              {busyToken === snap.action_token ? '...' : 'Delete'}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Write the LargeFilesTab component**

```jsx
function LargeFilesTab({ largeFiles, onReveal, isScanning }) {
  const items = largeFiles?.items || [];
  return (
    <div style={{ fontSize: 11 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 70px 90px', gap: 4, padding: '6px 12px', borderBottom: '1px solid var(--border)', fontSize: 9, textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
        <span>File</span>
        <span style={{ textAlign: 'right' }}>Size</span>
        <span style={{ textAlign: 'right' }}>Action</span>
      </div>
      <div style={{ maxHeight: 400, overflowY: 'auto' }}>
        {isScanning && items.length === 0 && (
          <div style={{ padding: 12 }}>
            <div className="shimmer" style={{ height: 14, marginBottom: 8 }} />
            <div className="shimmer" style={{ height: 14 }} />
          </div>
        )}
        {items.map((item) => (
          <div key={item.path} className="surface-hover" style={{
            display: 'grid', gridTemplateColumns: '2fr 70px 90px', gap: 4,
            padding: '5px 12px', borderBottom: '1px solid var(--border)', alignItems: 'center',
          }}>
            <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={item.path}>
              {item.label}
            </span>
            <span className="mono" style={{ textAlign: 'right' }}>{formatBytes(item.allocated_bytes)}</span>
            <span style={{ textAlign: 'right' }}>
              <button onClick={() => onReveal(item.path)}
                style={{ padding: '2px 7px', borderRadius: 4, fontSize: 9, border: '1px solid var(--border)', cursor: 'pointer', background: 'transparent', color: 'var(--text-secondary)' }}>
                Reveal
              </button>
            </span>
          </div>
        ))}
        {!isScanning && items.length === 0 && (
          <div style={{ padding: 12, color: 'var(--text-secondary)', textAlign: 'center' }}>No files &ge; 1 GB found</div>
        )}
      </div>
      {largeFiles?.updated_at && (
        <div style={{ padding: '4px 12px', fontSize: 9, color: 'var(--text-secondary)', borderTop: '1px solid var(--border)' }}>
          Scanned {formatRelativeTime(largeFiles.updated_at)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Write the ActionPanel (tabbed container)**

```jsx
function ActionPanel({ findings, snapshots, largeFiles, busyToken, onExecute, onReveal, isScanning }) {
  const [activeTab, setActiveTab] = useState('findings');
  const findingsCount = findings?.items?.length || 0;
  const snapshotsCount = snapshots?.items?.length || 0;
  const largeFilesCount = largeFiles?.items?.length || 0;

  return (
    <div className="surface" style={{ borderRadius: 8, overflow: 'hidden' }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
        {[
          { key: 'findings', label: 'Findings', count: findingsCount },
          { key: 'snapshots', label: 'Snapshots', count: snapshotsCount },
          { key: 'large_files', label: 'Large Files', count: largeFilesCount },
        ].map(t => (
          <div key={t.key} className={`tab ${activeTab === t.key ? 'active' : ''}`}
               onClick={() => setActiveTab(t.key)}>
            {t.label}
            <span style={{ marginLeft: 4, padding: '1px 6px', borderRadius: 8, fontSize: 9, background: activeTab === t.key ? `${('var(--accent)')}22` : 'var(--surface-hover)' }}>
              {t.count}
            </span>
          </div>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'findings' && (
        <FindingsTab findings={findings} busyToken={busyToken} onExecute={onExecute} onReveal={onReveal} isScanning={isScanning} />
      )}
      {activeTab === 'snapshots' && (
        <SnapshotsTab snapshots={snapshots} busyToken={busyToken} onExecute={onExecute} isScanning={isScanning} />
      )}
      {activeTab === 'large_files' && (
        <LargeFilesTab largeFiles={largeFiles} onReveal={onReveal} isScanning={isScanning} />
      )}
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add storage_monitor
git commit -m "Add tabbed ActionPanel with Findings, Snapshots, and Large Files tabs"
```

---

## Task 9: Frontend — App Component & Final Assembly

**Context:** Wire all components together in the App component. Replace the entire existing App function with the new 3-zone layout.

**File:** `storage_monitor` — inside the `<script type="text/babel">` block

- [ ] **Step 1: Replace the entire App component and remove old components**

Remove the old `StatCard`, `BreakdownList`, and `App` components entirely. Write the new `App`:

```jsx
function App() {
  const {
    metadata, summary, breakdowns, findings, snapshots, largeFiles,
    checks, scanStatus, busyToken, message,
    triggerScan, executeAction, revealPath,
  } = useMonitorState();

  const [activeRoot, setActiveRoot] = useState(null);
  const isScanning = scanStatus?.running;

  // Auto-select first available root
  useEffect(() => {
    if (activeRoot) return;
    for (const key of ['data_root', 'home_root', 'library_root', 'applications_root']) {
      if (breakdowns[key]?.items?.length > 0) {
        setActiveRoot(key);
        break;
      }
    }
  }, [breakdowns, activeRoot]);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Zone 1: Header */}
      <HeaderBar
        metadata={metadata}
        summary={summary}
        scanStatus={scanStatus}
        onRescan={triggerScan}
        onToggleTheme={toggleTheme}
        checks={checks}
      />

      {/* Message bar */}
      {message && (
        <div style={{ padding: '4px 16px', fontSize: 11, background: 'var(--success-bg)', color: 'var(--success)' }}>
          {message}
        </div>
      )}

      <div style={{ flex: 1, padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1600, margin: '0 auto', width: '100%' }}>
        {/* Zone 2: Storage Map */}
        <section>
          <Treemap
            breakdowns={breakdowns}
            activeRoot={activeRoot}
            onSelectRoot={setActiveRoot}
            isScanning={isScanning}
          />
          {activeRoot && (
            <AccordionBreakdown
              rootKey={activeRoot}
              breakdown={breakdowns[activeRoot]}
              isScanning={isScanning}
            />
          )}
        </section>

        {/* Zone 3: Action Panel */}
        <section style={{ flex: 1, minHeight: 0 }}>
          <ActionPanel
            findings={findings}
            snapshots={snapshots}
            largeFiles={largeFiles}
            busyToken={busyToken}
            onExecute={executeAction}
            onReveal={revealPath}
            isScanning={isScanning}
          />
        </section>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
```

- [ ] **Step 2: Full smoke test**

```bash
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473 &
sleep 8
# Verify HTML serves
curl -s http://127.0.0.1:8473/ | grep -q 'Storage Monitor' && echo "HTML serves OK" || echo "HTML FAILED"
# Verify API still works
curl -s http://127.0.0.1:8473/api/state | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert data.get('report') is not None, 'no report'
print('API OK')
"
# Verify breakdown endpoint
curl -s "http://127.0.0.1:8473/api/breakdown?path=$HOME" | python3 -c "
import sys, json; data = json.load(sys.stdin)
assert len(data['items']) > 0; print('Breakdown OK')
"
# Verify metadata refresh
curl -s -X POST http://127.0.0.1:8473/api/refresh-metadata | python3 -c "
import sys, json; data = json.load(sys.stdin)
assert 'container_free_bytes' in data; print('Metadata refresh OK')
"
kill %1 2>/dev/null
echo "All smoke tests passed"
```

- [ ] **Step 3: Manual browser test**

Open the app in a browser and verify:
1. Dark mode applies correctly (check OS preference + toggle)
2. Header bar shows scan status, usage bar, summary pills
3. Treemap renders 4 blocks proportional to size
4. Clicking a treemap block opens the accordion
5. Clicking an accordion row drills down (loading spinner, breadcrumb)
6. Findings tab shows sortable/filterable table with Trash and Reveal buttons
7. Snapshots tab shows date-sorted list with checkboxes and bulk delete
8. Large Files tab shows 1GB+ files with Reveal
9. Shimmer placeholders appear during scan for unfilled sections
10. Sections update progressively as scan data streams in

- [ ] **Step 4: Commit**

```bash
git add storage_monitor
git commit -m "Complete UI redesign: 3-zone dashboard with treemap, accordion, tabbed actions, dark mode"
```

---

## Task 10: Polish & Cleanup

**Context:** Final pass — fix any layout issues, verify edge cases, update README and docs.

**File:** `storage_monitor`, `README.md`

- [ ] **Step 1: Test edge cases**

- Empty state (no prior scan, first launch)
- Scan errors (manually kill a scan mid-way)
- Zero findings / zero snapshots / zero large files
- Light mode vs dark mode toggle
- Small viewport (1280x720)
- Theme toggle persists across page reload

- [ ] **Step 2: Update README.md**

Add a note about the UI redesign, dark mode support, and the new breakdown drill-down feature. Update any screenshots or feature descriptions.

- [ ] **Step 3: Update VERSION**

Bump `VERSION = "0.1.0"` to `VERSION = "0.2.0"` to reflect the redesign.

- [ ] **Step 4: Commit**

```bash
git add storage_monitor README.md
git commit -m "Polish UI redesign: edge cases, README update, version bump to 0.2.0"
```

---

## Summary of Backend Changes

| Change | Location |
|--------|----------|
| Remove `phase_progress`, `completed_in_phase`, `total_in_phase` from scan_status | AppState, set_phase_progress, run_scan_thread, start_scan |
| Separate snapshots from findings, wrap in `{items, updated_at}` | collect_scan_report |
| Per-section `updated_at` timestamps | Report breakdowns, findings, large_files, snapshots |
| Granular SSE: `metadata_ready`, `breakdown_ready`, `finding_added`, `large_file_found`, `snapshot_found`, `scan_complete` | collect_scan_report, run_scan_thread |
| `GET /api/breakdown?path=` | New endpoint |
| `POST /api/refresh-metadata` | New endpoint |
| Post-action metadata refresh before rescan | api_execute_action |
| Action token validation checks both findings and snapshots | resolve_action |

## Summary of Frontend Changes

| Change | Component |
|--------|-----------|
| CSS custom properties, dark/light themes, system detection | `<style>` + inline `<script>` |
| Fixed header bar with scan status, usage bar, pills | HeaderBar |
| CSS Grid treemap (4 roots) | Treemap |
| Collapsible accordion with drill-down via `/api/breakdown` | AccordionBreakdown |
| Tabbed action panel | ActionPanel |
| Sortable/filterable findings table | FindingsTab |
| Snapshot manager with bulk delete | SnapshotsTab |
| Large files list | LargeFilesTab |
| Streaming state accumulation from granular SSE | useMonitorState |
| Relative time formatter | formatRelativeTime |
| Shimmer placeholders during scan | shimmer CSS class |
| Optimistic removal on action | useMonitorState |
