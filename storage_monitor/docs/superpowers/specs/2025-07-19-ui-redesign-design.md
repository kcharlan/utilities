# Storage Monitor UI Redesign — Design Spec

## Problem Statement

The current Storage Monitor UI has several usability issues:
- **Low density**: Large cards, excessive padding, and decorative elements require extensive scrolling to access useful information.
- **No dark mode**: Light-only warm cream palette.
- **Unclear scan state**: No indication of data freshness or scan progress per section. Cached/stale data is indistinguishable from fresh data.
- **Scattered Time Machine snapshots**: Mixed into general findings, sorted to the bottom due to unknown size, no chronological ordering or bulk actions.
- **Jumpy progress indicator**: Phase transitions cause task counters to jump (e.g., "3/5 tasks" to "6/17 tasks") because different phases have different task counts.
- **Monolithic scan delivery**: All results arrive at once after the full scan completes, leaving the user waiting with no actionable data.

## Design Decisions

- **Approach**: Rewrite the embedded React SPA with a new layout and information architecture. Backend gets granular SSE events and new endpoints. Single-file architecture preserved.
- **Priority**: Density and information per screen above all else.
- **Workflow served**: Mix of browsing (understanding where space lives) and targeted hunting (finding and killing specific space hogs).
- **Core value sections**: Breakdowns (where space is) and findings (what to do about it). Summary stats are orientation, not the main event.

## Architecture Overview

Same single-file self-bootstrapping Python app. Same tech stack (React 18, Tailwind, Lucide via CDN, Babel Standalone). Backend remains FastAPI + uvicorn with SSE. Changes are to the HTML template (full rewrite), backend scan pipeline (streaming), and API surface (new endpoints).

---

## Section 1: Layout & Information Architecture

### Three-Zone Single-Screen Dashboard

The page is organized into 3 horizontal zones designed to fit on one screen at 1080p+.

#### Zone 1 — Header Bar (fixed, ~48px)

| Element | Description |
|---------|-------------|
| App title | Compact, left-aligned |
| Scan status | Pulsing green dot when fresh, animated dot when scanning. Shows relative timestamp: "Scanned 2m ago" |
| Disk usage bar | Thin segmented bar (used/hidden/free) inline in the header. Replaces the current large usage track |
| Summary pills | Small pill-shaped indicators: Container size, Used, Free, Reclaimable (sum of `safe_reclaimable_bytes` + `medium_reclaimable_bytes`). Replaces large stat cards |
| Rescan button | Triggers full scan |
| Scan details icon | Expandable panel showing scan phase metadata (the current "Checks" table). Power-user data, hidden by default |
| Dark mode toggle | Moon/sun icon, persists to localStorage |

#### Zone 2 — Storage Map (~60% of viewport)

**Treemap (top):**
- Proportional rectangles for the 4 root areas: Data Volume, Home, Library, Applications
- Color-coded per root (consistent colors throughout the UI)
- Rectangle size proportional to disk usage
- Click a block to expand its accordion below
- Selected block gets a highlight border and a downward arrow indicator pointing to the accordion

**Accordion detail (bottom):**
- Expands below the treemap showing the children of the selected root
- Each item: name, inline proportional bar, size (right-aligned, tabular-nums)
- Top 10 items shown by default, "Show all N" expander for the rest
- One accordion open at a time — clicking another treemap block swaps it
- Per-section timestamp in the accordion header: "scanned Xm ago"
- **Drill-down**: clicking a row within the accordion triggers a live `du` on that subdirectory, showing its children inline (indented or replacing the list). Breadcrumb trail at top: `Data > Users > kevinharlan > Library` for navigation back up.
- Cap visible children at 10-12 per level with "Show more"
- Loading spinner per row during drill-down (new `du` in progress)
- Constrained height with internal scroll if deep drill produces extensive content

#### Zone 3 — Action Panel (~40% of viewport, tabbed)

Three tabs:

