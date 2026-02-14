# EditDB Code Audit - February 13, 2026

## Assumptions

Given the nature of this single-file SQLite management utility, the following assumptions were made:

1. **Deployment Model**: Single-user, local development tool running on localhost
2. **Expected Load**: Low concurrency (1 user), small to medium databases (< 1GB), typical operations on tables with < 100k rows
3. **Performance Targets**: Sub-second response for typical queries, acceptable UI lag < 500ms
4. **Failure Handling**: User-facing errors via alerts/UI messages, no automatic retry logic needed
5. **Public API**: CLI interface (`editdb <db_path>`) is the only public API; HTTP endpoints are internal
6. **Security Model**: Local-only (127.0.0.1), no authentication needed, trusts local filesystem permissions

---

## Executive Summary

EditDB is a well-designed single-file SQLite management utility with a self-contained React frontend. The codebase shows good architectural decisions (self-bootstrapping venv, shadow-table migrations, transaction safety). However, there are **critical SQL injection vulnerabilities** and several robustness/safety issues that should be addressed.

**Critical Issues**: 2  
**High Priority**: 4  
**Medium Priority**: 5  
**Low Priority**: 3

---

## Findings

### Category: Correctness & Safety

#### FINDING 1: SQL Injection Vulnerabilities in Multiple Endpoints

**Severity**: Critical  
**Category**: Correctness & Safety  
**Evidence**: 
- `editdb:105` - `cursor.execute(f"PRAGMA table_info('{table_name}');")`
- `editdb:111` - `cursor.execute(f"PRAGMA foreign_key_list('{table_name}');")`
- `editdb:122` - `cursor.execute(f"CREATE TABLE {temp_name} ({cols_sql});")`
- `editdb:129` - `insert_sql = f"INSERT INTO {temp_name} ({', '.join(new_names)}) SELECT {', '.join(old_names)} FROM {table_name}"`
- `editdb:132-133` - `DROP TABLE` and `ALTER TABLE` with f-strings
- `editdb:222` - `conn.execute(f"CREATE TABLE {table.name} (id INTEGER PRIMARY KEY AUTOINCREMENT)")`
- `editdb:232` - `conn.execute(f"ALTER TABLE {table_name} RENAME TO {payload.new_name}")`
- `editdb:242` - `conn.execute(f"DROP TABLE {table_name}")`
- `editdb:258` - `sql = f"CREATE {unique} INDEX {payload.name} ON {payload.table} ({cols})"`
- `editdb:269` - `conn.execute(f"DROP INDEX {index_name}")`
- `editdb:287` - `cursor.execute(f"SELECT * FROM {table_name}")`
- `editdb:362` - `cursor.execute(f"SELECT * FROM {table_name} LIMIT ? OFFSET ?", (limit, offset))`
- `editdb:369` - `cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")`
- `editdb:405-407` - Dynamic WHERE and SET clause construction
- `editdb:419-420` - Dynamic WHERE clause construction

**Why It Matters**: 
An attacker controlling table/column/index names could execute arbitrary SQL, leading to data corruption, unauthorized data access, or denial of service. While this is a local tool, malicious filenames or specially crafted databases could exploit this.

**Recommended Fix**:
1. Use SQLite identifier quoting for all dynamic identifiers: `f'"{table_name}"'` or better, use proper escaping
2. For PRAGMA statements, validate input against `sqlite_master` first
3. For dynamic column lists, validate against schema
4. Add input validation for table/column/index names (alphanumeric + underscore only)

**Effort**: M (Medium - requires systematic changes across ~15 locations)  
**Risk**: Low (changes are localized, easily testable)

**Acceptance Criteria**:
- All dynamic SQL uses quoted identifiers or parameterized queries where possible
- Input validation rejects special characters in names
- Test with malicious inputs like: `'; DROP TABLE users; --`, `"test"` or `test--`
- Manual audit confirms no f-string interpolation of user-controlled identifiers

