"""Diagnosis engine: turns raw run evidence into a structured incident report.

Deterministic and rule-based by default (same input -> same output). An LLM can
optionally add narrative via ai_bot.llm_adapter but never changes the decision.
"""
from ai_bot.evidence import RunEvidence, item
from ai_bot.playbooks import find_root_cause
from pipeline.stages import PIPELINE_PURPOSE, STAGE_BY_KEY
from pipeline.workspace import utcnow

ANALYZER = "ai-cicd-bot rule-engine v1.0 (deterministic)"
AUTO_FIX_MIN_CONFIDENCE = 0.80


def _stage_table(ev):
    return [{"order": s.order, "key": s.key, "name": s.name, "status": s.status,
             "duration_s": s.duration_s, "summary": s.summary} for s in ev.record.stages]


def _base(ev: RunEvidence) -> dict:
    rec = ev.record
    return {
        "run_id": rec.run_id, "scenario": rec.scenario, "pipeline": rec.pipeline, "analyzer": ANALYZER,
        "generated_at": utcnow(), "status": rec.status, "outcome": rec.outcome, "failed_stage": rec.failed_stage,
        "commit": rec.commit, "duration_s": rec.duration_s, "stages": _stage_table(ev),
        "passed_work": [s.name for s in rec.stages if s.status == "PASS"],
        "failed_work": [s.name for s in rec.stages if s.status == "FAIL"],
        "skipped_work": [s.name for s in rec.stages if s.status == "SKIPPED"],
    }


def diagnose(run_dir) -> dict:
    ev = RunEvidence(run_dir)
    report = _base(ev)
    report.update(_success(ev) if ev.record.status == "SUCCESS" else _failure(ev))
    return report


# --------------------------------------------------------------------------- success
def _success(ev: RunEvidence) -> dict:
    rec = ev.record
    unit, integ = ev.test_summary("unit"), ev.test_summary("integration")
    lint_rep, manifest = ev.lint_report() or {}, ev.manifest() or {}
    integ_stage, deps = ev.stage("integration"), ev.stage("dependencies")
    probe = integ_stage.metrics.get("readiness_probe", {})
    tests = []
    for label, data in (("unit", unit), ("integration", integ)):
        if data:
            t = data["totals"]
            suites = sorted({c["test"].split("::")[0].split(".")[-1] for c in data["cases"]})
            tests.append({"suite": label, "total": t["tests"], "passed": t["passed"], "failed": t["failed"],
                          "skipped": t["skipped"], "time_s": t["time_s"], "modules": suites})
    total_tests = sum(t["total"] for t in tests)
    checks = [
        {"check": "Static analysis", "result": f"{lint_rep.get('python_files', 0)} Python files, "
                                               f"{lint_rep.get('errors', 0)} errors, {lint_rep.get('warnings', 0)} warnings",
         "rules": ", ".join(lint_rep.get("checks", []))},
        {"check": "Secret scan", "result": f"{lint_rep.get('files_secret_scanned', 0)} files scanned, "
                                           f"{lint_rep.get('secret_findings', 0)} findings"},
        {"check": "Dependency constraints", "result": f"{deps.metrics.get('declared', 0)} declared, all resolved; "
                                                      f"{len(deps.metrics.get('unbounded', []))} without upper bound"},
        {"check": "Artifact integrity", "result": f"sha256 {manifest.get('sha256', '?')[:16]}..., "
                                                  f"{len(manifest.get('files', []))} files checksummed, reproducible build"},
        {"check": "Version metadata", "result": f"pyproject and app.__version__ agree on {manifest.get('version')}"},
        {"check": "Deployment manifest policy", "result": f"environment={integ_stage.metrics.get('environment')}, "
                                                          "port range + probe path validated"},
        {"check": "Readiness probe", "result": f"GET {probe.get('path')} -> HTTP {probe.get('http_status')}"},
        {"check": "API contract tests", "result": f"{integ['totals']['passed'] if integ else 0} integration tests passed"},
    ]
    artifacts = [{"path": a["path"], "sha256": a["sha256"], "size_bytes": a["size_bytes"], "version": a["version"],
                  "files": a["files"]} for a in rec.artifacts]
    slowest = max(rec.stages, key=lambda s: s.duration_s)
    stage_explanations = [{"stage": s.name, "status": s.status, "duration_s": s.duration_s,
                           "what_it_did": STAGE_BY_KEY[s.key].purpose, "result": s.summary} for s in rec.stages]
    return {
        "title": "Healthy run - release candidate verified",
        "executive_summary": (
            f"Run {rec.run_id} PASSED all {len(rec.stages)} stages in {rec.duration_s:.2f}s for commit "
            f"'{rec.commit.get('message')}'. {total_tests} automated tests passed (0 failed), static analysis and "
            f"secret scanning were clean, and a checksummed artifact "
            f"({artifacts[0]['path'].split('/')[-1] if artifacts else 'n/a'}) was built and validated in an isolated "
            f"staging deployment. Conclusion: READY for promotion through the normal change-approval gate."),
        "pipeline_purpose": PIPELINE_PURPOSE,
        "stage_explanations": stage_explanations,
        "tests": tests,
        "artifacts": artifacts,
        "quality_checks": checks,
        "timing": {"total_s": rec.duration_s, "slowest_stage": slowest.name, "slowest_s": slowest.duration_s,
                   "started_at": rec.created_at, "finished_at": rec.finished_at},
        "root_cause": "No failure detected - no root-cause analysis required.",
        "evidence": [item(s.log_file, f"{s.name}: {s.status}", s.summary) for s in rec.stages],
        "impact": {"severity": "NONE", "area": "release", "blast_radius": [],
                   "customer_impact": "No adverse impact expected: verified by unit, contract and deployment tests.",
                   "production_impact": "None - this pipeline never deploys to production.",
                   "release_blocked": False},
        "release_readiness": {
            "ready": True, "verdict": "READY",
            "conditions": ["Change-approval for production promotion (human gate)",
                           "Deploy the exact artifact sha256 validated here - do not rebuild"],
        },
        "recommendation": "Promote this artifact to the next environment via the standard change process.",
        "proposed_changes": [],
        "validation_plan": ["Post-deploy: run readiness probe and smoke test against the target environment",
                            "Watch error rate / latency SLOs for 30 minutes after promotion"],
        "rollback_plan": ["Re-deploy the previously released artifact by its sha256 (immutable artifacts)",
                          "No configuration migration involved, so rollback is a pure redeploy"],
        "confidence": 0.97,
        "auto_remediable": False,
        "decision": "NO_ACTION_REQUIRED",
    }


