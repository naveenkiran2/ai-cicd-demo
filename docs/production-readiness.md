# Production readiness

This demo is local-first and deliberately constrained. This document lists what each control looks like **in the
demo today** and what it would need to become **in production**.

| # | Area | Demo today | Production target |
|---|---|---|---|
| 1 | Human-in-the-loop approval | `--approve` is required; dry run is the default; the approver is recorded | Approval through PR review or ChatOps with an SSO identity; two-person rule for HIGH-severity areas; approval expiry |
| 2 | RBAC & least privilege | The bot can write only to `artifacts/runs/<id>/workspace/` | Separate identities for *read* (diagnose) and *propose* (open a PR). The bot never holds merge, deploy or prod credentials. Short-lived, scoped tokens |
| 3 | Change-control integration | `change_record.json` + `patch.diff` | The bot opens a PR or ITSM change with the diagnosis, evidence and validation attached; CAB policy decides auto-approval classes |
| 4 | Environment isolation | Ephemeral local "staging" on 127.0.0.1 and a per-run workspace snapshot | Ephemeral, sandboxed runners per remediation; no network egress except artifact stores; prod is unreachable by design |
| 5 | Secrets handling | No secrets used; subprocess environments are scrubbed; secret scan in lint; LLM payload redacted | Secrets from a vault, injected only into the stage that needs them, never logged or sent to an LLM; secret-scan findings always escalate and trigger rotation |
| 6 | Audit logs | Append-only `audit.jsonl` per run (actor, action, outcome, hashes) | Ship to a SIEM or immutable store with retention policy; signed events; link to PR and ticket IDs |
| 7 | Confidence scoring | Sum of named evidence signals; 80% threshold for auto-fix | Calibrate against labelled history; track precision and recall per playbook; set thresholds per risk class |
| 8 | Rollback | Byte-for-byte backups; auto-restore on failed validation; `--rollback` with drift check | Fixes delivered as revertible commits; deployment rollback through immutable artifact versions; automated revert PR |
| 9 | Policy guardrails | Allow-list and deny-list, 2-file/5-line cap, sha256 precondition, syntax check, no-production rule | Policy-as-code (for example OPA) versioned and reviewed; per-repo allow-lists; protected paths (tests, CI, IaC, auth) |
| 10 | Testing before change promotion | Targeted stage rerun, then full pipeline rerun; success only when the rerun passes | Plus the full CI on the PR branch, canary or progressive delivery in non-prod, and SLO checks before promotion |
| 11 | Monitoring & feedback loops | Reports per run | Metrics: diagnosis precision, fix acceptance rate, rollback rate, MTTR, coverage. Engineers rate every diagnosis, and the ratings drive playbook tuning |
| 12 | Escalation when confidence is low | Below 80%, or no matching playbook, gives ESCALATE with the evidence bundle and fix guide, and no change | Page or ticket the owning team (from CODEOWNERS / a service catalog) with the bundle; time-boxed escalation; never retry blindly |

## Guardrail principles (non-negotiable)

1. **Propose and prove, never assume.** A fix is "done" only when the targeted *and* the full validation pass.
2. **Narrowest effective change.** Prefer config over code, and one line over a refactor. Alternatives are recorded.
3. **Specifications are read-only.** Tests, contracts and policies are never edited to turn a build green.
4. **No production authority.** The bot can ask for a deploy through the normal process. It cannot perform one.
5. **Deterministic core, advisory LLM.** LLM output may inform a human but cannot bypass the policy gate. Prompts
   receive redacted, minimal data.
6. **Everything is attributable.** Every action has an actor, a timestamp, an input hash and an outcome.

## LLM integration plan

`ai_bot/llm_adapter.py` defines a `Narrator` interface. The default `RuleBasedNarrator` adds nothing. A
`ClaudeNarrator` activates only when `AI_BOT_LLM=claude` and `ANTHROPIC_API_KEY` are set, and the SDK is installed.

Possible next steps, each behind the same safety gate:

* **Narrative**, already stubbed: executive summaries tailored to the audience.
* **Candidate generation for unknown failures**: the LLM proposes a patch, which is then treated as untrusted
  input. It must pass `safety.evaluate`, the targeted rerun and the full rerun, and it is always routed to a human
  PR review (never auto-approved).
* **Playbook authoring assistant**: draft new playbooks from incident retrospectives for engineers to review.

Operational requirements: per-request timeouts with deterministic fallback, cost and latency budgets, prompt and
version pinning, an evaluation set built from past incidents, and data-handling review (no source or secrets
beyond what policy allows).

## Pre-production checklist

- [ ] Read-only pilot shows root-cause precision of at least 85% on real failures
- [ ] Bot identity has no merge, deploy or prod permissions (verified by access review)
- [ ] Remediation delivered only as PRs; branch protection requires human review
- [ ] Allow-lists defined per repository; tests, CI, IaC and auth paths are protected
- [ ] Audit events shipped to the SIEM; retention policy approved
- [ ] Rollback drill executed (bad fix, then auto-revert)
- [ ] Escalation routing tested with on-call tooling
- [ ] LLM data-handling assessment completed (if enabled)
- [ ] Dashboards: precision, acceptance rate, rollback rate, MTTR, coverage