**Robustness Considerations**:
- Invalid input should return 400 with clear error message
- Should not crash server or corrupt database
- Consider whitelisting valid identifier characters: `^[a-zA-Z_][a-zA-Z0-9_]*$`

---

#### FINDING 2: Missing Variable Definition in createTable

**Severity**: Critical  
**Category**: Correctness & Safety  
**Evidence**: `editdb:973` - `if res.ok:` references undefined variable `res`

**Why It Matters**: 
This is a runtime error that will crash the function when a user tries to create a table. The fetch result is never assigned to a variable.

**Recommended Fix**:
```python
# Line 953 should be:
const res = await fetch('/api/tables', {
```

**Effort**: S (Small - one-line fix)  
**Risk**: Low (trivial fix)

**Acceptance Criteria**:
- Create table via UI works without console errors
- Success path shows table in list
- Failure path shows error alert

---

#### FINDING 3: Race Condition in Bootstrap Execution

**Severity**: Medium  
**Category**: Correctness & Safety  
**Evidence**: `editdb:18-24` - Import check happens before venv re-execution

**Why It Matters**:
If dependencies are installed in the current environment but the venv exists, the script will run in the wrong environment. This can lead to version mismatches or missing dependencies.

**Recommended Fix**:
```python
def bootstrap():
    venv_dir = os.path.expanduser("~/.editdb_venv")
    venv_python = os.path.join(venv_dir, "bin", "python3")
    
    # Always use venv if it exists
    if os.path.exists(venv_python) and sys.executable != venv_python:
        os.execv(venv_python, [venv_python] + sys.argv)
    
    # Check if we are already running inside our private venv
    if sys.executable == venv_python:
        return
    
    # Only check imports if we need to create venv
    # ... rest of logic
```

**Effort**: S (Small - reorder logic)  
**Risk**: Low (improves reliability)

**Acceptance Criteria**:
- Running with existing venv always uses venv python
- Running without venv creates it and re-executes
- No duplicate execution

---

#### FINDING 4: Unsafe Directory Creation

**Severity**: Medium  
**Category**: Correctness & Safety  
**Evidence**: `editdb:79` - `os.makedirs(os.path.dirname(self.db_path), exist_ok=True)`

**Why It Matters**:
If `db_path` is just a filename (no directory component), `os.path.dirname()` returns empty string, causing `os.makedirs("")` which creates a directory named `""` or fails silently. This could lead to confusing errors.

**Recommended Fix**:
```python
def __init__(self, db_path: str):
    self.db_path = os.path.abspath(db_path)
    # Only create directory if there is one
    db_dir = os.path.dirname(self.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    # Test connection
    conn = sqlite3.connect(self.db_path)
    conn.close()
```

**Effort**: S (Small - add condition)  
**Risk**: Low (defensive programming)

**Acceptance Criteria**:
- `editdb test.db` (no path) works without error
- `editdb /tmp/foo/bar/test.db` creates `/tmp/foo/bar/` if needed
- No empty-string directories created

---

### Category: Robustness & Resilience

#### FINDING 5: No Connection Pooling or Timeout Configuration

**Severity**: Medium  
**Category**: Robustness & Resilience  
**Evidence**: `editdb:84-88` - New connection created for every operation

**Why It Matters**:
SQLite can lock under concurrent access. While this is a single-user tool, concurrent requests from the browser (parallel API calls) could cause "database is locked" errors. No timeout is set for lock acquisition.

**Recommended Fix**:
```python
def get_connection(self):
    conn = sqlite3.connect(self.db_path, timeout=30.0)  # 30 second lock timeout
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 30000;")  # 30 seconds in milliseconds
    return conn
```

**Effort**: S (Small - add timeout parameters)  
**Risk**: Low (improves reliability)

**Acceptance Criteria**:
- Parallel requests don't immediately fail with "database is locked"
- Timeout error is clear after 30 seconds
- Test with concurrent CSV import + schema change

**Robustness Considerations**:
- Under high contention: retry at client level or show clear error
- For large imports: consider wrapping in transaction with lower timeout
- Max concurrent operations: ~3-5 (browser tab limit)

