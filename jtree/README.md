# jtree: Interactive JSON Viewer & Editor

jtree is a graphical, node-graph-based JSON explorer that renders JSON as an interactive mind map on a pannable/zoomable canvas. Full editing capabilities (add, delete, rename, edit, copy/paste, reorder) are built in.

## Quick Start

```zsh
# Run with a file
./jtree data.json

# Run without a file (opens to welcome screen, use Open button)
./jtree

# Or make it global
ln -s "$(pwd)/jtree" /usr/local/bin/jtree
jtree data.json
```

On first run, jtree creates a runtime home at `~/.jtree/`, a private virtual environment at `~/.jtree/venv/`, and a `bootstrap_state.json` refresh marker.

## Options

```
jtree [file.json] [--port 8100] [--readonly]
```

| Flag | Default | Description |
|------|---------|-------------|
| `[file.json]` | optional | Path to the JSON file (opens welcome screen if omitted) |
| `--port`, `-p` | 8100 | Port for the local server |
| `--readonly` | off | Disable all editing |

## Features

### Interactive Node Graph
- **Layered horizontal layout**: Root on the left, children expand rightward
- **Click** to expand/collapse object and array nodes; **Expand All** via context menu
- **Pan** by dragging the canvas; **zoom** with scroll wheel
- Collapsed nodes show summaries like `{5 keys}` or `[3 items]`
- **Containment lanes**: Dashed borders visually group expanded children by depth

### Visual Design
- **Blueprint aesthetic**: Dark navy background with subtle grid lines
- **Color-coded types**: Each JSON type has a distinct border color and badge
  - Object (cyan), Array (purple), String (green), Number (orange), Boolean (red), Null (blue-grey)
- **Light/dark mode** toggle with localStorage persistence

### File Operations
- **Open**: Click the Open button or Ctrl+O / Cmd+O to load a JSON file via browser picker or server path
- **Save**: Write changes back to the original file
- **Save As**: Browser file picker (primary) or typed server path; supports `~` expansion

### Editing
- **Edit values**: Double-click any leaf node for inline editing
- **Add child**: Right-click a container node > Add Child (with type selector)
- **Delete**: Right-click > Delete (confirmation for subtrees)
- **Rename key**: Right-click > Rename Key (objects only)
- **Copy/Paste**: Copy entire nodes or subtrees, paste into any container (Cmd+C / Cmd+V); auto-names duplicates (`key_copy1`, `key_copy2`, etc.); clipboard survives file switches for cross-file workflows
- **Array reordering**: Move Up, Move Down, or Move to Position via context menu
- **Undo/Redo**: Stack of 50 operations, Ctrl+Z / Cmd+Z to undo, Ctrl+Shift+Z / Ctrl+Y to redo

### Navigation
- **Navigator sidebar**: Collapsible tree-of-contents showing only container nodes (objects and arrays) with disclosure triangles. Click any node to pan the canvas to it. Auto-reveals and scrolls to the active node as you navigate. Toggle with Ctrl+B or the toolbar button. A thin rail remains visible when collapsed for discoverability.
- **Breadcrumb bar**: Clickable path at the top (e.g., `root > users > [0] > address`)
- **Full file path** displayed in header with copy-to-clipboard button
- **Search**: Ctrl+F / Cmd+F opens a search panel with key/value/both filtering
- **Minimap**: Bottom-right scaled overview with click-to-navigate and drag-to-pan
- **Context menu**: Right-click any node for all operations

### Export
- **SVG**: Vector export of the current graph view
- **PNG / JPEG**: Raster export at 2x resolution (rendered from SVG)

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl/Cmd + O | Open file |
| Ctrl/Cmd + S | Save |
| Ctrl/Cmd + Z | Undo |
| Ctrl/Cmd + Shift + Z (or Ctrl + Y) | Redo |
| Ctrl/Cmd + C | Copy node |
| Ctrl/Cmd + V | Paste node |
| Ctrl/Cmd + B | Toggle navigator sidebar |
| Ctrl/Cmd + F | Toggle search |
| Escape | Close modal/search |

### Performance
- Full JSON loaded in memory server-side; frontend fetches slices on demand
- Handles files up to 50 MB
- Large arrays paginated (50 items at a time)
- Only expanded nodes are rendered

## Architecture

Single-file self-bootstrapping Python script following the embedded React SPA pattern:

- **Backend**: FastAPI + uvicorn serving REST API and HTML
- **Frontend**: React 18, Tailwind CSS, Lucide Icons, DM Sans + JetBrains Mono fonts (all CDN)
- **No build step**: No `npm install`, no `node_modules`

## Requirements

- Python 3.8+
- A modern web browser
- Dependencies installed automatically on first run
