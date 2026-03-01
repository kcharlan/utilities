# jtree Code Audit — 2026-03-01

## Assumptions

- **Language**: Python 3.8+ with embedded React 18 SPA (JSX via Babel Standalone, Tailwind via CDN)
- **Architecture**: Single-file self-bootstrapping Python script (~3,455 lines); FastAPI backend serving REST API + HTML template
- **Deployment**: Local-only tool, single user, bound to `127.0.0.1`
- **Scale**: Files up to 50 MB; single concurrent user per server instance
- **API Stability**: All `/api/*` routes are internal (consumed only by the embedded SPA); no external consumers
- **Test Coverage**: 168 tests covering all 20 API endpoints plus frontend features (navigator sidebar, expand/collapse-all, minimap); test suite passes clean

---

## Findings

### [Correctness] Finding #1: XSS via Filename in HTML Template

- **Severity**: Critical
- **Category**: Correctness & Safety
- **Evidence**:
  - `jtree:619` — `return HTML_TEMPLATE.replace("{{FILE_NAME}}", fname)`
  - `jtree:922` — `<title>jtree - {{FILE_NAME}}</title>`
  - `fname` comes from `os.path.basename(json_manager.file_path)` — user-controlled via the original filename
- **Impact**:
  A JSON file named `"><script>alert(1)</script>.json` would inject arbitrary HTML/JS into the page `<title>` tag and any other location where `{{FILE_NAME}}` appears. Since the server is local-only, exploitability requires a malicious file on disk, but this is still a correctness bug that can break rendering with filenames containing `<`, `>`, `&`, or `"`.
- **Recommended Fix**:
  HTML-escape `fname` before interpolation:
  ```python
  import html

  @app.get("/", response_class=HTMLResponse)
  def serve_spa():
      fname = os.path.basename(json_manager.file_path) if json_manager else "jtree"
      safe_fname = html.escape(fname, quote=True)
      return HTML_TEMPLATE.replace("{{FILE_NAME}}", safe_fname)
  ```
- **Effort**: S
- **Risk**: Low (no behavior change for normal filenames)
- **Acceptance Criteria**:
  - Load a file named `test<b>bold</b>.json` and verify the title renders literally, not as HTML
  - Add a test: open a file with HTML-special chars in its name, assert `<script>` does not appear unescaped in the GET `/` response

---

### [Correctness] Finding #2: Dead/Unreachable `undo()` and `rename_key()` Methods on JSONManager

- **Severity**: Medium
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - `jtree:328-348` — Original `rename_key()` method stores `old_value` as a plain string (the old key name)
  - `jtree:427-481` — Original `undo()` method with a `pass` on rename undo (line 479: `pass  # Rename undo is complex; skip for now`)
  - `jtree:500-601` — These methods are monkey-patched with `_fixed_rename` and `_fixed_undo` which correctly handle rename undo/redo
  - `jtree:502` — `_original_rename = JSONManager.rename_key` is assigned but never used
- **Impact**:
  ~155 lines of dead code that confuse readers. The original `undo()` at line 427 silently does nothing for rename operations. If the monkey-patch were ever accidentally removed, rename undo would break silently.
- **Recommended Fix**:
  Delete the original `rename_key()` method (lines 328-348) and original `undo()` method (lines 427-481). Move the logic from `_fixed_rename` and `_fixed_undo` directly into the class body. Remove the `_original_rename` assignment (line 502) and the two `JSONManager.xxx = _fixed_xxx` assignments.
- **Effort**: S
- **Risk**: Low (purely structural — same code runs, just reorganized)
- **Acceptance Criteria**:
  - Full test suite still passes (151 tests)
  - No methods defined outside the class body
  - No `_original_rename` or `_fixed_*` references remain

---

### [Correctness] Finding #3: Dot-Separated Path Scheme Breaks on Keys Containing Dots

- **Severity**: Medium
- **Category**: Correctness & Safety
- **Evidence**:
  - `jtree:128` — `parts = path.split('.')`
  - All path construction uses `f"{path}.{k}"` (e.g., line 205, 212, 231, 234, 254, 265)
  - Frontend mirrors this: paths are dot-separated strings throughout the React code
- **Impact**:
  A JSON object with a key like `"my.key"` produces a path `root.my.key` which is then split into `["root", "my", "key"]`, incorrectly traversing two levels instead of one. This makes such nodes unreachable — they cannot be expanded, edited, or deleted. This affects any JSON file using dots in keys (common in Java property files, Spring configs, OpenAPI specs, etc.).
