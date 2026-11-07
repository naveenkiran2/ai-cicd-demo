"""End-to-end demo driver: pipeline -> AI analysis -> (approved) self-healing -> outcome.

  python -m ai_bot.demo --scenario success
  python -m ai_bot.demo --scenario failure            # asks for approval interactively
  python -m ai_bot.demo --scenario partial --approve  # non-interactive approval
  python -m ai_bot.demo --scenario all --approve      # all three, back to back
  add --pause to wait for Enter between steps (presenter mode)
  add --export-samples to copy the results into reports/samples/<scenario>/
"""
import argparse
import shutil
import sys

from ai_bot import reports
from ai_bot.analyze import analyze_run
from ai_bot.remediate import EXIT_OK, remediate
from pipeline import console as c
from pipeline import workspace as ws
from pipeline.run import run_pipeline

SAMPLES_DIR = ws.PROJECT_ROOT / "reports" / "samples"


def _pause(enabled: bool, label: str) -> None:
    if enabled and sys.stdin.isatty():
        input(c.style(f"\n  [press Enter to continue: {label}] ", "cyan"))


def _step(title: str) -> None:
    print("\n" + c.style(f">>> {title}", "magenta", "bold"))


def _approval(args) -> bool:
    if args.approve:
        return True
    if not sys.stdin.isatty():
        print(c.badge("DRY RUN") + " no TTY and no --approve: the plan will be shown but not applied")
        return False
    answer = input(c.style("\n  Approve the proposed change for this run's workspace? [y/N] ", "bold"))
    return answer.strip().lower() in ("y", "yes")


def run_scenario(name: str, args) -> bool:
    print(c.banner(f"DEMO SCENARIO: {name.upper()}", ws.load_scenario(name)["title"]))
    _step("STEP 1  CI pipeline executes the commit")
    record, run_dir = run_pipeline(name)
    _pause(args.pause, "AI analysis")

    _step("STEP 2  AI bot analyses the run (logs, test reports, diff, source)")
    diagnosis = analyze_run(run_dir)
    verified = record.status == "SUCCESS"
    if record.status != "SUCCESS":
        _pause(args.pause, "self-healing")
        _step("STEP 3  Guided self-healing (human approval required)")
        code = remediate(run_dir, approve=_approval(args), approver=args.approver)
        final = reports.remediation_result(run_dir)
        verified = code == EXIT_OK and bool(final and final.get("verified"))

    _step("RESULT")
    if record.status == "SUCCESS":
        print(f"  {c.badge('PASS')} pipeline green; release verdict: "
              f"{c.badge(diagnosis['release_readiness']['verdict'])}")
    elif verified:
        final = reports.remediation_result(run_dir)
        print(f"  {c.badge('FAIL')} -> {c.badge('FIXED')} -> {c.badge('RERUN PASSED')}  "
              f"rerun {final['rerun_run_id']}; files changed: {', '.join(f['path'] for f in final['files_changed'])}")
    else:
        print(f"  {c.badge('FAIL')} not remediated (dry run, escalation or failed validation) - see bot/ reports")
    if args.export_samples:
        export_sample(name, run_dir, reports.remediation_result(run_dir))
    return verified


def export_sample(name: str, run_dir, final) -> None:
    """Copy a run (minus bulky workspace/staging copies) into reports/samples/<name>/."""
    dest = SAMPLES_DIR / name
    if dest.exists():
        shutil.rmtree(dest)  # only ever our own generated sample folder
    ignore = shutil.ignore_patterns("workspace", "staging", "__pycache__")
    shutil.copytree(run_dir, dest / "run", ignore=ignore)
    if final and final.get("rerun_run_id"):
        shutil.copytree(ws.RUNS_DIR / final["rerun_run_id"], dest / "rerun", ignore=ignore)
    print(f"  sample exported to {dest.relative_to(ws.PROJECT_ROOT)}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_bot.demo", description="Run the end-to-end demo")
    parser.add_argument("--scenario", required=True, choices=ws.SCENARIOS + ("all",))
    parser.add_argument("--approve", action="store_true", help="approve remediation non-interactively")
    parser.add_argument("--approver", help="name recorded in the audit trail")
    parser.add_argument("--pause", action="store_true", help="wait for Enter between steps")
    parser.add_argument("--export-samples", action="store_true", help="write results to reports/samples/")
    args = parser.parse_args(argv)
    names = ws.SCENARIOS if args.scenario == "all" else (args.scenario,)
    results = {name: run_scenario(name, args) for name in names}
    if len(names) > 1:
        print(c.section("Demo summary"))
        for name, ok in results.items():
            print(f"  {name:<8} {c.badge('PASS' if ok else 'FAIL')}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
