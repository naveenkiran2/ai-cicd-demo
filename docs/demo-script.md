# 10-minute leadership demo script

**Audience:** engineering leadership and platform stakeholders. **Format:** one terminal, large font, plus this
page. **Goal:** show that AI-assisted CI/CD operations cut triage time, standardise root-cause analysis, and fix
things safely with a human in control.

## Before you start (2 minutes, off-stage)

```bash
cd ai-cicd-demo && pip install -r requirements.txt
```

```bash
python -m ai_bot.demo --scenario all --approve > /dev/null && echo "demo environment OK"
```

* Use a terminal at least 120 columns wide with a font size of 16pt or more. Colour is on by default in a TTY.
* Have `reports/samples/failure/terminal-output.txt` open in an editor tab as a fallback.
* Optional: open `docs/architecture.md` section 3 (the decision flow diagram) in a second tab.

---

## 1. The business problem: manual triage is slow and inconsistent (0:00 to 1:30)

**Show:** nothing yet, or a single slide.

> **Speaker notes**
> - "Every red build starts the same ritual: someone opens a 2,000-line log, scrolls, guesses, asks in Slack,
>   reruns it 'just in case', and eventually finds the change that broke it."
> - "That costs us three ways. Time, because MTTR for pipeline failures is measured in hours, not minutes.
>   Inconsistency, because the quality of the root cause depends on who is on call. Knowledge loss, because the fix
>   lives in someone's head, not in a reusable pattern."
> - "Senior engineers become human log parsers. That is our most expensive talent doing our least valuable work."
> - "Today I'll show a working prototype that does the first 80% of that ritual automatically, with evidence, and
>   only changes code when a human says yes."

## 2. The solution: AI-assisted observability, diagnosis, guided remediation and validation (1:30 to 2:30)

**Show:** the ASCII diagram at the top of `README.md`.

> **Speaker notes**
> - "Four capabilities. **Observe**: the pipeline emits structured evidence, not just logs. That means run
>   metadata, JUnit, diffs and checksums. **Diagnose**: the bot correlates that evidence into a root cause with a
>   confidence score. **Remediate**: it proposes the smallest possible fix and applies it only with approval, inside
>   guardrails. **Validate**: it proves the fix by rerunning, first the failed stage, then the whole pipeline."
> - "It's deliberately deterministic. The decisions come from reviewable playbooks, so the same failure gives the
>   same answer every time. There's an adapter for Claude to add a richer narrative, but the LLM never decides
>   what gets changed."

## 3. Successful run: the bot explains a green build (2:30 to 4:00)

```bash
python -m ai_bot.demo --scenario success --pause
```

**Point at:** the 7 PASS lines, then in the report: *What this pipeline does*, *Tests executed* (21 unit + 6
integration), *Artifacts generated* (sha256), *Quality & security checks*, and *Release readiness: READY* with
conditions.

> **Speaker notes**
> - "Even green builds are opaque to most stakeholders. Here the bot turns one into a release-readiness
>   statement: what ran, what was tested, the exact artifact checksum, which security checks passed, and the
>   conditions for promotion."
> - "Notice that it says READY *for promotion through change approval*. It does not deploy to production. That
>   gate stays human."
> - "A release manager, an auditor or a product owner can read this without opening a single log."

## 4. Failure detection and self-healing (4:00 to 6:30)

```bash
python -m ai_bot.demo --scenario failure --pause
```

**Walk through, in order:**

1. The pipeline: unit tests **FAIL** (4 of 21). Packaging and integration are **SKIPPED**. Say: "Nothing broken got
   built or deployed."
2. *Root-cause analysis*: `apply_discount()` multiplies by `discount_pct` without `/100`.
3. *Confidence 95%*. Read the four signals aloud: the AST pattern, the line changed in this commit, the
   assertions off by **exactly 100x**, and the shared import path.
4. *Impact*: severity HIGH, customer-facing pricing, blast radius includes `POST /orders/quote`. Production
   impact: none.
5. *Files proposed*: a one-line diff. *Alternatives considered*: "Edit the tests is rejected, because the bot is
   not allowed to touch tests."
6. At the prompt **`Approve the proposed change? [y/N]`**, pause, then type `y`.
7. Steps 05 to 10: safety gate 13/13, backup, **FIXED**, targeted lint and unit tests **RERUN PASSED**, then the
   full pipeline goes green, and the before/after table appears.

