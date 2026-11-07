# ai-cicd-demo: an AI bot for CI/CD triage and safe self-healing

A small, deterministic demo you run locally. It shows an AI bot taking over the
slow, manual parts of CI/CD operations:

1. **Explain** a healthy run: what ran, what was tested, what was built, and whether it is ready to release.
2. **Diagnose** a failed run: which stage failed, the root cause with log/test/diff evidence, the blast radius and the fix.
3. **Self-heal safely**: propose a minimal patch, get explicit human approval, back up, apply only allow-listed
   changes, rerun the failed stage, rerun the full pipeline, and write an audit trail.

There are no cloud credentials, paid services, LLM keys or network calls (beyond an optional `pip install pytest`).
The demo is the same every time you run it.

```
 commit ──> [ local CI pipeline: 7 stages ] ──> run.json + logs + JUnit + diff
                                                  │
                                                  ▼
                       [ AI bot: evidence -> playbooks -> diagnosis + confidence ]
                                                  │
                    success: release-readiness report   failure: fix proposal
                                                                  │  human --approve
                                                                  ▼
                [ safety gate -> backup -> patch -> targeted rerun -> full rerun -> audit ]
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Verified locally on 3.13; CI runs 3.12 and 3.13 on GitHub Actions |
| `pytest` | The only third-party package. The app and pipeline use only the standard library |
| OS | Linux, macOS or Windows. The output is plain ASCII. Colour switches off automatically when piped (`NO_COLOR=1` turns it off, `FORCE_COLOR=1` forces it on) |

## Setup (about 1 minute)

```bash
cd ai-cicd-demo
```

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

Run every command from the `ai-cicd-demo/` directory.

---

## Commands

### The whole story in one command per scenario

```bash
python -m ai_bot.demo --scenario success
```

```bash
python -m ai_bot.demo --scenario failure            # asks "Approve the proposed change? [y/N]"
```

```bash
python -m ai_bot.demo --scenario partial --approve  # non-interactive approval
```

```bash
python -m ai_bot.demo --scenario all --approve      # all three back to back (~5 seconds)
```

Extra flags: `--pause` waits for Enter between steps (presenter mode). `--approver NAME` sets the name written to the
audit trail. `--export-samples` refreshes `reports/samples/`.

### Step by step (what the demo runs for you)

```bash
python -m pipeline.run --scenario success      # exit 0
```

```bash
python -m pipeline.run --scenario failure      # exit 1: unit tests fail
```

```bash
python -m pipeline.run --scenario partial      # exit 1: only integration/deployment validation fails
```

```bash
python -m ai_bot.analyze --run-id <id>         # text report; add --json for machine-readable output
```

```bash
python -m ai_bot.remediate --run-id <id>       # DRY RUN: plan + safety gate, modifies nothing
```

```bash
python -m ai_bot.remediate --run-id <id> --approve
```

```bash
python -m ai_bot.remediate --run-id <id> --rollback
```

```bash
python -m pipeline.run --from-run <id>         # manual full rerun on a run's (patched) workspace
```

`<id>` can be the printed run id, `latest`, or `latest-success|latest-failure|latest-partial`.

### Exit codes

| Command | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `pipeline.run` | pipeline SUCCESS | pipeline FAILED | - | - |
| `ai_bot.remediate` | fixed and verified, dry run, or nothing to fix | validation failed (rolled back) | blocked by safety gate / already remediated | escalated to a human |
| `ai_bot.demo` | every scenario ended green and verified | anything else | - | - |

---

## The three scenarios

| Scenario | Simulated commit | Intentional defect | What fails | Bot fix (1 line) | Targeted rerun |
|---|---|---|---|---|---|
| **success** | `DOCS-12` docstring tweak | none | nothing | none. It writes a release-readiness report instead | - |
| **failure** | `PRICE-142` "simplify discount calculation" | `app/pricing.py`: `subtotal * discount_pct` (dropped the `/ 100`, so 10% becomes 1000%) | Unit tests (4 of 21); build, package and integration are SKIPPED | `subtotal * (discount_pct / HUNDRED)` | lint + unit tests |
| **partial** | `OPS-87` "align readiness probe with k8s naming" | `config/deploy.json`: `health_path` changed to `/healthz`, but the service serves `/health` | Only *Integration & deployment validation* (1 of 6 tests fail; the probe returns 404) | `"health_path": "/health"` | integration only, reusing the already-built artifact |

Each scenario is a declared change in `scenarios/<name>/scenario.json` that is applied to a clean snapshot of the
repository. **The baseline sources in `app/` and `config/` are never modified**, so the demo can be repeated forever.

---

## Example output

The full transcripts are in `reports/samples/<scenario>/terminal-output.txt`. This excerpt is from the failure
scenario:

```
  [4/7] Unit tests ........................... FAIL      0.38s  4 failed, 17 passed
  [5/7] Build & package artifact ............. SKIPPED       -  skipped: upstream stage 'unit_tests' failed

