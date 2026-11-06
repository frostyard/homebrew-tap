# `.memory/` — corrections inbox

The single sanctioned inbox for durable learned corrections (core ADR-0018).

Contract:

- `corrections.jsonl` is append-only. It has one JSON object per line. It has 5 fields, and every field is required:

  ```json
  {"date":"YYYY-MM-DD","scope":"…","correction":"…","evidence":"…","promoted_to":""}
  ```

- `promoted_to` starts empty. When the correction graduates into `AGENTS.md`, a document under `docs/`, or a test, set it to that path. Promotion is the only sanctioned duplication.
- Never record credentials or non-public vulnerability details.
- `make verify` runs `.github/scripts/test_baseline.py`, which checks every line and its 5 fields.
- A blocking review point adds 1 line in the pull request that fixes it, next to the guard that catches it.
