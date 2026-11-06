# Documentation

The root [README.md](../README.md) is the front page. It follows core's
[README spec](https://github.com/frostyard/core/blob/main/docs/specs/readme.md)
(kind `packaging`, at most 1000 words); the details live here.

## Index

### Design

- [design/overview.md](design/overview.md): how a cask changes, from an
  application's release to an installed cask, and what each workflow does.

### Rules and agents

- [AGENTS.md](../AGENTS.md): the layout, who writes which path, the workflow
  rules and the gate. `CLAUDE.md`, `GEMINI.md`, `.cursorrules` and
  `.github/copilot-instructions.md` are symlinks to it (core ADR-0018).
- [SECURITY.md](../SECURITY.md): what is in scope, and how to report a
  vulnerability.
- [`.memory/README.md`](../.memory/README.md): the corrections inbox.

## Conventions

- A new design document goes in [`design/`](design/) and is indexed above.
- Design documents are updated in place, so that they always describe the
  workflows and the scripts that are in the tree.
- Cross-links go in both directions.
- The root `README.md` links here; the rules and the details do not go in it.
