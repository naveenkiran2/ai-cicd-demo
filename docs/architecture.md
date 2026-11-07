# Architecture

The design rests on one principle: **the AI bot only ever reasons over structured evidence the pipeline already
produces, and it can only change things through a narrow, audited, human-approved channel.**

## 1. Component architecture

```
+--------------------------------------------------------------------------------------------+
|  ai-cicd-demo                                                                              |
|                                                                                            |
|  app/  (system under test)        scenarios/<name>/scenario.json  (simulated commits)      |
|   pricing.py  orders.py                    |                                               |
|   config.py   service.py (HTTP)            v                                               |
|  config/deploy.json            +--------------------------+                                |
|  tests/unit  tests/integration |  pipeline/  (CI engine)  |                                |
|                                |  run.py      orchestrator, CLI, outcome classification   |
|                                |  stages.py   7 stage implementations                     |
|                                |  workspace.py run dirs, snapshots, diffs, hashing        |
|                                |  lint.py     AST linter + secret scan                    |
|                                |  models.py   RunRecord / StageResult (run.json schema)   |
|                                |  reporting.py summary.md + terminal rendering            |
|                                +------------+-------------+                                |
|                                             | writes                                       |
|                                             v                                              |
|            artifacts/runs/<run-id>/ run.json, logs/, test-reports/, commit.diff,           |
|                                     artifacts/, workspace/                                 |
|                                             ^ reads                     | edits workspace/ |
|                                             |                           | only (gated)     |
|                                +------------+---------------------------+-------------+   |
|                                |  ai_bot/  (incident analyst + remediation assistant)  |   |
|                                |  evidence.py   uniform read-only access to a run      |   |
|                                |  playbooks.py  failure patterns -> Finding            |   |
|                                |  diagnose.py   assembles the 11-section report        |   |
|                                |  llm_adapter.py optional advisory narrative (Claude)  |   |
|                                |  reports.py    text / Markdown / JSON renderers       |   |
|                                |  safety.py     policy gate (allow-list, limits, ...)  |   |
|                                |  remediate.py  10-step self-healing workflow          |   |
|                                |  analyze.py / demo.py  CLIs                           |   |
|                                +-------------------------------------------------------+   |
+--------------------------------------------------------------------------------------------+
```

| Layer | Owns | Must not |
|---|---|---|
| `app/`, `tests/`, `config/` | Business logic and its contract | Know about the pipeline or the bot |
| `pipeline/` | Executing stages and recording facts | Interpret failures |
| `ai_bot/` (analysis) | Turning facts into a diagnosis | Modify anything |
| `ai_bot/` (remediation) | Applying an approved, minimal change | Bypass `safety.py`, edit tests, or touch anything outside a run workspace |

## 2. Pipeline flow

```
checkout -> dependencies -> lint -> unit_tests -> package -> integration -> publish
   |            |            |         |            |            |            ^
   +------------+------------+---------+------------+------------+  always runs
        a FAIL marks every later stage SKIPPED (except publish)
```

* **Checkout** copies `app/ config/ tests/ pyproject.toml requirements.txt` into `workspace/`, applies the
  scenario's declared change (it must match exactly once), stores `commit.diff`, and computes a tree digest that acts
  as the commit SHA.
* **Integration & deployment validation** works the way a platform would: it validates the manifest against
  policy, deploys the *packaged artifact* (not the source tree) into `staging/`, starts it on `127.0.0.1` on an
  ephemeral port, runs the readiness probe from `health_path`, then runs the API and contract tests with
  `SERVICE_URL` and `DEPLOY_CONFIG`, and finally tears everything down.
* **Outcome classification** (`pipeline/run.py::_outcome`) depends only on the data, not on the scenario name. A
  failure after a successful package stage is `partial_success`, any other failure is `failure`, and no failure is
  `success`.
* Subprocesses get a scrubbed environment: any variable ending in `_TOKEN`, `_SECRET` or `_API_KEY` is removed.

## 3. AI bot decision flow

```
                   run.json
                      |
          status == SUCCESS ? ----yes---> release-readiness analysis
                      | no                (purpose, stages, tests, artifacts, checks,
                      v                    timing, risk, verdict READY + conditions)
        playbooks for failed stage (in order)
          PB-001 percentage-scale-error   (unit_tests)
          PB-002 readiness-probe-mismatch (integration)
          PB-003 missing-dependency       (dependencies)  guidance only
          PB-004 lint-violation           (lint)          guidance only
          PB-999 unclassified             (any)           confidence 0.30
                      |
            first match -> Finding
                      |
     confidence = sum of named evidence signals (capped at 0.97)
                      |
     auto_remediable && confidence >= 0.80 ?
          | yes                                   | no
  PROPOSE_FIX_PENDING_APPROVAL           ESCALATE_TO_ENGINEER
  (dry run until --approve)              (fix guide + evidence bundle, no change)
```

