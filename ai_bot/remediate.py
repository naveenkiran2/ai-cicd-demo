"""Safe self-healing workflow for a failed pipeline run.

  python -m ai_bot.remediate --run-id <id>              # dry run: plan + safety gate, no changes
  python -m ai_bot.remediate --run-id <id> --approve    # apply, validate, rerun, report
  python -m ai_bot.remediate --run-id <id> --rollback   # restore the pre-fix backups

Ten steps: detect -> classify -> evidence -> propose -> approval/safety gate ->
backup -> apply -> targeted validation -> full rerun -> audit + final report.
A run is reported as fixed only when the full pipeline rerun actually passes;
any failed validation automatically restores the backups.
"""
import argparse
import getpass
import json
import os
import shutil
import sys
from pathlib import Path

from ai_bot import reports, safety
from ai_bot.analyze import analyze_run
from ai_bot.diagnose import diagnose
from pipeline import console as c
from pipeline import workspace as ws
from pipeline.models import RunRecord
from pipeline.run import run_pipeline, run_stage
from pipeline.stages import STAGE_BY_KEY, STAGES, RunContext

TOTAL_STEPS = 10
EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_ESCALATED = 0, 1, 2, 3


class Audit:
    """Append-only JSONL audit trail (who/what/when/outcome for every step)."""

    def __init__(self, path: Path, run_id: str):
        self.path, self.run_id = path, run_id
        path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, step: str, action: str, outcome: str, actor: str = "ai-cicd-bot", **details) -> None:
        event = {"ts": ws.utcnow(), "run_id": self.run_id, "step": step, "actor": actor, "action": action,
                 "outcome": outcome, "details": details}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")


def step(n: int, title: str, status: str, detail: str = "") -> None:
    label = f"[{n:02d}/{TOTAL_STEPS}] {title} "
    print(f"  {label}{c.style('.' * max(2, 42 - len(label)), 'grey')} {c.badge(status, 13)} {detail}")


def _approver(explicit):
    if explicit:
        return explicit
    try:
        return os.environ.get("USER") or os.environ.get("USERNAME") or getpass.getuser()
    except Exception:
        return "unknown"


def _load_diagnosis(run_dir: Path) -> dict:
    """Use the diagnosis a human reviewed (bot/diagnosis.json); create one if absent."""
    stored = reports.load_json(run_dir / reports.BOT_DIR / "diagnosis.json")
    return stored if stored else analyze_run(run_dir, echo=False)


