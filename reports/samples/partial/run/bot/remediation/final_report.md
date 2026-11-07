# Remediation report - run `20261107-203929-partial`

**Result: RERUN PASSED** - verified: True

| Field | Value |
|---|---|
| Fix | Readiness probe path /healthz not served (service exposes /health) |
| Playbook | PB-002 readiness-probe-path-mismatch (confidence 95%) |
| Approved by | demo.approver |
| Before | FAILED (partial_success, failed at `integration`) |
| After | SUCCESS (rerun `20261107-203929-partial-rerun1`) |

## Before / after

| Stage | Before | Targeted rerun | Full rerun |
|---|---|---|---|
| Checkout & environment validation | PASS | - | PASS |
| Dependency installation | PASS | - | PASS |
| Lint, static & secret checks | PASS | - | PASS |
| Unit tests | PASS | - | PASS |
| Build & package artifact | PASS | - | PASS |
| Integration & deployment validation | FAIL | PASS | PASS |
| Publish pipeline report | PASS | - | PASS |

## Files changed

- `config/deploy.json` line 5: sha256 `5d52e51d0014` -> `55ff8dd8457d` (backup `bot/remediation/backups/config/deploy.json.orig`)

Patch: `bot/remediation/patch.diff` - Audit trail: `bot/remediation/audit.jsonl`
