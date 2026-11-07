# From firefighting to self-healing: the CI/CD platform transformation story

## The situation

Every engineering team ships through the CI/CD pipeline, which makes it the organisation's delivery bloodstream.
When it goes red, delivery stops. Today, recovering from a red pipeline is a manual, expert-dependent ritual:

* An engineer stops their planned work, opens long logs, and reconstructs what happened.
* The quality of the diagnosis depends on *who* is on call and how familiar they are with that service.
* Fixes are applied by hand, often after a few "rerun and hope" attempts. The reasoning is rarely written down.
* The same classes of failure recur across teams, because the lessons stay in people's heads.

The result is slow recovery, inconsistent quality, senior engineers spending time on toil, and no audit trail for
the changes made under pressure.

## The idea

Treat pipeline failures as **incidents that a digital teammate triages first**. The bot does the evidence
gathering and the first-pass analysis that humans do today, then hands the human a decision instead of a puzzle:

| Today (manual) | With the AI CI/CD bot |
|---|---|
| Read logs line by line | Structured evidence (stage metadata, test reports, diffs, checksums) is collected automatically |
| Guess the root cause | A root cause with a confidence score and traceable evidence |
| Assess impact informally | Severity, blast radius (modules, APIs), customer and production impact |
| Ad hoc fix, often rerun everything | Minimal, playbook-based fix; the failed stage is rerun first, then the full pipeline |
| Tribal knowledge | Reusable remediation playbooks that the whole organisation shares |
| No record | A complete audit trail: who approved, what changed, hashes, validation results |

## What the demo proves

1. **Explaining success.** A green build becomes a release-readiness statement that a non-engineer can trust.
2. **Diagnosing failure.** A pricing regression is pinned to one line, with evidence, in under a second. That
   includes the tell-tale "every wrong value is exactly 100x" signature an expert would recognise.
3. **Targeted repair.** A late-stage deployment failure is separated from the work that succeeded. Only the
   broken stage is repaired and revalidated first.
4. **Safety.** Nothing changes without explicit human approval. The bot can only touch an allow-list of files,
   cannot edit tests, rolls back automatically on failed validation, and never claims success it did not verify.

## Illustrative outcomes

> **These numbers are illustrative assumptions for discussion, not measured results.** A pilot would establish a
> baseline (current MTTR, triage hours, repeat-failure rate) before claiming any improvement.

| Outcome | Illustrative target | How the bot contributes |
|---|---|---|
| CI/CD triage time | **40 to 60% reduction** | Evidence gathering and first-pass RCA are automated. Engineers review instead of investigate |
| Mean time to recovery (pipeline incidents) | **Hours down to minutes** for known patterns (for example, from about 90 to about 20 minutes, including human review) | Diagnosis is instant, and the fix plus validation is a single approved action |
| Root-cause consistency | **Every incident gets the same 11-section report** | Standard template and evidence standard, whoever is on call |
| Repeat incidents | **20 to 30% fewer** recurring failure classes within two quarters | Each resolved pattern becomes a playbook, and patterns feed code-review and lint rules |
| Engineering productivity | About **0.5 to 1 engineer-day per team per sprint** returned to roadmap work | Less context switching and fewer "who knows this service?" escalations |
| Release confidence | **Every promotion carries a verifiable readiness report** | Artifact checksum, test evidence and quality gates are summarised automatically |
| Audit and compliance | **100% of automated changes traceable** | Approval, patch, hashes and validation are captured in an append-only log |

### A worked illustration (assumptions stated)

* Assume 200 pipeline failures a month across the organisation, each taking 45 minutes of engineer triage on average.
  That is about **150 engineer-hours a month**.
* Assume the bot fully diagnoses 50% of failures (known patterns) and cuts triage on those to 10 minutes of review,
  and gives a useful head start that saves 15 minutes on the rest.
* That gives about 58 + 25 = **83 hours a month saved, roughly 55%**, before counting faster recovery for the teams
  that were blocked.

## The roadmap

| Phase | Scope | Exit criteria |
|---|---|---|
| **0. This demo** | Local, deterministic, 2 auto-fix playbooks, human approval | Leadership buy-in |
| **1. Read-only pilot** (4 to 6 weeks) | Bot posts diagnoses on real pipeline failures for 2 or 3 teams; no changes | Precision of at least 85% on root cause, judged by engineers; triage baseline captured |
| **2. Assisted remediation** | Bot opens fix *pull requests* for high-confidence patterns; humans merge | Fix acceptance rate of at least 70%; zero unsafe changes |
| **3. Scaled playbooks** | Mine incident history for the top 20 patterns; LLM narrative and candidate generation behind the safety gate | Coverage of more than 50% of failures; MTTR target met |
| **4. Policy-driven autonomy** | Low-risk classes (for example, config drift in non-prod) auto-approved by policy, with full audit | Change advisory board sign-off; error budget respected |

## The message for leadership

> We are not replacing engineers with AI. We are removing the toil between "the build is red" and "here is the
> decision". And we are making every one of those decisions faster, consistent and auditable.