> **Speaker notes**
> - "Manually, this is a 30 to 90 minute investigation. The bot did it in under a second, and every claim links to
>   a log line, a test report or the diff."
> - "The 100x signature matters. It's the kind of pattern a senior engineer spots and a junior one misses. Now it's
>   captured once, as a playbook, and applied consistently."
> - "It asked me. Nothing changes without explicit approval. The default is a dry run."
> - "It didn't declare victory after the patch. It reran the failed stage, then the entire pipeline, and only
>   then said RERUN PASSED. If either rerun had failed, it would have restored the backup automatically."

## 5. Partial failure: targeted diagnosis and repair (6:30 to 8:00)

```bash
python -m ai_bot.demo --scenario partial --approve
```

**Point at:** build, lint, unit and package are **PASS**, and only *Integration & deployment validation* is
**FAIL** (1 of 6 tests fail). Then *Passed work / Failed work / Reusable: artifact sha256…*, the evidence
`GET /healthz -> HTTP 404` alongside `service only serves ['/health']`, and the targeted rerun of **only** the
integration stage.

> **Speaker notes**
> - "This is the expensive kind of failure: late in the pipeline, after 80% of the work has passed. Teams usually
>   rerun everything and hope."
> - "The bot separates what succeeded from what failed. The artifact is good and reusable. The defect is a
>   one-line ops config drift, where the readiness probe points at `/healthz` but the service serves `/health`."
> - "It chose the config fix over adding a new route, because that's the narrower change and needs no rebuild,
>   and it says so under 'Alternatives considered'."
> - "It reruns only the failed stage against the existing artifact first, which is fast feedback, and then the
>   whole pipeline for a clean, auditable green."

## 6. Business outcomes (8:00 to 9:00)

**Show:** `docs/leadership-story.md`, the "Illustrative outcomes" table.

> **Speaker notes**
> - "These figures are illustrative assumptions, not measurements. In a pilot we'd baseline them first."
> - "**MTTR**: triage drops from tens of minutes to seconds for known patterns, and we would target a 40 to 60%
>   reduction in overall triage time."
> - "**Less manual effort**: on-call engineers review a diagnosis instead of producing one."
> - "**Standardised troubleshooting**: every incident gets the same 11-section report and the same evidence
>   standard."
> - "**Fewer repeat incidents**: each fix becomes a playbook. The organisation learns once."
> - "**Auditability**: who approved what, which file changed, its hashes before and after, and the validation
>   result."

## 7. Production safeguards and human approval (9:00 to 10:00)

```bash
cat artifacts/runs/*-failure/bot/remediation/audit.jsonl | head -5
```

```bash
python -m ai_bot.remediate --run-id latest-failure      # shows it refuses: already remediated
```

> **Speaker notes**
> - "The guardrails are code, not policy slides. It edits an allow-list of source and config files only, and never
>   tests, pipeline code, CI config or dependencies. The change is capped at 2 files and 5 lines, the file hash must
>   match what was diagnosed, the patched file must parse, and it scans for secrets and refuses production targets."
> - "Low confidence means escalation, not guessing. Unknown failures go to an engineer with the evidence bundle
>   already attached."
> - "Rolling out to production means adding RBAC, change-ticket integration and PR-based delivery. That roadmap
>   is in `docs/production-readiness.md`."
> - Close: **"The bot doesn't replace engineers. It removes the toil between the red build and the decision, and
>   it makes every decision auditable."**

---

## Likely questions

| Question | Short answer |
|---|---|
| "Is this really AI?" | It's an AI-agent *architecture*: perceive, reason, act, verify. Reasoning uses deterministic playbooks for safety and repeatability, and an LLM adapter (Claude) is plugged in for narrative and could later propose candidates for unknown failures, behind the same gate |
| "What if it's wrong?" | The confidence threshold leads to escalation, the dry run is the default, approval is required, and failed validation triggers an automatic rollback. It cannot report success unless the rerun actually passes |
| "Why not let it edit tests?" | Tests are the specification. A bot that edits tests to go green destroys the signal |
| "How does it scale to our failures?" | Mine past incidents for the top-N patterns and encode each as a playbook with its own tests. Track the coverage rate and the false-positive rate |
| "What about secrets?" | It never reads them: subprocess environments are scrubbed, the secret scan runs on every build, and only redacted structured data is sent to the optional LLM |
