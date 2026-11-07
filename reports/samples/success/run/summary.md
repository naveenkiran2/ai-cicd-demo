# Pipeline run `20261107-203926-success`

| Field | Value |
|---|---|
| Pipeline | order-service-ci |
| Scenario | success |
| Commit | `37108b64f976` - DOCS-12: clarify pricing docstring |
| Status | **SUCCESS** (SUCCESS) |
| Failed stage | - |
| Trigger | manual |
| Started | 2026-11-07T20:39:26.891Z |
| Duration | 0.76s |

## Stages

| # | Stage | Status | Duration | Summary |
|---|---|---|---|---|
| 1 | Checkout & environment validation | **PASS** | 0.00s | tree 37108b64f976, 18 files, python 3.13.18 |
| 2 | Dependency installation | **PASS** | 0.00s | 1/1 resolved; app runtime uses stdlib only |
| 3 | Lint, static & secret checks | **PASS** | 0.01s | 15 files, 0 errors, 0 secrets |
| 4 | Unit tests | **PASS** | 0.31s | 21 passed |
| 5 | Build & package artifact | **PASS** | 0.00s | order-service-1.4.0.tar.gz sha256:ab613bd964a9 |
| 6 | Integration & deployment validation | **PASS** | 0.43s | 6 passed |
| 7 | Publish pipeline report | **PASS** | 0.00s | 2 reports published |

## Artifacts

- `artifacts/order-service-1.4.0.tar.gz` sha256 `ab613bd964a91446...` (3085 bytes)

Logs: `logs/`  -  Test reports: `test-reports/`  -  Commit diff: `commit.diff`