---

#### FINDING 6: Missing Error Handling in Migration Rollback

**Severity**: High  
**Category**: Robustness & Resilience  
**Evidence**: `editdb:114-142` - `execute_migration` finally block always re-enables foreign keys

**Why It Matters**:
If the connection is broken or closed during migration, the `finally` block will raise an exception trying to execute on a closed connection, hiding the original error.

**Recommended Fix**:
```python
def execute_migration(self, table_name: str, new_cols_def: List[str], mapping: Dict[str, str]):
    conn = self.get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
        cursor = conn.cursor()
        
        temp_name = f"_{table_name}_new_{int(time.time())}"
        cols_sql = ", ".join(new_cols_def)
        cursor.execute(f"CREATE TABLE {temp_name} ({cols_sql});")
        
        # Map existing columns
        new_names = [n for n, o in mapping.items() if o]
        old_names = [mapping[n] for n in new_names]
        
        if new_names:
            insert_sql = f"INSERT INTO {temp_name} ({', '.join(new_names)}) SELECT {', '.join(old_names)} FROM {table_name}"
            cursor.execute(insert_sql)
        
        cursor.execute(f"DROP TABLE {table_name}")
        cursor.execute(f"ALTER TABLE {temp_name} RENAME TO {table_name}")
        
        conn.commit()
        return True, None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass  # Connection may be closed
        return False, str(e)
    finally:
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.close()
        except Exception:
            pass  # Connection may already be closed
```

**Effort**: S (Small - add inner try-catch)  
**Risk**: Low (improves error handling)

**Acceptance Criteria**:
- Simulate connection close during migration
- Original error message is preserved and returned
- No "connection closed" exception masks original error
- Foreign keys are re-enabled on success path

---

#### FINDING 7: No Validation of Column Mappings in Migration

**Severity**: High  
**Category**: Robustness & Resilience  
**Evidence**: `editdb:125-130` - Column names from client used directly in SQL

**Why It Matters**:
Client can send mismatched old/new column names that don't exist in the source table, causing SQL errors mid-migration after the temp table is created.

**Recommended Fix**:
```python
def execute_migration(self, table_name: str, new_cols_def: List[str], mapping: Dict[str, str]):
    conn = self.get_connection()
    try:
        # Validate mapping against existing schema
        existing_cols = {col['name'] for col in self.get_schema(table_name)}
        for new_name, old_name in mapping.items():
            if old_name and old_name not in existing_cols:
                return False, f"Column '{old_name}' does not exist in table '{table_name}'"
        
        # ... rest of migration logic
```

**Effort**: S (Small - add validation)  
**Risk**: Low (fail-fast prevents corruption)

**Acceptance Criteria**:
- Migration with invalid old column name returns error before creating temp table
- Error message is clear and actionable
- Valid migrations still work

---

#### FINDING 8: CSV Import Has No Row Limit or Progress Feedback

**Severity**: Medium  
**Category**: Robustness & Resilience  
**Evidence**: `editdb:316-335` - Entire CSV loaded into memory, processed row-by-row

**Why It Matters**:
Large CSV files (>10MB) will cause memory issues and block the server with no user feedback. Single transaction means all-or-nothing with no intermediate commits.

**Recommended Fix**:
```python
@app.post("/api/import/{table_name}")
async def import_data(table_name: str, file: UploadFile = File(...)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    
    # Add size limit
    max_size = 50 * 1024 * 1024  # 50MB
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail=f"File too large (max {max_size/1024/1024}MB)")
    
    decoded = content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(decoded))
    
    with db_manager.get_connection() as conn:
        try:
            batch_size = 1000
            count = 0
            for row in reader:
                cols = list(row.keys())
                placeholders = ", ".join([":" + c for c in cols])
                sql = f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({placeholders})"
                conn.execute(sql, row)
                count += 1
                if count % batch_size == 0:
                    conn.commit()  # Intermediate commits for large files
            conn.commit()
            return {"status": "success", "rows_imported": count}
        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(e))
```