- **Recommended Fix**:
  This is a fundamental design issue. A low-risk incremental fix:
  1. Switch the path separator to a character unlikely to appear in keys (e.g., `\x00` or a multi-char delimiter like `///`)
  2. Or adopt an array-based path representation in the API (`["root", "my.key"]`) and serialize as JSON in query params

  Option 1 is simpler but still fragile. Option 2 is correct but touches every API endpoint and the entire frontend. Given this is a local tool, document the limitation for now and consider option 2 if users report issues.
- **Effort**: L (option 2) / S (document limitation)
- **Risk**: High (option 2 changes every API contract) / Low (document only)
- **Acceptance Criteria**:
  - If fixing: test with a JSON file containing keys with dots; verify all operations (expand, edit, delete, rename, search) work
  - If documenting: add note to README

---

### [Robustness] Finding #4: Recursive `_search_recursive` and `_build_subtree` Can Blow the Stack

- **Severity**: Medium
- **Category**: Robustness & Resilience
- **Evidence**:
  - `jtree:246-269` — `_search_recursive` recurses into every nested object/array
  - `jtree:223-237` — `_build_subtree` recurses to `depth` levels (max 10 via API clamp at line 713-714)
  - Python's default recursion limit is 1000
- **Impact**:
  A JSON file with nesting depth >1000 (unusual but possible with machine-generated JSON) would cause `RecursionError` crash during search. `_build_subtree` is safer because `depth` is clamped to 10, but `_search_recursive` has no depth guard.
- **Recommended Fix**:
  Add a depth parameter to `_search_recursive` with a limit:
  ```python
  def _search_recursive(self, value, path, query, search_type, results, limit, depth=0):
      if len(results) >= limit or depth > 500:
          return
      # ... existing code, passing depth=depth+1 to recursive calls
  ```
- **Effort**: S
- **Risk**: Low (only affects pathological input — deeply nested JSON)
- **Acceptance Criteria**:
  - Search on normal files works identically
  - Search on a file nested 1500 levels deep returns results (up to depth 500) without crashing

---

### [Robustness] Finding #5: `save()` and `save-as` Have No Path Validation

- **Severity**: Medium
- **Category**: Robustness & Resilience
- **Evidence**:
  - `jtree:813-820` — `api_save_as` calls `os.path.expanduser(body.path)` then `json_manager.save(resolved)` with no further validation
  - `jtree:483-498` — `save()` calls `os.path.abspath(target)` then `open(target, 'w')` directly
- **Impact**:
  Since this is a local tool accessed only from localhost, the risk is limited. However, the server will happily write to any path the process has permission for — `/etc/passwd`, `~/.ssh/authorized_keys`, etc. A browser extension or CSRF from another tab could potentially trigger `POST /api/save-as` to an arbitrary path.
- **Recommended Fix**:
  Add basic sanity checks:
  ```python
  @app.post("/api/save-as")
  def api_save_as(body: SaveAsBody):
      _require_file()
      resolved = os.path.expanduser(body.path)
      resolved = os.path.abspath(resolved)
      if not resolved.endswith('.json'):
          raise HTTPException(status_code=400, detail="Save path must end with .json")
      # ... proceed with save
  ```
- **Effort**: S
- **Risk**: Low (adds a guard; `.json` suffix check is a reasonable default for a JSON editor)
- **Acceptance Criteria**:
  - `POST /api/save-as {"path": "/tmp/test.json"}` succeeds
  - `POST /api/save-as {"path": "/tmp/test.txt"}` returns 400
  - Add tests for both cases

---

### [Correctness] Finding #6: `serve_spa` Crashes When File Loaded via `open-content` (No `file_path`)

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - `jtree:617-619`:
    ```python
    def serve_spa():
        fname = os.path.basename(json_manager.file_path) if json_manager else "jtree"
    ```
  - `jtree:112-113` — `from_content()` sets `instance.file_path = None` and `instance.display_name = file_name`
- **Impact**:
  When a user uploads JSON via the browser (using `/api/open-content`), `json_manager` is not `None` but `json_manager.file_path` is `None`. Calling `os.path.basename(None)` raises `TypeError: expected str, bytes or os.PathLike object, not NoneType`. Any page refresh after a browser upload crashes the SPA endpoint.
- **Recommended Fix**:
  ```python
  @app.get("/", response_class=HTMLResponse)
  def serve_spa():
      if json_manager:
          fname = getattr(json_manager, 'display_name', None) or (
              os.path.basename(json_manager.file_path) if json_manager.file_path else "jtree"
          )
      else:
          fname = "jtree"
      safe_fname = html.escape(fname, quote=True)
      return HTML_TEMPLATE.replace("{{FILE_NAME}}", safe_fname)
  ```
  This reuses the same `display_name` fallback logic already present in `api_status()` (line 634).
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - Open content via `/api/open-content`, then GET `/` — no crash, correct filename in title
  - Add test: `client.post("/api/open-content", ...)` then `client.get("/")` returns 200

