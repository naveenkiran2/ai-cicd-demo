# Pipeline run `20261107-203927-failure`

| Field | Value |
|---|---|
| Pipeline | order-service-ci |
| Scenario | failure |
| Commit | `b46a02bfaab3` - PRICE-142: simplify discount calculation |
| Status | **FAILED** (FAILED) |
| Failed stage | unit_tests |
| Trigger | manual |
| Started | 2026-11-07T20:39:27.757Z |
| Duration | 0.40s |

## Stages

| # | Stage | Status | Duration | Summary |
|---|---|---|---|---|
| 1 | Checkout & environment validation | **PASS** | 0.00s | tree b46a02bfaab3, 18 files, python 3.13.18 |
| 2 | Dependency installation | **PASS** | 0.00s | 1/1 resolved; app runtime uses stdlib only |
| 3 | Lint, static & secret checks | **PASS** | 0.01s | 15 files, 0 errors, 0 secrets |
| 4 | Unit tests | **FAIL** | 0.38s | 4 failed, 17 passed |
| 5 | Build & package artifact | **SKIPPED** | 0.00s | skipped: upstream stage 'unit_tests' failed |
| 6 | Integration & deployment validation | **SKIPPED** | 0.00s | skipped: upstream stage 'unit_tests' failed |
| 7 | Publish pipeline report | **PASS** | 0.00s | 2 reports published |

## Artifacts

- none (pipeline stopped before packaging)

Logs: `logs/`  -  Test reports: `test-reports/`  -  Commit diff: `commit.diff`
