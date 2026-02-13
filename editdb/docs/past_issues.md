# EditDB Past Issues

## 2026-02-13: SQL Console caused white-screen crash

- Symptom:
  - Opening the SQL Console intermittently blanked the UI.
  - Browser console showed React error:
    - `NotFoundError: Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.`
- Root cause:
  - The `Icon` component used imperative DOM mutation (`lucide.createIcons` + manual element replacement) inside React-managed nodes.
  - React reconciliation later attempted to remove/update nodes that had already been replaced outside React, causing the crash.
- Fix:
  - Replaced imperative icon DOM mutation with a React-rendered SVG component using Lucide icon data.
  - Added a top-level React `ErrorBoundary` so future frontend runtime failures render a recoverable error screen instead of a blank page.
- Validation:
  - `python3 -m py_compile editdb` passes.
  - SQL Console navigation no longer triggers the prior `removeChild` crash path.

## 2026-02-13: Action icons became invisible but buttons still worked

- Symptom:
  - Row edit icon (left pencil), index edit icon (right pencil), and index delete icon were clickable but not visible.
- Root cause:
  - Lucide UMD icon map uses PascalCase keys (example: `Edit3`), while component lookup used kebab-case names (example: `edit-3`), resulting in missing icon definitions.
- Fix:
  - Added kebab-case to PascalCase conversion before icon lookup.
  - Render now uses Lucide’s canonical tuple format (`[tag, attrs, children]`) to construct SVG children via React.
- Validation:
  - `python3 -m py_compile editdb` passes.
  - Icon controls render visually while preserving existing click behavior.

## Notes

- The browser console message:
  - `A listener indicated an asynchronous response by returning true, but the message channel closed before a response was received`
  - was assessed as extension/background-script noise, not an EditDB application error.