| Tab | Content |
|-----|---------|
| **Findings** | Compact table of all actionable findings. Columns: Finding (name), Category (badge), Risk (badge), Size, Actions. Sortable. Filterable by risk/category. Column headers present. Risk levels explained via tooltip or legend. |
| **Snapshots** | Dedicated Time Machine section (see Section 3) |
| **Large Files** | Files >= 1GB, separated from general findings |

**Removed sections:**
- **Action Deck** (top 8 findings as cards): duplicates findings table, wastes space. Top-reclaimable items get a subtle row accent in the findings table instead.
- **Watchlist cards**: watchlist items that exist appear as findings. Absent watchlist items are not shown (not useful).
- **Checks table**: moved to collapsible details panel behind scan details icon in header.

### Findings Table Detail

- Column headers: Finding, Category, Risk, Size, Actions
- Risk column has header with tooltip explaining levels:
  - **Low**: Safe to delete. Caches that regenerate automatically.
  - **Medium**: Review before deleting. May have side effects.
  - **High**: Manual review required. Cannot be undone.
- Primary action button ("Move to Trash") is visually prominent — filled accent color
- Secondary action ("Reveal in Finder") is subdued/outline style
- Rows sortable by any column, filterable by risk level (all/low/med/high toggle)
- Top-reclaimable items get a subtle accent background to draw the eye

---

## Section 2: Scan Status & Progressive Updates

### Per-Section Staleness Timestamps

Every data section (each accordion breakdown, findings tab, snapshots tab, large files tab) shows its own "scanned Xm ago" in its header. Backend tracks `updated_at` per section in the report.

**Relative time formatting rules:**
- < 60s: "just now"
- < 60m: "Xm ago"
- < 24h: "Xh ago"
- < 48h: "yesterday"
- < 14d: "X days ago"
- < 8w: "X weeks ago"
- >= 8w: formatted date (e.g., "Mar 5")

### Progressive Section Updates

Backend publishes partial results via SSE as each scan phase completes:

1. **Metadata probes complete** (~2s) → header bar updates with container/volume/free stats, summary pills refresh
2. **Each root breakdown completes** (independently) → that root's treemap block and accordion become interactive. Other roots show shimmer placeholder.
3. **Large files arrive** (streaming, per-file) → large files tab populates progressively, each file inserted in sorted position
4. **Findings/watchlist arrive** (streaming, per-item) → findings tab populates progressively
5. **Snapshots arrive** (streaming, per-snapshot) → snapshots tab populates

Within seconds of starting a scan, the first breakdown is visible and interactive.

### Scan Progress Indicator — Simplified

- Thin progress bar in the header bar (overall 0-1.0 percentage, smoothly animated via CSS transition)
- Shimmer/skeleton effect on sections that haven't refreshed yet
- **No more task counters** (removed `completed_in_phase` / `total_in_phase`). The visual shimmer on pending sections communicates what's done vs pending better than numbers that jump between phases.
- Sections fade in smoothly when their data arrives, replacing the shimmer

### Interactivity During Scan

Everything already loaded is fully interactive during a scan — click, drill down, execute actions. No greying out, no blocking. The "scanned Xm ago" label is the honest signal about freshness.

---

## Section 3: Time Machine Snapshots Section

### Dedicated Snapshots Tab

Located as the second tab in Zone 3's action panel.

**Header row:**
- Count badge: "N local snapshots"
- "Select All" checkbox
- "Delete Selected" button (disabled until selection, shows count: "Delete 3")
- Sort toggle: newest-first / oldest-first (default: oldest-first — old snapshots are usually the cleanup targets)

**Snapshot list rows:**
- Checkbox for multi-select
- Human-readable date/time (e.g., "Mar 19, 2026 at 2:30 PM") — parsed from the raw `com.apple.TimeMachine.YYYY-MM-DD-HHMMSS.local` token
- Relative age (e.g., "2 days ago") — same formatter as staleness timestamps
- Individual delete button

**No size column.** Info note at top of section: "Snapshot space is managed by APFS and reclaimed as needed. Deleting old snapshots can free space, but the exact amount depends on shared block references."

### Bulk Delete Behavior