---

### [Robustness] Finding #7: `_push_undo` Pops from Front of List — O(n) on Every Mutation

- **Severity**: Low
- **Category**: Performance/Efficiency
- **Evidence**:
  - `jtree:279` — `self.undo_stack.pop(0)` when stack exceeds `max_undo` (50)
- **Impact**:
  `list.pop(0)` is O(n) because Python shifts all remaining elements. With `max_undo=50` this is negligible, but it's an easy fix using `collections.deque`:
  ```python
  from collections import deque
  self.undo_stack = deque(maxlen=50)
  ```
  This automatically discards the oldest entry and all operations are O(1).
- **Recommended Fix**:
  Replace both `undo_stack` and `redo_stack` lists with `deque`. The `redo_stack` doesn't need `maxlen` since it's cleared on new mutations and bounded by undo stack size.
- **Effort**: S
- **Risk**: Low (behavioral equivalent; `deque` supports `append`, `pop`, `len`, iteration)
- **Acceptance Criteria**:
  - All tests pass
  - Undo/redo still works correctly with 50+ mutations

---

### [Correctness] Finding #8: `redo` for Delete Operation Does Not Correctly Re-delete

- **Severity**: Medium
- **Category**: Correctness & Safety
- **Evidence**:
  - `jtree:394-400` — In the `redo()` method, the `delete` case:
    ```python
    elif op == "delete":
        parent, key, old = self._resolve_path(path)
        self.undo_stack.append({"op": "delete", "path": path, "old_value": copy.deepcopy(old)})
        if isinstance(parent, dict):
            del parent[key]
        elif isinstance(parent, list):
            parent.pop(key)
    ```
  - `jtree:565` — In `_fixed_undo`, delete undo sets `redo_entry["forward"] = None`
- **Impact**:
  The delete redo path resolves the path fresh and re-deletes, which is correct. However, it ignores the `fwd` value (which is `None`). This works by coincidence but is fragile — if the undo had failed or partially applied, the redo could delete the wrong node. The logic is correct for the current flow but the `forward = None` sentinel is misleading.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Existing undo/redo tests pass; add a test: add child, undo, redo, undo, redo verifies data integrity at each step

---

### [Maintainability] Finding #9: Global Mutable State (`json_manager`) Without Encapsulation

- **Severity**: Low
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - `jtree:607` — `json_manager: Optional[JSONManager] = None` as module global
  - `jtree:655,676,3425` — `global json_manager` used in 3 functions
  - All API handlers access `json_manager` as a module global
- **Impact**:
  Makes testing harder (requires `autouse` fixture to reset state) and prevents running multiple instances in-process. For a single-user local tool this is acceptable, but encapsulating state in an `AppState` object or using FastAPI's dependency injection would improve testability.
- **Recommended Fix**:
  Low priority. If refactoring, wrap in a class or use `app.state`:
  ```python
  app.state.json_manager = None
  ```
  This is a larger refactor and optional.
- **Effort**: M
- **Risk**: Medium (touches every endpoint)
- **Acceptance Criteria**: All tests pass; `global json_manager` no longer appears in codebase

---

### [Maintainability] Finding #10: Missing `.gitignore` in Project Directory

- **Severity**: Low
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - No `.gitignore` exists in `/Users/kevinharlan/source/utilities/jtree/`
  - The parent repo's `.gitignore` covers `venv/`, `__pycache__/`, `.coverage` etc.
  - `.DS_Store` and `.coverage` are present on disk but excluded by parent rules
- **Impact**:
  Relies entirely on the parent `.gitignore`. If this project is ever extracted to its own repo, these files would be committed. Low risk given the monorepo context.
- **Recommended Fix**:
  Optional — add a local `.gitignore`:
  ```
  venv/
  __pycache__/
  .coverage
  .pytest_cache/
  .DS_Store
  ```
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: `git status` still clean after adding

---

## Implementation Plan

### Phase 1: Critical/High Severity Fixes

