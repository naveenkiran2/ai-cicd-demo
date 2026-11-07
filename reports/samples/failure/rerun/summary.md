# Pipeline run `20261107-203927-failure-rerun1`

| Field | Value |
|---|---|
| Pipeline | order-service-ci |
| Scenario | failure |
| Commit | `db1233d7068c` - ai-bot fix: Percentage not normalised in apply_discount() (app/pricing.py:23) |
| Status | **SUCCESS** (SUCCESS) |
| Failed stage | - |
| Trigger | ai-bot-remediation (parent 20261107-203927-failure) |
| Started | 2026-11-07T20:39:28.490Z |
| Duration | 0.76s |

## Stages

| # | Stage | Status | Duration | Summary |
|---|---|---|---|---|
| 1 | Checkout & environment validation | **PASS** | 0.00s | tree db1233d7068c, 18 files, python 3.13.18 |
| 2 | Dependency installation | **PASS** | 0.00s | 1/1 resolved; app runtime uses stdlib only |
| 3 | Lint, static & secret checks | **PASS** | 0.01s | 15 files, 0 errors, 0 secrets |
| 4 | Unit tests | **PASS** | 0.33s | 21 passed |
| 5 | Build & package artifact | **PASS** | 0.00s | order-service-1.4.0.tar.gz sha256:115f03b21c61 |
| 6 | Integration & deployment validation | **PASS** | 0.41s | 6 passed |
| 7 | Publish pipeline report | **PASS** | 0.00s | 2 reports published |

## Artifacts

- `artifacts/order-service-1.4.0.tar.gz` sha256 `115f03b21c616aad...` (3075 bytes)

Logs: `logs/`  -  Test reports: `test-reports/`  -  Commit diff: `commit.diff`
