"""Analyze a pipeline run and produce the incident / release report.

  python -m ai_bot.analyze --run-id <id|latest|latest-failure>
  python -m ai_bot.analyze --run-id <id> --json      # machine-readable output
"""
import argparse
import json
import sys

from ai_bot import llm_adapter, reports
from ai_bot.diagnose import diagnose
from pipeline import workspace as ws


def analyze_run(run_dir, echo=True) -> dict:
    diagnosis = llm_adapter.enrich(diagnose(run_dir))
    paths = reports.write_diagnosis(run_dir, diagnosis)
    if echo:
        print(reports.render_text(diagnosis, reports.remediation_result(run_dir)))
        print("\n  Reports: " + ", ".join(str(p.relative_to(ws.PROJECT_ROOT)) for p in paths))
    return diagnosis


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_bot.analyze", description=__doc__.splitlines()[1])
    parser.add_argument("--run-id", required=True, help="run id, 'latest' or 'latest-<scenario>'")
    parser.add_argument("--json", action="store_true", help="print the JSON report instead of text")
    args = parser.parse_args(argv)
    run_dir = ws.resolve_run_dir(args.run_id)
    if args.json:
        print(json.dumps(analyze_run(run_dir, echo=False), indent=2, default=str))
    else:
        analyze_run(run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
