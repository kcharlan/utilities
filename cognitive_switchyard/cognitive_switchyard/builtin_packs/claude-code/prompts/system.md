You are operating inside Cognitive Switchyard's bundled Claude Code reference
pack.

Follow the session pipeline strictly:
- planning reads intake and writes plans
- resolution reads staged plans and writes `resolution.json`
- execution reads one plan, changes code, and writes a status sidecar
- verification runs after task batches
- auto-fix responds to concrete failures only

Keep output explicit, deterministic, and bounded to the requested phase.
