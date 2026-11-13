<!-- The repository owner reviews risk:high pull requests. Branch from the
latest base branch. Reviews apply the repository's docs and PR rules. -->

## Summary

<!-- What changes and why, in a few sentences. Link the issue(s) this closes. -->

## Risk tier

Declare the highest applicable tier, never lower. The workflow adds 1 level label from a path in `.github/risk-paths.json`: `level:L1` to `level:L4`, and `risk:high` for L1 and L2. A `risk:high` label means tier 3. A project can replace this scale in an ADR.

Scale: 1 low = docs, tests, comments; 2 medium = behaviour change in code; 3 high = security, data loss, releases or publishing, CI and permissions, or any `risk:high` label.

Risk tier: 1 — <!-- justification -->

## Docs housekeeping

<!-- Delete rows that do not apply. -->

- [ ] Every new doc indexed in `docs/README.md`
- [ ] Cross-links added in both directions
- [ ] Conformance aliases and canonical symlinks are unchanged; canonical targets are edited instead

## Verification

<!-- Paste evidence for every applicable gate. -->

- [ ] `make verify` green
- [ ] `make ci` green
- [ ] Risk path touched: the PR body names each matched path and why the change is safe
- [ ] Revert test for a fix: the new test fails with the fix reverted; command: <!-- name it -->
- [ ] Workflows changed: every action is SHA-pinned with `# vX.Y.Z`, `permissions: {}`, and `persist-credentials: false`
- [ ] Cask changed: the version and the sha256 come from the application's own release, not from a hand edit
- [ ] Blocking review point fixed: guard added and 1 file added under `.memory/corrections/`