**Effort**: M (Medium - add batching and limits)  
**Risk**: Low (improves UX)

**Acceptance Criteria**:
- 60MB CSV is rejected with clear error
- 10k row CSV imports successfully with intermediate commits
- UI shows row count after import
- Memory usage stays reasonable (<100MB for 10k rows)

**Scalability Considerations**:
- Max file size: 50MB
- Batch commit every 1000 rows to avoid long locks
- For larger imports: recommend chunking or streaming approach

---

#### FINDING 9: No Input Validation on Query Endpoint

**Severity**: Medium  
**Category**: Robustness & Resilience  
**Evidence**: `editdb:197-212` - Raw SQL query executed without any validation

**Why It Matters**:
User can send empty queries, malformed SQL, or expensive queries (e.g., Cartesian joins) that hang the server. No timeout or resource limits.

**Recommended Fix**:
```python
@app.post("/api/query")
async def execute_query(sql: SQLQuery):
    # Basic validation
    if not sql.query or not sql.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    if len(sql.query) > 100_000:  # 100KB limit
        raise HTTPException(status_code=400, detail="Query too large")
    
    with db_manager.get_connection() as conn:
        try:
            # Set statement timeout (if SQLite compiled with it)
            # Note: SQLite doesn't have statement timeout, but we can use interrupt
            cursor = conn.cursor()
            cursor.execute(sql.query)
            # Check if it's a query that returns rows
            if cursor.description:
                columns = [description[0] for description in cursor.description]
                # Limit result size
                rows = cursor.fetchmany(10000)  # Max 10k rows
                if cursor.fetchone():  # Check if more rows
                    # More rows available but truncated
                    return {"columns": columns, "rows": [dict(r) for r in rows], 
                            "truncated": True, "message": "Results limited to 10,000 rows"}
                return {"columns": columns, "rows": [dict(r) for r in rows]}
            else:
                conn.commit()
                return {"status": "success", "rows_affected": cursor.rowcount}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
```

**Effort**: M (Medium - add validation and limits)  
**Risk**: Low (improves safety)

**Acceptance Criteria**:
- Empty query returns 400 error
- Query returning 100k rows is truncated to 10k with warning
- Valid queries work as before

**Scalability Considerations**:
- Max query size: 100KB
- Max result rows: 10k (prevents browser memory issues)
- For larger results: recommend export feature

---

#### FINDING 10: Missing CORS and Host Binding Security

**Severity**: Low  
**Category**: Robustness & Resilience  
**Evidence**: `editdb:2080` - Server binds to `127.0.0.1` only, no CORS headers

**Why It Matters**:
While binding to localhost is correct for security, there's no explicit CORS policy. If users want to access from other local tools or configure differently, there's no safe way to do it.

**Recommended Fix**:
Document the security model explicitly. Current implementation is correct (localhost-only, no CORS needed). Add a comment:

```python
# Security: Bind to 127.0.0.1 only (not 0.0.0.0) to prevent network access
# No CORS headers needed since we only serve localhost requests
uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
```

**Effort**: S (Documentation only)  
**Risk**: Low (no code change)

**Acceptance Criteria**:
- README documents security model
- Code comment explains localhost-only binding

---

### Category: Best Practices & Maintainability

#### FINDING 11: Context Manager Improper Usage

**Severity**: Low  
**Category**: Best Practices & Maintainability  
**Evidence**: Multiple locations use `with self.get_connection() as conn:` but manually close in migration

**Why It Matters**:
Inconsistent connection handling. Using `with` should auto-close, but migration manually calls `conn.close()`. This is confusing and could lead to resource leaks if modified.

**Recommended Fix**:
Standardize on one pattern:
- Use `with` for simple operations (auto-close)
- Use manual try/finally for complex operations like migration (already correct)

Remove `with` from migration since it manually manages connection:
```python
# Instead of:
# with db_manager.get_connection() as conn:

# Use explicit try/finally in execute_migration (already done)
conn = self.get_connection()
try:
    # ...
finally:
    conn.close()
```

