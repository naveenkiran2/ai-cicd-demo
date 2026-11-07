# Remediation report - run `20261107-203927-failure`

**Result: RERUN PASSED** - verified: True

| Field | Value |
|---|---|
| Fix | Percentage not normalised in apply_discount() (app/pricing.py:23) |
| Playbook | PB-001 percentage-scale-error (confidence 95%) |
| Approved by | demo.approver |
| Before | FAILED (failure, failed at `unit_tests`) |
| After | SUCCESS (rerun `20261107-203927-failure-rerun1`) |

## Before / after

| Stage | Before | Targeted rerun | Full rerun |
|---|---|---|---|
| Checkout & environment validation | PASS | - | PASS |
| Dependency installation | PASS | - | PASS |
| Lint, static & secret checks | PASS | PASS | PASS |
| Unit tests | FAIL | PASS | PASS |
| Build & package artifact | SKIPPED | - | PASS |
| Integration & deployment validation | SKIPPED | - | PASS |
| Publish pipeline report | PASS | - | PASS |

## Files changed

- `app/pricing.py` line 23: sha256 `5390a7d26812` -> `e5985e44e5c6` (backup `bot/remediation/backups/app/pricing.py.orig`)

Patch: `bot/remediation/patch.diff` - Audit trail: `bot/remediation/audit.jsonl`