def remediate(run_dir: Path, approve: bool, approver=None, echo_pipeline=True) -> int:
    run_dir = Path(run_dir)
    record = RunRecord.load(run_dir)
    rem_dir = reports.bot_dir(run_dir) / "remediation"
    audit = Audit(rem_dir / "audit.jsonl", record.run_id)
    approver = _approver(approver)
    print(c.banner(f"AI CI/CD BOT  self-healing remediation  run {record.run_id}",
                   "mode: " + ("APPLY (approved)" if approve else "DRY RUN (no files will be modified)")))

    existing = reports.load_json(rem_dir / "change_record.json")
    if existing and existing.get("status") in ("applied", "verified"):
        print(c.badge("BLOCKED") + f" run already remediated (status={existing['status']}); see "
              f"{(rem_dir / 'final_report.md').relative_to(ws.PROJECT_ROOT)}. Use --rollback to undo.")
        return EXIT_REFUSED

    # 1. detect
    if record.status == "SUCCESS":
        step(1, "Detect failure", "PASS", "pipeline succeeded - nothing to remediate")
        audit.log("detect", "inspect run", "no-failure")
        return EXIT_OK
    failed = record.stage(record.failed_stage)
    step(1, "Detect failure", "FAIL", f"{failed.name}: {failed.summary}")
    audit.log("detect", "inspect run", "failure-detected", stage=failed.key, summary=failed.summary)

    # 2-3. classify + evidence
    d = _load_diagnosis(run_dir)
    step(2, "Classify failure", "INFO", f"{d['failure_class']}  ({d['playbook']}, {d['confidence']:.0%})")
    sources = sorted({e["source"].split(":")[0] for e in d["evidence"]})
    step(3, "Gather evidence", "INFO", f"{len(d['evidence'])} items from {', '.join(sources)}")
    audit.log("classify", "rule-engine diagnosis", d["decision"], playbook=d["playbook"], confidence=d["confidence"],
              failure_class=d["failure_class"], evidence=len(d["evidence"]))

    # 4. propose
    plan = {
        "run_id": record.run_id, "created_at": ws.utcnow(), "title": d["title"], "playbook": d["playbook"],
        "confidence": d["confidence"], "changes": d["proposed_changes"], "targeted_validation": d["targeted_validation"],
        "validation_plan": d["validation_plan"], "rollback_plan": d["rollback_plan"],
        "safety_policy": {"allowed": safety.ALLOWED_GLOBS, "denied": safety.DENIED_GLOBS,
                          "max_files": safety.MAX_FILES, "max_changed_lines": safety.MAX_CHANGED_LINES},
    }
    reports.save_json(reports.bot_dir(run_dir) / "remediation_plan.json", plan)
    if not d["proposed_changes"] or not d["auto_remediable"]:
        step(4, "Propose minimal remediation", "ESCALATE", d.get("escalation_reason") or "no safe change")
        audit.log("propose", "build plan", "escalated", reason=d.get("escalation_reason"))
        _final(run_dir, record, d, "ESCALATED", approver if approve else None, [], None, None, audit)
        print(c.wrap("Escalated to a human engineer. Fix guide: " + " | ".join(d["fix_guide"])))
        return EXIT_ESCALATED
    changes = d["proposed_changes"]
    step(4, "Propose minimal remediation", "INFO",
         f"{len(changes)} file(s): " + ", ".join(f"{ch['path']}:{ch['line']}" for ch in changes))
    for ch in changes:
        print(c.style(f"{'':12}- {ch['old'].strip()}", "red"))
        print(c.style(f"{'':12}+ {ch['new'].strip()}", "green"))
    audit.log("propose", "build plan", "proposed", files=[ch["path"] for ch in changes])

    # 5. safety gate + approval
    workspace = run_dir / "workspace"
    checks = safety.evaluate(d, workspace, approve)
    reports.save_json(rem_dir / "safety_checks.json", checks)
    failed_checks = [x for x in checks if not x["passed"]]
    if not approve and [x["check"] for x in failed_checks] == ["human-approval"]:
        step(5, "Safety gate & human approval", "DRY RUN",
             f"{len(checks) - 1}/{len(checks) - 1} policy checks pass; awaiting approval")
        audit.log("approve", "request approval", "pending", checks_passed=len(checks) - 1)
        print(c.style(f"\n  No files were modified. To apply this change run:\n"
                      f"    python -m ai_bot.remediate --run-id {record.run_id} --approve", "cyan"))
        return EXIT_OK
    if failed_checks:
        step(5, "Safety gate & human approval", "BLOCKED", "; ".join(x["check"] for x in failed_checks))
        for x in failed_checks:
            print(f"{'':12}{c.badge('FAIL')} {x['check']}: {x['detail']}")
        audit.log("approve", "safety gate", "blocked", failed=failed_checks)
        _final(run_dir, record, d, "BLOCKED", approver, [], None, None, audit)
        return EXIT_REFUSED
    step(5, "Safety gate & human approval", "PASS", f"{len(checks)}/{len(checks)} checks; approved by {approver}")
    audit.log("approve", "human approval", "approved", actor=approver, checks=len(checks))

    # 6. backup + patch record
    backups_dir = rem_dir / "backups"
    patch, files = [], []
    for ch in changes:
        target = workspace / ch["path"]
        backup = backups_dir / (ch["path"] + ".orig")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        before = target.read_text(encoding="utf-8")
        after = before.replace(ch["old"], ch["new"], 1)
        patch.append(ws.unified_diff(ch["path"], before, after))
        files.append({"path": ch["path"], "line": ch["line"], "backup": backup.relative_to(run_dir).as_posix(),
                      "sha256_before": ch["sha256_before"], "after_text": after})
    patch_text = "".join(patch)
    (rem_dir / "patch.diff").write_text(patch_text, encoding="utf-8")
    change_record = {"run_id": record.run_id, "status": "pending", "approved_by": approver, "approved_at": ws.utcnow(),
                     "playbook": d["playbook"], "files": [{k: v for k, v in f.items() if k != "after_text"}
                                                          for f in files]}
    reports.save_json(rem_dir / "change_record.json", change_record)
    step(6, "Backup & patch record", "PASS", f"{len(files)} backup(s) + bot/remediation/patch.diff")
    audit.log("backup", "write backups and patch", "ok", backups=[f["backup"] for f in files])

    # 7. apply
    for f, entry in zip(files, change_record["files"]):
        target = workspace / f["path"]
        target.write_text(f["after_text"], encoding="utf-8")
        entry["sha256_after"] = ws.sha256_file(target)
    change_record["status"] = "applied"
    reports.save_json(rem_dir / "change_record.json", change_record)
    step(7, "Apply allow-listed change", "FIXED", ", ".join(
        f"{e['path']} {e['sha256_before'][:8]}->{e['sha256_after'][:8]}" for e in change_record["files"]))
    audit.log("apply", "write patched files", "applied", files=change_record["files"])

    # 8. targeted validation (failed stage first, reusing upstream outputs)
    step(8, "Targeted validation", "INFO", "rerunning only: " + ", ".join(d["targeted_validation"]))
    targeted = _targeted(run_dir, record, d["targeted_validation"])
    t_ok = all(r.status == "PASS" for r in targeted)
    reports.save_json(rem_dir / "targeted_validation.json", [r.__dict__ for r in targeted])
    print(f"{'':12}=> {c.badge('RERUN PASSED' if t_ok else 'FAIL')}")
    audit.log("validate-targeted", "rerun affected stages", "passed" if t_ok else "failed",
              stages={r.key: r.status for r in targeted})
    if not t_ok:
        _rollback(run_dir, audit, reason="targeted validation failed")
        _final(run_dir, record, d, "ROLLED BACK", approver, change_record["files"], targeted, None, audit)
        return EXIT_FAILED

    # 9. full pipeline rerun on the patched workspace
    step(9, "Full pipeline rerun", "INFO", "all 7 stages on the patched workspace")
    rerun, rerun_dir = run_pipeline(
        record.scenario, source_workspace=workspace, parent_run_id=record.run_id, trigger="ai-bot-remediation",
        commit={"message": f"ai-bot fix: {d['title']}", "author": f"ai-cicd-bot (approved by {approver})",
                "branch": f"bot/fix-{record.run_id}", "diff": patch_text}, echo=echo_pipeline)
    audit.log("validate-full", "full pipeline rerun", rerun.status, rerun_run_id=rerun.run_id)
    if rerun.status != "SUCCESS":
        _rollback(run_dir, audit, reason=f"full rerun {rerun.run_id} failed")
        _final(run_dir, record, d, "ROLLED BACK", approver, change_record["files"], targeted, rerun, audit)
        return EXIT_FAILED
    change_record["status"] = "verified"
    reports.save_json(rem_dir / "change_record.json", change_record)
    reports.write_diagnosis(rerun_dir, diagnose(rerun_dir))  # release-readiness report for the green rerun

    # 10. audit + final report
    final = _final(run_dir, record, d, "RERUN PASSED", approver, change_record["files"], targeted, rerun, audit)
    step(10, "Audit trail & final report", "RERUN PASSED", "bot/remediation/final_report.md")
    print("\n".join(reports.render_remediation_summary(final)))
    return EXIT_OK