1. Select multiple snapshots via checkboxes
2. Click "Delete Selected"
3. Confirmation prompt: "Delete N snapshots? This cannot be undone."
4. Executes sequentially (each `tmutil deletelocalsnapshots` call)
5. Small progress indicator during batch
6. Each row disappears with fade-out animation as its deletion succeeds
7. After each individual deletion (or batch completion): lightweight metadata refresh to update free space numbers in header immediately
8. Full background rescan kicks off after batch completes for comprehensive reconciliation

---

## Section 4: Dark Mode & Visual Design

### Color Palette

**Dark mode** (default when OS `prefers-color-scheme: dark`):

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#0f1117` | Page background (deep blue-black) |
| `--surface` | `#1e2030` | Cards, panels, accordions |
| `--border` | `rgba(255,255,255,0.08)` | Subtle structure lines |
| `--text-primary` | `#e2e4e9` | Main text |
| `--text-secondary` | `rgba(255,255,255,0.5)` | Labels, descriptions |
| `--accent` | `#c6512c` | Primary actions, emphasis (rust) |
| `--accent-hover` | `#d4663f` | Hover state for accent |
| `--success` | `#4ade80` | Low risk, fresh status, free space |
| `--warning` | `#facc15` | Medium risk |
| `--danger` | `#f87171` | High risk |

**Light mode** (when OS is light or user toggles):

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#f4f5f7` | Page background (cool neutral) |
| `--surface` | `#ffffff` | Cards, panels |
| `--border` | `rgba(0,0,0,0.08)` | Structure lines |
| `--text-primary` | `#1a1b1e` | Main text |
| `--text-secondary` | `rgba(0,0,0,0.5)` | Labels, descriptions |
| `--accent` | `#c6512c` | Same rust accent (works on both) |

### Design Tokens

| Token | Value |
|-------|-------|
| Border radius | 6-8px (compact, not bubbly) |
| Font | System stack: `-apple-system, BlinkMacSystemFont, system-ui, sans-serif` |
| Monospace | `ui-monospace, SFMono-Regular, monospace` with `font-variant-numeric: tabular-nums` |
| Spacing grid | 8px base (4px, 8px, 12px, 16px increments) |
| Row padding | 4-8px vertical, 12px horizontal |
| Section padding | 12-16px |
| Transitions | 150ms ease (hover states, theme toggle, section reveals) |

### Theme Implementation

CSS custom properties on `:root` (light) and `[data-theme="dark"]`. JS initialization:
1. Check localStorage for user override
2. If no override, read `window.matchMedia('(prefers-color-scheme: dark)')`
3. Listen for OS theme changes via `matchMedia.addEventListener('change', ...)`
4. Set `data-theme` attribute on `<html>`
5. Toggle button swaps theme and persists to localStorage

### Removed

- Grain texture overlay
- Ticker/sweep animations
- Animated gradient backgrounds
- Custom font imports (Archivo Black, Manrope, IBM Plex Mono)
- Large decorative border-radius (28-34px → 6-8px)

---

## Section 5: Backend Changes

### A) Granular SSE Events

Replace the single bulk `report` event with streaming per-item events:

| Event | Payload | Fires when |
|-------|---------|------------|
| `metadata_ready` | Container/volume/free stats | Phase 1 (metadata probes) completes |
| `breakdown_ready` | `{root: "data_root", items: [...], total_bytes, updated_at}` | Each root's `du` completes independently |
| `finding_added` | Single finding object | Each watchlist item evaluated |
| `large_file_found` | Single large file object | `find` discovers each file |
| `snapshot_found` | Single snapshot object | Each snapshot parsed from `tmutil` |
| `scan_complete` | Full assembled report | All phases done. Report cached to disk. |

The frontend accumulates these events into local state, inserting items in sorted position as they arrive.

The existing `scan_status` event continues to fire for progress bar updates, but without `completed_in_phase` / `total_in_phase` fields.

### B) On-Demand Breakdown Endpoint

```
GET /api/breakdown?path=/System/Volumes/Data/Users
```