# --------------------------------------------------------------------------- failure / partial
def _failure(ev: RunEvidence) -> dict:
    rec = ev.record
    finding = find_root_cause(ev)
    f = finding.to_dict()
    failed = ev.stage(rec.failed_stage)
    passed = [s.name for s in rec.stages if s.status == "PASS" and s.key != "publish"]
    reusable = [f"artifact {a['path']} (sha256 {a['sha256'][:12]})" for a in rec.artifacts]
    eligible = finding.auto_remediable and finding.confidence >= AUTO_FIX_MIN_CONFIDENCE
    if eligible:
        decision = "PROPOSE_FIX_PENDING_APPROVAL"
    else:
        decision = "ESCALATE_TO_ENGINEER"
        finding.escalation_reason = finding.escalation_reason or (
            f"confidence {finding.confidence:.0%} below auto-fix threshold {AUTO_FIX_MIN_CONFIDENCE:.0%}")
    kind = "PARTIAL SUCCESS" if rec.outcome == "partial_success" else "FAILED"
    summary = (f"Run {rec.run_id} {kind}: '{failed.name}' failed ({failed.summary}). "
               f"Root cause ({finding.confidence:.0%} confidence): {finding.title}. ")
    if rec.outcome == "partial_success":
        summary += (f"{len(passed)} earlier stages passed and their outputs are reusable "
                    f"({'; '.join(reusable) or 'none'}). ")
    summary += f"Production impact: {finding.impact['production_impact']} "
    summary += ("A minimal fix is proposed and awaits human approval." if eligible
                else f"Escalating to an engineer: {finding.escalation_reason}")

    files = [c["path"] for c in f["changes"]]
    targeted = finding.targeted_validation or [rec.failed_stage]
    validation = [f"Safety gate: allow-list, file-hash precondition, change-size limit, syntax check of {', '.join(files) or '-'}",
                  f"Targeted rerun: {', '.join(STAGE_BY_KEY[k].name for k in targeted)}"
                  + (" (reusing the already-built artifact)" if "package" not in targeted and reusable else ""),
                  "Full pipeline rerun (all 7 stages) on the patched workspace",
                  "Success is declared only if the full rerun status is SUCCESS"]
    rollback = ["Automatic: if targeted or full validation fails, restore the byte-for-byte backups and log it",
                "Manual: python -m ai_bot.remediate --run-id " + rec.run_id + " --rollback",
                "Source control: the patch is saved as a .diff; revert it like any commit"]
    return {
        "title": finding.title,
        "executive_summary": summary,
        "failure_class": finding.failure_class,
        "playbook": finding.playbook,
        "failed_stage_detail": {"key": failed.key, "name": failed.name, "summary": failed.summary,
                                "error": failed.error, "log_file": failed.log_file},
        "reusable_outputs": reusable,
        "root_cause": finding.root_cause,
        "evidence": f["evidence"],
        "impact": f["impact"],
        "recommendation": finding.recommendation,
        "fix_guide": finding.fix_steps,
        "alternatives_considered": finding.alternatives_considered,
        "proposed_changes": f["changes"],
        "targeted_validation": targeted,
        "validation_plan": validation,
        "rollback_plan": rollback,
        "confidence": finding.confidence,
        "confidence_factors": f["confidence_factors"],
        "auto_remediable": eligible,
        "escalation_reason": None if eligible else finding.escalation_reason,
        "decision": decision,
    }