-- 4. Root-cause analysis ----------------------------------------------------
  Percentage not normalised in apply_discount() (app/pricing.py:23)
  Confidence: 95%
    +0.55  percentage variable multiplied without /100 on the failing code path
    +0.20  suspect line was modified in the latest commit
    +0.15  3 assertion(s) off by exactly 100x (scale error signature)
    +0.05  all failing tests share the suspect module

  [05/10] Safety gate & human approval ..... PASS          13/13 checks; approved by demo.approver
  [07/10] Apply allow-listed change ........ FIXED         app/pricing.py 5390a7d2->e5985e44
          [targeted] Unit tests ............................ PASS     0.32s  21 passed
            => RERUN PASSED
  Stage                                Before   Targeted  Full rerun
  Unit tests                           FAIL     PASS      PASS
  Build & package artifact             SKIPPED  -         PASS
  Integration & deployment validation  SKIPPED  -         PASS
```

> Screenshot placeholders: for slides, run `FORCE_COLOR=1 python -m ai_bot.demo --scenario failure --approve` and
> capture the coloured terminal (PASS green, FAIL red, SKIPPED grey, FIXED cyan).

---

## The pipeline

| # | Stage | What it really does |
|---|---|---|
| 1 | Checkout & environment validation | Snapshots the repo into `artifacts/runs/<id>/workspace/`, applies the scenario commit, writes `commit.diff`, computes a tree digest, and checks the Python version and repository layout |
| 2 | Dependency installation | Checks every requirement against its version constraint (`--install-deps` runs `pip install` for missing ones) |
| 3 | Lint, static & secret checks | Built-in AST linter (syntax, unused imports, bare except, `print`, line length, whitespace) plus a secret scan (AWS keys, private keys, credential literals) |
| 4 | Unit tests | `pytest tests/unit` with JUnit XML output |
| 5 | Build & package artifact | Checks that the pyproject and `app.__version__` agree, then builds a reproducible `.tar.gz` (fixed mtimes, sorted entries) with a sha256 manifest |
| 6 | Integration & deployment validation | Checks the deploy manifest against policy (no production, port range, probe path). Extracts the artifact to an isolated staging dir, starts the service on `127.0.0.1` on an ephemeral port, probes readiness, then runs the API and contract tests |
| 7 | Publish pipeline report | Writes `run.json` and `summary.md`. This stage always runs, even after a failure |

When a stage fails, every later stage is marked SKIPPED, except Publish. The run's outcome is `success`, `failure`,
or `partial_success`. `partial_success` means the artifact was built, but a later stage failed.

### What a run directory contains

```
artifacts/runs/<run-id>/
  run.json               structured run metadata (stages, timings, metrics, artifacts, commit)
  summary.md             human-readable run summary
  commit.diff            the change under test
  logs/NN_<stage>.log    timestamped stage logs (+ service.log)
  test-reports/          junit-unit.xml, junit-integration.xml, *-summary.json, lint.json
  artifacts/             order-service-1.4.0.tar.gz + manifest.json (sha256 per file)
  workspace/             the checked-out snapshot (the ONLY place the bot may edit)
  bot/
    diagnosis.json|.md   the 11-section analysis report
    remediation_plan.json
    validation.json      final validation verdict
    remediation/
      safety_checks.json, change_record.json, patch.diff, backups/
      targeted/          logs + reports of the targeted stage rerun
      final_report.json|.md, audit.jsonl
