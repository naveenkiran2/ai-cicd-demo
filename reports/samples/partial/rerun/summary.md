# Pipeline run `20261107-203929-partial-rerun1`

| Field | Value |
|---|---|
| Pipeline | order-service-ci |
| Scenario | partial |
| Commit | `db1233d7068c` - ai-bot fix: Readiness probe path /healthz not served (service exposes /health) |
| Status | **SUCCESS** (SUCCESS) |
| Failed stage | - |
| Trigger | ai-bot-remediation (parent 20261107-203929-partial) |
| Started | 2026-11-07T20:39:30.378Z |
| Duration | 0.75s |

## Stages

| # | Stage | Status | Duration | Summary |
|---|---|---|---|---|
| 1 | Checkout & environment validation | **PASS** | 0.00s | tree db1233d7068c, 18 files, python 3.13.18 |
| 2 | Dependency installation | **PASS** | 0.00s | 1/1 resolved; app runtime uses stdlib only |
| 3 | Lint, static & secret checks | **PASS** | 0.01s | 15 files, 0 errors, 0 secrets |
| 4 | Unit tests | **PASS** | 0.36s | 21 passed |
| 5 | Build & package artifact | **PASS** | 0.00s | order-service-1.4.0.tar.gz sha256:115f03b21c61 |
| 6 | Integration & deployment validation | **PASS** | 0.37s | 6 passed |
| 7 | Publish pipeline report | **PASS** | 0.00s | 2 reports published |

## Artifacts

- `artifacts/order-service-1.4.0.tar.gz` sha256 `115f03b21c616aad...` (3075 bytes)

Logs: `logs/`  -  Test reports: `test-reports/`  -  Commit diff: `commit.diff`