def _targeted(run_dir: Path, record: RunRecord, keys: list) -> list:
    tdir = run_dir / reports.BOT_DIR / "remediation" / "targeted"
    artifact = next(iter(record.artifacts), None)
    ctx = RunContext(run_id=f"{record.run_id}-targeted", run_dir=tdir, workspace=run_dir / "workspace",
                     scenario=ws.load_scenario(record.scenario),
                     options={"reuse_artifact": str(run_dir / artifact["path"]) if artifact else None})
    results = []
    for key in keys:
        order = [s.key for s in STAGES].index(key) + 1
        result = run_stage(ctx, STAGE_BY_KEY[key], order)
        print(f"{'':10}{c.style('[targeted]', 'cyan')}{_stage_text(result)}")
        results.append(result)
        if result.status != "PASS":
            break
    return results


def _stage_text(r) -> str:
    return f" {r.name} {c.style('.' * max(2, 38 - len(r.name)), 'grey')} {c.badge(r.status, 7)} " \
           f"{r.duration_s:5.2f}s  {c.style(r.summary, 'grey')}"


def _rollback(run_dir: Path, audit: Audit, reason: str, actor: str = "ai-cicd-bot") -> bool:
    rem_dir = run_dir / reports.BOT_DIR / "remediation"
    record = reports.load_json(rem_dir / "change_record.json")
    if not record or record.get("status") not in ("applied", "verified"):
        print(c.badge("BLOCKED") + " nothing to roll back")
        return False
    for f in record["files"]:
        target = run_dir / "workspace" / f["path"]
        if f.get("sha256_after") and ws.sha256_file(target) != f["sha256_after"]:
            print(c.badge("BLOCKED") + f" {f['path']} changed since the fix; refusing to overwrite")
            audit.log("rollback", "restore backups", "refused", actor=actor, file=f["path"])
            return False
    for f in record["files"]:
        shutil.copy2(run_dir / f["backup"], run_dir / "workspace" / f["path"])
    record["status"] = "rolled_back"
    record["rolled_back_reason"] = reason
    reports.save_json(rem_dir / "change_record.json", record)
    audit.log("rollback", "restore backups", "restored", actor=actor, reason=reason,
              files=[f["path"] for f in record["files"]])
    print(f"  {c.badge('ROLLED BACK')} restored {len(record['files'])} file(s) from backup ({reason})")
    return True


