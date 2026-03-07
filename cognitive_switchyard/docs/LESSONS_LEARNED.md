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

## Placeholder UI Layers Age Poorly

- What went wrong: A minimal shell can make tests pass while leaving major design-doc behavior effectively unimplemented.
- Pattern that caused it: Treating the API scaffold as equivalent to the full operator console.
- Pattern to follow instead: Close placeholder gaps in the same implementation pass, or explicitly track them as incomplete before declaring a phase finished.