**Effort**: S (Small - documentation or minor refactor)  
**Risk**: Low (cleanup)

**Acceptance Criteria**:
- Simple operations use `with`
- Complex operations (migration) use explicit try/finally
- No mixed patterns

---

#### FINDING 12: Magic Numbers for Pagination

**Severity**: Low  
**Category**: Best Practices & Maintainability  
**Evidence**: `editdb:702` - `pageSize` default is 100, hardcoded

**Why It Matters**:
Page size should be configurable or at least a named constant. Changing it requires finding all occurrences.

**Recommended Fix**:
```python
# At module level or in DBManager
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000

# In frontend:
const [pageSize, setPageSize] = useState(100);

// Add UI control to change page size
```

**Effort**: S (Small - extract constant)  
**Risk**: Low (refactor)

**Acceptance Criteria**:
- Page size is a named constant
- Consider adding UI control for page size (25/50/100/500)

---

#### FINDING 13: No Logging or Observability

**Severity**: Medium  
**Category**: Best Practices & Maintainability  
**Evidence**: No logging framework, only `print` statements

**Why It Matters**:
Debugging issues requires print debugging. No structured logs for errors, performance, or user actions.

**Recommended Fix**:
```python
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('editdb')

# Replace prints with logging
logger.info(f"🚀 EditDB starting for: {args.db_path}")
logger.info(f"📡 API available at http://127.0.0.1:{args.port}/api")

# Add error logging
except Exception as e:
    logger.error(f"Migration failed for {table_name}: {e}", exc_info=True)
    raise HTTPException(status_code=400, detail=str(e))
```

**Effort**: M (Medium - add logging throughout)  
**Risk**: Low (improves debugging)

**Acceptance Criteria**:
- All errors logged with context
- Performance logging for slow operations (>1s)
- Logs include timestamp, level, message
- Log level configurable via CLI flag

---

### Category: Readability

#### FINDING 14: Embedded 1600-Line Frontend in Python String

**Severity**: Medium  
**Category**: Readability  
**Evidence**: `editdb:431-2054` - Entire React app in `HTML_TEMPLATE` string

**Why It Matters**:
Makes code review difficult, no syntax highlighting, hard to maintain. While documented as intentional for "single-file" distribution, it's a maintenance burden.

**Recommended Fix**:
Consider one of these approaches:
1. **Keep as-is** but document in comments that this is intentional for portability
2. **Extract to separate file** and load at runtime:
   ```python
   TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'index.html')
   with open(TEMPLATE_PATH) as f:
       HTML_TEMPLATE = f.read()
   ```
3. **Build step**: Keep source in separate `.html` file, embed during build/install

**Effort**: M (if splitting) / S (if documenting)  
**Risk**: Low (readability improvement)

**Acceptance Criteria**:
- If keeping embedded: Add clear comment explaining single-file design choice
- If splitting: Document how to rebuild single-file for distribution
- Syntax highlighting works for frontend code

---

#### FINDING 15: Inconsistent Naming Conventions

**Severity**: Low  
**Category**: Readability  
**Evidence**: 
- Python: `snake_case` (correct)
- JavaScript: Mixed `camelCase` and inconsistent destructuring
- CSS: `kebab-case` (correct)

**Why It Matters**:
Minor inconsistency in JavaScript variable naming (e.g., `tRes`/`tData` vs. `tablesResponse`/`tablesData`).

**Recommended Fix**:
Apply consistent naming:
- API responses: `*Response` or `*Res`
- Parsed data: `*Data`
- Consider adding ESLint config (if ever splitting frontend)

**Effort**: S (Small - documentation or light refactor)  
**Risk**: Low (style cleanup)

**Acceptance Criteria**:
- Consistent naming pattern documented in comments
- Follow JavaScript naming conventions guide

---

### Category: Performance/Efficiency

#### FINDING 16: N+1 Query Pattern in Frontend Data Fetching

