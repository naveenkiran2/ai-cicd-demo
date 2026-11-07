"""Pipeline entry point.

  python -m pipeline.run --scenario success|failure|partial
  python -m pipeline.run --from-run <run-id>      # rerun on that run's (patched) workspace
"""
import argparse
import platform
import sys
import time
import traceback

from pipeline import reporting, workspace as ws
from pipeline.models import RunRecord, StageResult, Status
from pipeline.stages import STAGE_BY_KEY, STAGES, RunContext, StageLog, StageOutcome

PACKAGE_ORDER = STAGE_BY_KEY["package"]
PACKAGE_INDEX = STAGES.index(PACKAGE_ORDER)


def run_stage(ctx: RunContext, stage, order: int, log_prefix: str = "") -> StageResult:
    result = StageResult(key=stage.key, name=stage.name, order=order)
    log_path = ctx.logs_dir / f"{log_prefix}{order:02d}_{stage.key}.log"
    log = StageLog(log_path)
    log.info(f"stage {stage.key}: {stage.purpose}")
    result.started_at, start = ws.utcnow(), time.perf_counter()
    try:
        outcome = stage.func(ctx, log)
    except Exception as exc:  # a crashing stage is a failed stage, never a silent pass
        log.error(f"stage crashed: {exc!r}")
        log.output(traceback.format_exc())
        outcome = StageOutcome(Status.FAIL, f"stage error: {exc}", error=repr(exc))
    result.duration_s = round(time.perf_counter() - start, 3)
    result.finished_at = ws.utcnow()
    result.status = Status(outcome.status).value
    result.summary, result.metrics, result.error, result.reports = (
        outcome.summary, outcome.metrics, outcome.error, outcome.reports)
    log.info(f"stage {stage.key} finished: {result.status} in {result.duration_s}s")
    log.close()
    result.log_file = ctx.rel(log_path)
    return result


def run_pipeline(scenario_name: str, *, source_workspace=None, parent_run_id=None, trigger="manual",
                 commit=None, options=None, echo=True):
    scenario = ws.load_scenario(scenario_name)
    run_id = ws.rerun_id(parent_run_id) if parent_run_id else ws.new_run_id(scenario_name)
    run_dir = ws.RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    opts = dict(options or {})
    if source_workspace:
        opts["source_workspace"] = str(source_workspace)
        opts["commit_diff"] = (commit or {}).get("diff", "")
    ctx = RunContext(run_id=run_id, run_dir=run_dir, workspace=run_dir / "workspace", scenario=scenario, options=opts)
    commit_info = dict(scenario.get("commit", {}))
    if commit:
        commit_info.update({k: v for k, v in commit.items() if k != "diff"})
    record = RunRecord(run_id=run_id, scenario=scenario_name, created_at=ws.utcnow(), trigger=trigger,
                       parent_run_id=parent_run_id, commit=commit_info,
                       environment={"python": platform.python_version(), "platform": platform.platform(),
                                    "executor": "local"})
    ctx.state["record"] = record
    record.stages = [StageResult(key=s.key, name=s.name, order=i + 1) for i, s in enumerate(STAGES)]
    if echo:
        print(reporting.render_header(record))
    start = time.perf_counter()
    failed = None
    for index, stage in enumerate(STAGES):
        if failed and not stage.always_run:
            skipped = record.stages[index]
            skipped.summary = f"skipped: upstream stage '{failed}' failed"
            if echo:
                print(reporting.stage_line(skipped, len(STAGES)))
            continue
        if stage.key == "publish":  # finalise status before the report is written
            record.status = "FAILED" if failed else "SUCCESS"
            record.failed_stage = failed
            record.outcome = _outcome(record)
            record.duration_s = round(time.perf_counter() - start, 3)
        result = run_stage(ctx, stage, index + 1)
        record.stages[index] = result
        if stage.key == "checkout":
            record.commit["sha"] = result.metrics.get("tree_sha", "unknown")
        if stage.key == "package" and result.status == "PASS":
            m = result.metrics
            record.artifacts.append({"path": m["artifact"], "sha256": m["sha256"], "size_bytes": m["size_bytes"],
                                     "version": m["version"], "files": m["files"]})
        if echo:
            print(reporting.stage_line(result, len(STAGES)))
        if result.status == "FAIL" and not failed:
            failed = stage.key
    record.status = "FAILED" if failed else "SUCCESS"
    record.failed_stage = failed
    record.outcome = _outcome(record)
    record.duration_s = round(time.perf_counter() - start, 3)
    record.finished_at = ws.utcnow()
    record.save(run_dir)
    (run_dir / "summary.md").write_text(reporting.summary_markdown(record), encoding="utf-8")
    if echo:
        print(reporting.render_footer(record, run_dir))
    return record, run_dir


def _outcome(record: RunRecord) -> str:
    if not record.failed_stage:
        return "success"
    failed_index = [s.key for s in STAGES].index(record.failed_stage)
    package = record.stages[PACKAGE_INDEX]
    return "partial_success" if failed_index > PACKAGE_INDEX and package.status == "PASS" else "failure"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.run", description="Run the local CI/CD pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", choices=ws.SCENARIOS, help="demo scenario to run")
    group.add_argument("--from-run", metavar="RUN_ID", help="rerun the pipeline on an existing run's workspace")
    parser.add_argument("--install-deps", action="store_true", help="pip install missing requirements")
    args = parser.parse_args(argv)
    options = {"install_deps": args.install_deps}
    if args.from_run:
        parent_dir = ws.resolve_run_dir(args.from_run)
        parent = RunRecord.load(parent_dir)
        record, _ = run_pipeline(parent.scenario, source_workspace=parent_dir / "workspace",
                                 parent_run_id=parent.run_id, trigger="manual-rerun",
                                 commit={"message": f"manual rerun of {parent.run_id}"}, options=options)
    else:
        record, _ = run_pipeline(args.scenario, options=options)
    return 0 if record.status == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
