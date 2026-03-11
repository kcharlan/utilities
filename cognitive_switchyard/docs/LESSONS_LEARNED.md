# Lessons Learned

## YAML Parsing In A Homebrew Python Environment

- What went wrong: Early validation ran outside the project venv, which hid the real dependency path and pushed the implementation toward environment-specific workarounds.
- Pattern that caused it: Assuming the shell's default Python and `pytest` entrypoint were the runtime of record.
- Pattern to follow instead: Build and validate through the project venv, and keep the runtime bootstrap path aligned with that same dependency set.

## Plan Metadata With Numeric IDs

- What went wrong: YAML loaders can coerce `PLAN_ID: 001` into an integer, which silently strips leading zeroes and breaks task-file matching.
- Pattern that caused it: Using a default YAML loader for identifier-like metadata.
- Pattern to follow instead: Treat plan IDs as strings during parsing and preserve the source representation end-to-end.

## SQLite Access Across The API Thread And Orchestrator Thread

- What went wrong: The web server and background orchestrator share the same SQLite file, and default connection settings were too strict for that access pattern.
- Pattern that caused it: Using thread-local SQLite defaults in a multi-threaded design.
- Pattern to follow instead: Use WAL mode plus a thread-safe connection configuration, and keep the filesystem as the recoverable source of truth.

## Error Handling In Modules Without A Logger

- What went wrong: Adding a `_logger.exception()` call in `orchestrator.py` failed at runtime because the module had no logger defined — it had no logging usage before this change.
- Pattern that caused it: Following the `server.py` pattern (`_logger = __import__("logging").getLogger(__name__)`) without checking whether the target module already had one.
- Pattern to follow instead: Before referencing `_logger` in any module, grep the file for `_logger` or `logging` to confirm the logger is already defined; if not, add it at the module bottom (consistent with `server.py` style) before writing the call site.

## Placeholder UI Layers Age Poorly

- What went wrong: A minimal shell can make tests pass while leaving major design-doc behavior effectively unimplemented.
- Pattern that caused it: Treating the API scaffold as equivalent to the full operator console.
- Pattern to follow instead: Close placeholder gaps in the same implementation pass, or explicitly track them as incomplete before declaring a phase finished.