**Step 1: Fix XSS in `serve_spa` and crash on browser-uploaded files (Findings #1, #6)**
- **Files to modify**: `jtree:1-3` (add `import html`), `jtree:616-619` (rewrite `serve_spa`)
- **Changes**:
  ```python
  import html  # add to imports section after 'import json'

  @app.get("/", response_class=HTMLResponse)
  def serve_spa():
      if json_manager:
          fname = getattr(json_manager, 'display_name', None) or (
              os.path.basename(json_manager.file_path) if json_manager.file_path else "jtree"
          )
      else:
          fname = "jtree"
      safe_fname = html.escape(fname, quote=True)
      return HTML_TEMPLATE.replace("{{FILE_NAME}}", safe_fname)
  ```
- **Commands**:
  ```bash
  source venv/bin/activate && python -m pytest tests/ -q
  ```
- **Expected result**: All tests pass
- **Stop condition**: If tests fail, check that `html.escape` is imported correctly

**Step 2: Add tests for XSS and open-content filename handling**
- **Files to modify**: `tests/test_api.py`
- **Changes**: Add tests in `TestServeSPA`:
  - Test that opening a file with `<script>` in name does not produce unescaped HTML
  - Test that after `/api/open-content`, GET `/` returns 200 with the display name
- **Commands**:
  ```bash
  source venv/bin/activate && python -m pytest tests/test_api.py -q
  ```
- **Expected result**: New tests pass

### Phase 2: Medium Severity Fixes

**Step 3: Add recursion depth guard to `_search_recursive` (Finding #4)**
- **Files to modify**: `jtree:246` (add `depth=0` parameter), `jtree:260,269` (pass `depth+1`)
- **Changes**:
  ```python
  def _search_recursive(self, value, path, query, search_type, results, limit, depth=0):
      if len(results) >= limit or depth > 500:
          return
      # ... in recursive calls, add depth=depth+1
  ```
- **Commands**:
  ```bash
  source venv/bin/activate && python -m pytest tests/ -q
  ```
- **Expected result**: All tests pass

**Step 4: Add `.json` suffix check to save-as endpoint (Finding #5)**
- **Files to modify**: `jtree:813-820`
- **Changes**:
  ```python
  @app.post("/api/save-as")
  def api_save_as(body: SaveAsBody):
      _require_file()
      resolved = os.path.expanduser(body.path)
      resolved = os.path.abspath(resolved)
      if not resolved.endswith('.json'):
          raise HTTPException(status_code=400, detail="Save path must end with .json")
      try:
          json_manager.save(resolved)
          return {"ok": True}
      except OSError as e:
          raise HTTPException(status_code=500, detail=str(e))
  ```
- **Commands**:
  ```bash
  source venv/bin/activate && python -m pytest tests/ -q
  ```
- **Expected result**: All tests pass (existing save-as tests use `.json` paths)
- **Stop condition**: If existing tests fail, check if any test uses a non-`.json` path

**Step 5: Remove dead code — consolidate monkey-patched methods into class (Finding #2)**
- **Files to modify**: `jtree:328-348` (delete original `rename_key`), `jtree:427-481` (delete original `undo`), `jtree:500-601` (move `_fixed_rename`/`_fixed_undo` logic into the class, remove monkey-patch assignments)
- **Changes**: Move the bodies of `_fixed_rename` and `_fixed_undo` to replace the original `rename_key` and `undo` methods within the `JSONManager` class. Delete lines 500-601 (the external overrides).
- **Commands**:
  ```bash
  source venv/bin/activate && python -m pytest tests/ -q
  ```
- **Expected result**: All tests pass
- **Stop condition**: If tests fail, verify method signatures match exactly

### Phase 3: Low Severity / Optional Improvements

> **OPTIONAL** — Only proceed if Phase 1-2 complete and time permits

**Step 6: Replace undo/redo stacks with `deque` (Finding #7)**
- **Files to modify**: `jtree` — add `from collections import deque`, replace `self.undo_stack: list = []` with `self.undo_stack = deque(maxlen=50)`, replace `self.redo_stack: list = []` with `self.redo_stack = deque()`. Remove the `pop(0)` guard in `_push_undo`. Also update `from_content` similarly.
- **Commands**:
  ```bash
  source venv/bin/activate && python -m pytest tests/ -q
  ```
- **Expected result**: All tests pass
- **Stop condition**: If `deque` doesn't support an operation used elsewhere (e.g., indexed access), fall back to list

**Step 7: Document dots-in-keys limitation (Finding #3)**
- **Files to modify**: `README.md`
- **Changes**: Add a "Known Limitations" section noting that JSON keys containing `.` characters cannot be navigated correctly.
- **Effort**: S
- **Risk**: Low

**Step 8: Add local `.gitignore` (Finding #10)**
- **Files to create**: `.gitignore`
- **Content**:
  ```
  venv/
  __pycache__/
  .coverage
  .pytest_cache/
  .DS_Store
  ```
