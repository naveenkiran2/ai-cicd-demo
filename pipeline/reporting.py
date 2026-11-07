"""Run-level reporting: run.json, summary.md and terminal rendering."""
from pathlib import Path

from pipeline import console as c
from pipeline.models import RunRecord, StageResult

OUTCOME_LABEL = {"success": "SUCCESS", "failure": "FAILED", "partial_success": "PARTIAL SUCCESS"}


def stage_line(result: StageResult, total: int) -> str:
    label = f"[{result.order}/{total}] {result.name} "
    dots = "." * max(2, 44 - len(label))
    timing = f"{result.duration_s:6.2f}s" if result.status != "SKIPPED" else "      -"
    return f"  {label}{c.style(dots, 'grey')} {c.badge(result.status, 7)} {timing}  {c.style(result.summary, 'grey')}"


def render_header(record: RunRecord) -> str:
    commit = record.commit
    sub = f"scenario={record.scenario}  branch={commit.get('branch', '-')}  author={commit.get('author', '-')}"
    sub += f"\n  commit: \"{commit.get('message', '')}\""
    if record.parent_run_id:
        sub += f"\n  rerun of {record.parent_run_id} (trigger: {record.trigger})"
    return c.banner(f"CI PIPELINE  {record.pipeline}  run {record.run_id}", sub)


def render_footer(record: RunRecord, run_dir: Path) -> str:
    label = OUTCOME_LABEL.get(record.outcome, record.status)
    lines = [c.section("Result"),
             f"  Pipeline status : {c.badge(record.status)}   outcome: {c.badge(label)}"]
    if record.failed_stage:
        failed = record.stage(record.failed_stage)
        lines.append(f"  Failed stage    : {failed.name}  ({failed.error or failed.summary})")
    lines.append(f"  Duration        : {record.duration_s:.2f}s")
    lines.append(f"  Run directory   : {run_dir.relative_to(Path.cwd()) if run_dir.is_relative_to(Path.cwd()) else run_dir}")
    if record.status != "SUCCESS" and not record.parent_run_id:
        lines.append(c.style(f"\n  Next: python -m ai_bot.analyze --run-id {record.run_id}", "cyan"))
    elif not record.parent_run_id:
        lines.append(c.style(f"\n  Explain this run: python -m ai_bot.analyze --run-id {record.run_id}", "cyan"))
    return "\n".join(lines)


def summary_markdown(record: RunRecord) -> str:
    label = OUTCOME_LABEL.get(record.outcome, record.status)
    rows = "\n".join(f"| {s.order} | {s.name} | **{s.status}** | {s.duration_s:.2f}s | {s.summary} |"
                     for s in record.stages)
    artifacts = "\n".join(f"- `{a['path']}` sha256 `{a['sha256'][:16]}...` ({a['size_bytes']} bytes)"
                          for a in record.artifacts) or "- none (pipeline stopped before packaging)"
    return f"""# Pipeline run `{record.run_id}`

| Field | Value |
|---|---|
| Pipeline | {record.pipeline} |
| Scenario | {record.scenario} |
| Commit | `{record.commit.get('sha')}` - {record.commit.get('message')} |
| Status | **{record.status}** ({label}) |
| Failed stage | {record.failed_stage or '-'} |
| Trigger | {record.trigger}{' (parent ' + record.parent_run_id + ')' if record.parent_run_id else ''} |
| Started | {record.created_at} |
| Duration | {record.duration_s:.2f}s |

## Stages

| # | Stage | Status | Duration | Summary |
|---|---|---|---|---|
{rows}

## Artifacts

{artifacts}

Logs: `logs/`  -  Test reports: `test-reports/`  -  Commit diff: `commit.diff`
"""


def publish(ctx) -> list:
    record: RunRecord = ctx.state["record"]
    md = ctx.run_dir / "summary.md"
    md.write_text(summary_markdown(record), encoding="utf-8")
    return [record.save(ctx.run_dir), md]