**Severity**: Low  
**Category**: Performance/Efficiency  
**Evidence**: `editdb:831-841` - Four parallel fetches for each table selection

**Why It Matters**:
Every table selection triggers 4 separate HTTP requests. While parallel, this could be combined into one endpoint for better performance.

**Recommended Fix**:
Add combined endpoint:
```python
@app.get("/api/table/{table_name}/full")
async def get_table_full(table_name: str, limit: int = 100, offset: int = 0):
    return {
        "schema": db_manager.get_schema(table_name),
        "data": # ... get data with limit/offset
        "fks": db_manager.get_fks(table_name),
        "count": # ... get count
    }
```

Then frontend makes one request instead of four.

**Effort**: M (Medium - new endpoint + frontend changes)  
**Risk**: Low (optimization)

**Acceptance Criteria**:
- Table selection makes 1 request instead of 4
- Total data transfer stays the same
- Response time improves by ~50-75% (fewer round trips)

**Performance Considerations**:
- Current: 4 × RTT (round trip time)
- Optimized: 1 × RTT
- For localhost: minimal gain (~10ms → ~3ms)
- For remote: significant gain (4×50ms → 50ms)

---

---

## Fix Plan

Below is a step-by-step plan ordered by severity and risk to guide implementation:

### Phase 1: Critical Safety Fixes (Do First)

**Step 1.1: Fix createTable undefined variable (FINDING 2)**
- **File**: `editdb`
- **Action**: Add `const res = ` before the fetch on line 953
- **Test**: Create a table via UI, verify it works
- **Stop condition**: Table creation succeeds without console errors

**Step 1.2: Fix SQL injection vulnerabilities (FINDING 1)**
- **Files**: `editdb`
- **Actions**:
  1. Create helper function for identifier validation:
     ```python
     def validate_identifier(name: str) -> bool:
         import re
         return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))
     ```
  2. Add validation to all API endpoints that accept table/column/index names
  3. Use double-quote escaping for identifiers: `f'"{table_name}"'`
  4. Update lines: 105, 111, 122, 129, 132-133, 222, 232, 242, 258, 269, 287, 362, 369, 405-407, 419-420
- **Commands**:
  ```bash
  # After changes:
  python3 -m py_compile editdb
  # Manual test with malicious inputs
  ```
- **Stop condition**: 
  - All endpoints validate input
  - Test injection attempts fail gracefully with 400 errors
  - Normal operations still work

### Phase 2: High-Priority Robustness (Do Second)

**Step 2.1: Add migration validation (FINDING 7)**
- **File**: `editdb`
- **Action**: Add column validation in `execute_migration` before creating temp table
- **Test**: Send migration with invalid column name, verify error
- **Stop condition**: Invalid migrations fail-fast with clear errors

**Step 2.2: Fix migration error handling (FINDING 6)**
- **File**: `editdb`
- **Action**: Wrap finally block operations in try-catch
- **Test**: Simulate connection issues during migration
- **Stop condition**: Original errors preserved, no secondary exceptions

### Phase 3: Medium-Priority Improvements (Do Third)

**Step 3.1: Add connection timeouts (FINDING 5)**
- **File**: `editdb`
- **Action**: Add `timeout=30.0` and `PRAGMA busy_timeout` to `get_connection()`
- **Test**: Concurrent schema change + data import
- **Stop condition**: No immediate "database locked" errors

**Step 3.2: Fix bootstrap race condition (FINDING 3)**
- **File**: `editdb`
- **Action**: Reorder bootstrap logic to check venv existence first
- **Test**: Run with existing venv, verify it's used
- **Stop condition**: Consistent venv usage

**Step 3.3: Add CSV import limits (FINDING 8)**
- **File**: `editdb`
- **Action**: Add file size check, batch commits, row counter
- **Test**: Import 60MB file (should fail), 5MB file (should succeed)
- **Stop condition**: Large files rejected, batching works