Confidence is explainable by design. Every point of it comes from a named signal that appears in the report. Here
is the breakdown for the failure scenario:

| Signal | Weight |
|---|---|
| Percentage variable multiplied without `/100` on the failing code path (AST) | 0.55 |
| Suspect line changed in the latest commit (diff correlation) | 0.20 |
| Assertions off by exactly 100x (numeric signature from JUnit) | 0.15 |
| All failing tests import the suspect module (import graph) | 0.05 |

### How suspects are found (PB-001)

1. Failing tests in JUnit, then their test modules, then the app modules they import (directly or transitively).
2. Suspects are ranked so that files changed in `commit.diff` come first.
3. The AST scan looks for `BinOp(Mult)` with an operand named `*_pct` or `*_percent`.
4. The fix rewrites that one operand into `(<name> / HUNDRED)`, using the module's own constant when it has one.

### How the probe mismatch is found (PB-002)

1. The log line `readiness probe FAILED: GET /healthz -> HTTP 404` gives the path and the status.
2. The manifest's `health_path` must equal that path, and the path must be absent from `GET_ROUTES` in
   `app/service.py` (read from the AST).
3. A close route match exists (`/health`), the health contract passed on it, and the manifest line appears in
   `commit.diff`.
4. The fix is the single manifest line. Adding a route was considered and rejected, because it would be a code
   change and a rebuild.

## 4. Structured data and logging

| Artifact | Format | Producer | Consumer |
|---|---|---|---|
| `run.json` | `RunRecord`: run id, scenario, status, outcome, failed stage, commit, environment, stages[], artifacts[], parent run id, trigger | pipeline | bot, humans, CI |
| `StageResult` | key, name, order, status, summary, started/finished, duration, log file, reports, metrics{}, error | each stage | bot |
| `logs/NN_stage.log` | `ISO-8601Z [LEVEL] message`, with subprocess output indented under `    \|` | StageLog | bot (regex evidence with line refs) |
| `test-reports/junit-*.xml` | JUnit XML | pytest | bot, CI dashboards |
| `test-reports/*-summary.json` | totals, failures (test id, message, details), cases | pipeline | bot |
| `test-reports/lint.json` | checks, counts, findings (file, line, check, severity) | lint stage | bot |
| `artifacts/manifest.json` | name, version, sha256, size, per-file sha256 | package stage | integration, bot |
| `bot/diagnosis.json` | full report (see `ai_bot/diagnose.py`) | bot | humans, LLM adapter, ticketing |
| `bot/remediation/audit.jsonl` | one event per line: ts, run id, step, actor, action, outcome, details | remediate | audit / SIEM |

Every evidence item in a diagnosis carries a `source` (`logs/06_integration.log:8`, `workspace:app/pricing.py:23`,
`commit.diff`, and so on), so each claim can be traced back to raw data.

## 5. Remediation and validation sequence

```
Engineer          ai_bot.remediate             safety.py          run workspace        pipeline
   |  --approve  ------>|                           |                   |                  |
   |                    | 1 detect (run.json)       |                   |                  |
   |                    | 2-3 load reviewed diagnosis.json + evidence   |                  |
   |                    | 4 write remediation_plan.json                 |                  |
   |                    | 5 evaluate(plan) -------->| approval, confidence, allow-list,    |
   |                    |<-------- all pass --------| sha256 precondition, size, syntax,   |
   |                    |                           | secrets, no-production               |
   |                    | 6 backups/ + patch.diff + change_record(pending)                 |
   |                    | 7 apply ------------------------------------->| (sha256_after)   |
   |                    | 8 targeted: run_stage(failed stage [+lint]) ---------------------->|
   |                    |      FAIL -> restore backups -> ROLLED BACK, exit 1                |
   |                    | 9 run_pipeline(source=workspace, parent=run) --------------------->| <id>-rerun1
   |                    |      FAIL -> restore backups -> ROLLED BACK, exit 1                |
   |                    | 10 change_record(verified), final_report, validation.json,        |
   |<--- RERUN PASSED --|    audit.jsonl, refreshed diagnosis.md                            |
```

* **Targeted validation** reruns only the failed stage. If a Python file changed, lint runs first. For the partial
  scenario the integration stage reuses the artifact from the original run, which is valid because the fix touches
  only environment config, which is not packaged. This is the "rerun the affected stage first" step.
* **Full validation** is a brand-new pipeline run (`<id>-rerunN`, trigger `ai-bot-remediation`). Its commit is
  the bot's patch, authored as `ai-cicd-bot (approved by <name>)`.
* **Success is only declared from data.** The result is `RERUN PASSED` only when `rerun.status == SUCCESS`.
  Anything else rolls back and reports `ROLLED BACK`.
* A side benefit you can show live: both fixes produce an artifact whose sha256 is byte-identical to the clean
  baseline build. That proves the fix restored exactly the intended code.