- Runs `du -x -k -d 1` on the requested path
- Returns `{path, total_bytes, items: [{path, label, allocated_bytes}], updated_at}`
- Same format as existing breakdown items
- **Path validation**: must be a descendant of one of the 4 known roots (`/System/Volumes/Data`, `$HOME`, `$HOME/Library`, `/Applications`). Reject traversal attempts.
- **Timeout**: 240s (inherit existing du timeout)
- Top 16 items returned, sorted by size descending

### C) Lightweight Metadata Refresh

```
POST /api/refresh-metadata
```

- Runs only `diskutil info` commands (phase 1 probes)
- Returns updated `{container_size_bytes, container_used_bytes, container_free_bytes, data_volume_used_bytes, system_volume_used_bytes}`
- Used after snapshot deletions and trash actions to quickly update header/pill numbers
- Does NOT trigger a full rescan

### D) Per-Section Timestamps

Report structure adds `updated_at` (ISO 8601) to:
- Each breakdown in `breakdowns` dict
- `findings` array (top-level)
- `large_files` array (top-level)
- `snapshots` (new top-level array, pulled out of findings)
- Global `generated_at` remains as the full-report completion timestamp

### E) Scan Progress Simplification

Remove from `scan_status`:
- `completed_in_phase`
- `total_in_phase`
- `phase_progress`

Keep:
- `running` (bool)
- `phase` (string)
- `progress` (float 0.0-1.0, smoothly weighted across phases)
- `started_at`, `updated_at`
- `error`

### F) Report Structure Changes

**New top-level field:** `snapshots` array (pulled out of `findings`):
```json
{
  "snapshots": [
    {
      "snapshot_name": "com.apple.TimeMachine.2026-03-19-143022.local",
      "parsed_date": "2026-03-19T14:30:22",
      "action_token": "...",
      "updated_at": "..."
    }
  ]
}
```

**Findings no longer contain snapshots.** Snapshots have their own tab and data path.

### G) Live Reconciliation After Actions

When an action executes successfully (trash or snapshot delete):
1. Frontend optimistically removes the item from local state immediately
2. Backend runs lightweight metadata refresh → publishes `metadata_ready` SSE event → header/pills update
3. Backend kicks off full background rescan
4. Rescan streams results via granular SSE events, merging into frontend state (not replacing wholesale)
5. If an item was deleted during a scan, the scan's `du`/`find` naturally won't see it — no special handling needed

---

## Section 6: Treemap Implementation Detail

### Rendering

The treemap is rendered as CSS Grid, not Canvas or SVG. This keeps it simple, accessible, and consistent with the rest of the UI.

**Algorithm**: Squarified treemap layout (compute rectangles with aspect ratios close to 1). For 4 top-level blocks this is straightforward — a single row or simple 2x2 arrangement based on relative sizes.

**When drilling down** (clicking a treemap block to see its children), the treemap itself does NOT re-render to show sub-blocks. The treemap stays as the 4-root overview navigator. Drill-down detail lives in the accordion below. This keeps the treemap stable and predictable.

### Interaction

- **Hover**: lighten the block slightly, show tooltip with exact size
- **Click**: expand/collapse that root's accordion below, highlight the block with a border
- **Active block**: gets a 2px accent border and a small downward arrow indicator

### Colors

Each root has a consistent color used in both the treemap block and its accordion header:

| Root | Color |
|------|-------|
| Data Volume | `#c6512c` (rust) |
| Home | `#1f4952` (steel/teal) |
| Library | `#5a7a3a` (olive) |
| Applications | `#8a6d3b` (amber) |

---

## Out of Scope

- **History/trends**: No time-series tracking of disk usage over sessions. The existing `history/` snapshots on disk remain but aren't surfaced in the new UI.
- **Notifications/alerts**: No threshold-based warnings or scheduled scans.
- **Multi-volume support**: Still scans the single APFS container on the boot drive.
- **File preview**: No preview of large files before deletion.
- **Undo for snapshot deletion**: `tmutil deletelocalsnapshots` is irreversible. Confirmation dialog is the safety net.