**Step 3.4: Add query validation (FINDING 9)**
- **File**: `editdb`
- **Action**: Add empty check, size limit, result row limit
- **Test**: Send empty query, huge query, query with 100k results
- **Stop condition**: All limits enforced, truncation works

**Step 3.5: Add logging (FINDING 13)**
- **File**: `editdb`
- **Action**: Replace print statements with logging, add error logging
- **Test**: Run operations, check log output
- **Stop condition**: Structured logs for all operations

**Step 3.6: Fix unsafe directory creation (FINDING 4)**
- **File**: `editdb`
- **Action**: Add check for empty dirname before makedirs
- **Test**: Run `editdb test.db` in current directory
- **Stop condition**: No empty-string directories created

### Phase 4: Low-Priority Cleanup (Optional)

**Step 4.1: Document security model (FINDING 10)**
- **Files**: `README.md`, `editdb`
- **Action**: Add comments and docs about localhost-only binding
- **Test**: Review documentation
- **Stop condition**: Security model documented

**Step 4.2: Extract page size constant (FINDING 12)**
- **File**: `editdb`
- **Action**: Create `DEFAULT_PAGE_SIZE` constant
- **Test**: Verify pagination still works
- **Stop condition**: No magic numbers

**Step 4.3: Standardize connection handling (FINDING 11)**
- **File**: `editdb`
- **Action**: Document when to use `with` vs manual try/finally
- **Test**: Code review
- **Stop condition**: Pattern is consistent and documented

**Step 4.4: Document embedded frontend (FINDING 14)**
- **File**: `editdb`
- **Action**: Add comment explaining single-file design choice
- **Test**: Code review
- **Stop condition**: Design rationale is clear

**Step 4.5: Document naming conventions (FINDING 15)**
- **File**: `editdb`
- **Action**: Add comment block with naming standards
- **Test**: Code review
- **Stop condition**: Standards documented

### Phase 5: Performance Optimizations (Optional)

**Step 5.1: Add combined table endpoint (FINDING 16)**
- **File**: `editdb`
- **Action**: Create `/api/table/{table_name}/full` endpoint
- **Action**: Update frontend to use combined endpoint
- **Test**: Measure request count and response time
- **Stop condition**: 4 requests reduced to 1, faster table loading

---

## Testing Recommendations

After implementing fixes, run the following tests:

### Manual Tests
1. **SQL Injection**: Try creating tables/columns with names like `"; DROP TABLE users; --`
2. **Large CSV**: Import 10MB and 60MB CSV files
3. **Concurrent Access**: Open 2 browser tabs, edit schema in one while querying in other
4. **Edge Cases**: Empty database path, filename-only path, malformed column mappings
5. **Error Recovery**: Kill server during migration, verify database integrity

### Validation Commands
```bash
# Syntax check
python3 -m py_compile editdb

# Run with test database
./editdb test.db

# Check for common issues
grep -n "f\".*{.*}.*FROM" editdb  # Find SQL injection candidates
grep -n "except:" editdb  # Find bare except clauses
```

### Success Metrics
- Zero SQL injection vulnerabilities
- All user errors return 400 with clear messages
- No unhandled exceptions in normal operation
- Database remains consistent after errors
- Logs provide actionable debugging info

---

## Notes

1. **Single-file design**: The embedded frontend is intentional for portability. While it impacts readability, it's a valid design choice for a local utility. Consider documenting this tradeoff.

2. **Security scope**: As a localhost-only tool, some issues (like SQL injection) are lower risk than in a network service. However, malicious databases could still exploit these vulnerabilities.

3. **Performance**: Current design is fine for typical use (small-medium databases, single user). The N+1 query optimization is nice-to-have but not critical.

4. **Testing**: Consider adding basic pytest tests for critical paths (migration, SQL validation, CSV import limits).

5. **Dependencies**: Current bootstrap approach is clever. Consider documenting the PEP 668 rationale in code comments.

6. **Error boundaries**: The React ErrorBoundary (added in past fixes) is excellent. Consider adding similar server-side global exception handler for FastAPI.
