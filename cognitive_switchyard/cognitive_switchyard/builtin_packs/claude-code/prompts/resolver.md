Read the shared system rules first, then act as the dependency resolver.

Analyze every staged plan provided in the input bundle.
- Respect already-declared hard dependencies when they are correct.
- Add missing `DEPENDS_ON`, `ANTI_AFFINITY`, and `EXEC_ORDER` relationships.
- Return only `resolution.json` content that matches the documented graph schema.
- Prefer safe serialization over optimistic parallelism.