def _final(run_dir, record, d, label, approver, files, targeted, rerun, audit) -> dict:
    rem_dir = run_dir / reports.BOT_DIR / "remediation"
    tmap = {r.key: r.status for r in (targeted or [])}
    comparison = [{"key": s.key, "name": s.name, "before": s.status, "targeted": tmap.get(s.key, ""),
                   "after": rerun.stage(s.key).status if rerun else "-"} for s in record.stages]
    final = {
        "run_id": record.run_id, "result_label": label, "verified": label == "RERUN PASSED",
        "title": d["title"], "playbook": d["playbook"], "confidence": d["confidence"],
        "approved_by": approver, "finished_at": ws.utcnow(),
        "before": {"status": record.status, "outcome": record.outcome, "failed_stage": record.failed_stage},
        "after": {"status": rerun.status, "outcome": rerun.outcome, "run_id": rerun.run_id} if rerun else None,
        "rerun_run_id": rerun.run_id if rerun else None,
        "targeted_validation": [{"stage": r.key, "status": r.status, "summary": r.summary} for r in (targeted or [])],
        "files_changed": [f for f in files if f.get("sha256_after")] if label == "RERUN PASSED" else [],
        "files_touched_then_restored": [f["path"] for f in files] if label == "ROLLED BACK" else [],
        "comparison": comparison,
        "patch": "bot/remediation/patch.diff" if files else None,
        "audit_log": "bot/remediation/audit.jsonl",
    }
    reports.save_json(rem_dir / "final_report.json", final)
    reports.save_json(run_dir / reports.BOT_DIR / "validation.json", {
        "verified": final["verified"], "targeted": final["targeted_validation"],
        "full_rerun": {"run_id": rerun.run_id, "status": rerun.status,
                       "stages": {s.key: s.status for s in rerun.stages}} if rerun else None})
    (rem_dir / "final_report.md").write_text(_final_md(final), encoding="utf-8")
    reports.write_diagnosis(run_dir, d)  # refresh diagnosis.md with the final outcome section
    audit.log("report", "write final report", label)
    return final


def _final_md(f: dict) -> str:
    rows = "\n".join(f"| {r['name']} | {r['before']} | {r['targeted'] or '-'} | {r['after']} |" for r in f["comparison"])
    files = "\n".join(f"- `{x['path']}` line {x['line']}: sha256 `{x['sha256_before'][:12]}` -> "
                      f"`{x['sha256_after'][:12]}` (backup `{x['backup']}`)" for x in f["files_changed"]) or "- none"
    return f"""# Remediation report - run `{f['run_id']}`

**Result: {f['result_label']}** - verified: {f['verified']}

| Field | Value |
|---|---|
| Fix | {f['title']} |
| Playbook | {f['playbook']} (confidence {f['confidence']:.0%}) |
| Approved by | {f['approved_by']} |
| Before | {f['before']['status']} ({f['before']['outcome']}, failed at `{f['before']['failed_stage']}`) |
| After | {(f['after'] or {}).get('status', '-')} (rerun `{f['rerun_run_id'] or '-'}`) |

## Before / after

| Stage | Before | Targeted rerun | Full rerun |
|---|---|---|---|
{rows}

## Files changed

{files}

Patch: `{f['patch']}` - Audit trail: `{f['audit_log']}`
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_bot.remediate", description="Safe self-healing for a run")
    parser.add_argument("--run-id", required=True, help="run id, 'latest' or 'latest-<scenario>'")
    parser.add_argument("--approve", action="store_true", help="explicit human approval to modify files")
    parser.add_argument("--approver", help="name recorded in the audit trail (default: $USER)")
    parser.add_argument("--rollback", action="store_true", help="restore backups of a previously applied fix")
    args = parser.parse_args(argv)
    run_dir = ws.resolve_run_dir(args.run_id)
    if args.rollback:
        audit = Audit(run_dir / reports.BOT_DIR / "remediation" / "audit.jsonl", run_dir.name)
        ok = _rollback(run_dir, audit, reason="manual rollback", actor=_approver(args.approver))
        return EXIT_OK if ok else EXIT_REFUSED
    return remediate(run_dir, args.approve, args.approver)


if __name__ == "__main__":
    sys.exit(main())