<run-id>-rerun1/         the full pipeline rerun triggered by the bot
```

Live runs are git-ignored. Committed examples of all three scenarios are in **`reports/samples/`**.

---

## How the AI bot works

1. **Evidence collection** (`ai_bot/evidence.py`). The bot reads `run.json`, the stage logs, JUnit summaries, the
   lint report, `commit.diff`, and (read-only) the workspace source. It also builds an import graph of the code.
2. **Playbooks** (`ai_bot/playbooks.py`). These are rules for known failure patterns. Each playbook returns a
   finding: root cause, evidence, a confidence score built from named signals, impact and blast radius, a minimal
   proposed change, and the stages to rerun.
   - `PB-001 percentage-scale-error`: maps the failing tests to the app modules they import, puts lines changed in
     the commit first, uses the AST to find a `*_pct` value multiplied without `/100`, and checks that the failed
     assertions are off by exactly 100x.
   - `PB-002 readiness-probe-path-mismatch`: links the probe 404 in the log, the manifest `health_path`, and the
     `GET_ROUTES` in `app/service.py` (closest match), and confirms the health contract passes on the real route.
   - `PB-003 missing-dependency` and `PB-004 lint-violation`: give guidance only (they always escalate).
   - `PB-999 unclassified`: the fallback. Confidence is 30%, so it always escalates to an engineer.
3. **Diagnosis** (`ai_bot/diagnose.py`). Every report has the same sections: executive summary, pipeline status,
   per-stage table, root cause, evidence, impact and risk, recommendation and fix guide, files to modify,
   validation plan, rollback plan, and the final outcome. Successful runs get a release-readiness explanation
   instead of a root cause.
4. **Narrative LLM (optional)** (`ai_bot/llm_adapter.py`). Set `AI_BOT_LLM=claude` and `ANTHROPIC_API_KEY`, and run
   `pip install anthropic`. Claude then adds an *advisory* summary for leadership. The LLM never chooses the fix or
   overrides the safety gate. Only a redacted, structured subset of the data is sent. Without a key, or if anything
   goes wrong, the bot falls back to the rule-based output.

## Self-healing safety controls

The bot modifies a file only when **every** check in `ai_bot/safety.py` passes:

| Control | Rule |
|---|---|
| Human approval | `--approve` is required. Without it you get a dry run that shows the plan and modifies nothing |
| Confidence threshold | The diagnosis confidence must be at least 80%. Otherwise the bot escalates to a human |
| Allow-list | Only `app/*.py` and `config/*.json` inside the run's `workspace/` |
| Deny-list | `tests/`, `pipeline/`, `ai_bot/`, `.github/`, requirements and pyproject. **The bot cannot edit tests to make them pass** |
| Containment | No path traversal, symlinks, new files or deletes, and nothing outside the project |
| Narrow change | At most 2 files and 5 changed lines. The replaced text must match exactly once |
| Drift protection | The file's sha256 must still equal the one recorded at diagnosis time |
| Integrity | The patched file must still parse (Python AST or JSON), and the new text must not contain anything that looks like a secret |
| No production | It refuses if `AI_BOT_TARGET_ENV=production` or if the manifest targets production. The pipeline never deploys beyond local staging |
| Backup first | Byte-for-byte backups and `patch.diff` are written before anything changes |
| Auto-rollback | If the targeted or full rerun fails, the backups are restored and the run is never reported as fixed |
| Idempotent | A run that has already been remediated is blocked until you roll it back (`--rollback` refuses if the file changed after the fix) |
| Audit | Every step is appended to `bot/remediation/audit.jsonl` (actor, action, outcome, hashes) |

---

## Running the interview demo in under 10 minutes

The full speaker script is in [`docs/demo-script.md`](docs/demo-script.md).

| Time | Do | Say |
|---|---|---|
| 0:00 | Problem slide or talk track | Manual triage is slow and inconsistent |
| 1:30 | `python -m ai_bot.demo --scenario success --pause` | The bot explains a green build and gives a release verdict |
| 3:30 | `python -m ai_bot.demo --scenario failure --pause` and type `y` at the prompt | Root cause with evidence, then a human-approved fix, then a verified rerun |
| 6:30 | `python -m ai_bot.demo --scenario partial --approve` | Passed work is kept, and only the failed stage is rerun first |
| 8:00 | Open `bot/remediation/audit.jsonl` and `final_report.md` | Auditability and guardrails |
| 9:00 | [`docs/leadership-story.md`](docs/leadership-story.md) outcomes | MTTR, consistency and productivity (illustrative) |

Backup plan if anything goes wrong live: show `reports/samples/*/terminal-output.txt`.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md): components, pipeline flow, bot decision flow, data model, and the remediation sequence
- [`docs/demo-script.md`](docs/demo-script.md): a 10-minute leadership demo with speaker notes
- [`docs/leadership-story.md`](docs/leadership-story.md): the transformation story for executives, with illustrative metrics
- [`docs/production-readiness.md`](docs/production-readiness.md): what it would take to run this for real

## Project layout

```
app/            sample order-service (pricing, orders, config validation, stdlib HTTP service)
config/         deployment manifest (deploy.json)
tests/unit/     domain unit tests          tests/integration/   API, contract and readiness tests
pipeline/       run.py (CLI/orchestrator), stages.py, models.py, reporting.py, lint.py, workspace.py, console.py
ai_bot/         analyze.py, diagnose.py, playbooks.py, evidence.py, remediate.py, safety.py, reports.py,
                llm_adapter.py, demo.py
scenarios/      success/ failure/ partial/ scenario.json (simulated commits)
artifacts/runs/ live run directories (git-ignored)
reports/samples sample outputs for all three scenarios
.github/workflows/ci.yml   the same flow on GitHub Actions (optional)
```

## Known limitations

- **Diagnosis uses rules, not open-ended reasoning.** The bot reliably fixes the defect *patterns* it has playbooks
  for. Anything else gets a low-confidence finding and is escalated, never guessed. This is deliberate, and it is
  how you would start in production. An LLM could widen coverage behind the same safety gate.
- **Fixes go to a sandbox workspace, not git.** A real system would open a pull request with `patch.diff`,
  attaching the diagnosis and validation evidence for review.
- **"Deployment" means a local process** on an ephemeral port, not Kubernetes. The manifest policy and readiness
  probe imitate what a platform would enforce.
- The confidence weights are hand-tuned for illustration. A real system would calibrate them against past incidents.
- The linter is a small built-in one, so the demo needs no extra installs. Real pipelines would use ruff, mypy,
  bandit, a dependency audit, and so on.
- Concurrent runs of the same scenario in the same second get unique ids (`-2`), but there is no run locking.
