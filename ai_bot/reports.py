"""Render diagnosis / remediation results as terminal text, Markdown and JSON."""
import json
from pathlib import Path

from pipeline import console as c

BOT_DIR = "bot"
OUTCOME = {"success": "SUCCESS", "failure": "FAILED", "partial_success": "PARTIAL SUCCESS"}


def bot_dir(run_dir: Path) -> Path:
    path = Path(run_dir) / BOT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None


def save_json(path: Path, data) -> Path:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return Path(path)


def remediation_result(run_dir: Path):
    return load_json(Path(run_dir) / BOT_DIR / "remediation" / "final_report.json")


# --------------------------------------------------------------------------- terminal
def render_text(d: dict, remediation=None) -> str:
    out = [c.banner(f"AI CI/CD BOT  incident analysis  run {d['run_id']}",
                    f"{d['analyzer']}  |  scenario={d['scenario']}")]
    out.append(c.section("1. Executive summary"))
    out.append(c.wrap(d["executive_summary"]))

    out.append(c.section("2. Pipeline status"))
    status = OUTCOME.get(d["outcome"], d["status"])
    out.append(f"  Status: {c.badge(d['status'])}   Outcome: {c.badge(status)}   "
               f"Failed stage: {d['failed_stage'] or '-'}   Duration: {d['duration_s']:.2f}s")
    out.append(f"  Commit: {d['commit'].get('sha')}  \"{d['commit'].get('message')}\"  by {d['commit'].get('author', '-')}")

    out.append(c.section("3. Stage-by-stage status"))
    out.append(c.table(["#", "Stage", "Status", "Time", "Result"],
                       [[s["order"], s["name"], c.badge(s["status"]),
                         f"{s['duration_s']:.2f}s" if s["status"] != "SKIPPED" else "-", s["summary"][:48]]
                        for s in d["stages"]]))
    if d["status"] != "SUCCESS":
        out.append(f"\n  {c.style('Passed work :', 'green')} {', '.join(d['passed_work']) or '-'}")
        out.append(f"  {c.style('Failed work :', 'red')} {', '.join(d['failed_work'])}")
        out.append(f"  {c.style('Not run     :', 'grey')} {', '.join(d['skipped_work']) or '-'}")
        if d.get("reusable_outputs"):
            out.append(f"  {c.style('Reusable    :', 'cyan')} {'; '.join(d['reusable_outputs'])}")

    if d["status"] == "SUCCESS":
        out += _success_sections(d)
    else:
        out += _failure_sections(d)

    if remediation:
        out += render_remediation_summary(remediation)
    elif d["status"] != "SUCCESS":
        out.append(c.section("11. Final outcome"))
        out.append("  Remediation not run yet.")
        if d["auto_remediable"]:
            out.append(c.style(f"  Preview : python -m ai_bot.remediate --run-id {d['run_id']}", "cyan"))
            out.append(c.style(f"  Apply   : python -m ai_bot.remediate --run-id {d['run_id']} --approve", "cyan"))
    if d.get("llm_narrative"):
        n = d["llm_narrative"]
        out.append(c.section(f"LLM narrative (advisory only - {n['provider']} {n.get('model', '')})"))
        out.append(c.wrap(n["text"]))
    return "\n".join(out)


def _success_sections(d):
    out = [c.section("4. What this pipeline does"), c.wrap(d["pipeline_purpose"]), ""]
    for i, s in enumerate(d["stage_explanations"], 1):
        out.append(f"  {i}. {c.style(s['stage'], 'bold')}  {c.badge(s['status'])}  ({s['duration_s']:.2f}s)")
        out.append(f"     did   : {s['what_it_did']}")
        out.append(c.style(f"     result: {s['result']}", "grey"))
    out.append(c.section("5. Tests executed"))
    out.append(c.table(["Suite", "Total", "Passed", "Failed", "Skipped", "Time", "Modules"],
                       [[t["suite"], t["total"], t["passed"], t["failed"], t["skipped"], f"{t['time_s']:.2f}s",
                         ", ".join(t["modules"])] for t in d["tests"]]))
    out.append(c.section("6. Artifacts generated"))
    for a in d["artifacts"]:
        out.append(f"  {a['path']}  v{a['version']}  {a['size_bytes']} bytes  {a['files']} files")
        out.append(c.style(f"    sha256:{a['sha256']}", "grey"))
    out.append(c.section("7. Quality & security checks"))
    out.append(c.table(["Check", "Result"], [[q["check"], c.badge("PASS") + "  " + q["result"]]
                                             for q in d["quality_checks"]]))
    t = d["timing"]
    out.append(c.section("8. Timing"))
    out.append(f"  Total {t['total_s']:.2f}s; slowest stage: {t['slowest_stage']} ({t['slowest_s']:.2f}s)")
    out.append(f"  Started {t['started_at']}  finished {t['finished_at']}")
    out.append(c.section("9. Risk, validation & rollback"))
    out.append(f"  Risk: {d['impact']['severity']} - {d['impact']['customer_impact']}")
    out.append("  Validation plan:\n" + c.bullets(d["validation_plan"], 4))
    out.append("  Rollback plan:\n" + c.bullets(d["rollback_plan"], 4))
    r = d["release_readiness"]
    out.append(c.section("10. Release readiness"))
    out.append(f"  Verdict: {c.badge(r['verdict'])}  (confidence {d['confidence']:.0%})")
    out.append(c.bullets([f"Condition: {x}" for x in r["conditions"]], 4))
    return out


def _failure_sections(d):
    out = [c.section("4. Root-cause analysis")]
    out.append(f"  {c.style(d['title'], 'bold')}")
    out.append(f"  Class: {d['failure_class']}   Playbook: {d['playbook']}")
    out.append(c.wrap(d["root_cause"]))
    confidence = f"{d['confidence']:.0%}"
    out.append(f"\n  Confidence: {c.style(confidence, 'bold')}")
    for f in d["confidence_factors"]:
        out.append(c.style(f"    +{f['weight']:.2f}  {f['signal']}", "grey"))

    out.append(c.section("5. Supporting evidence"))
    for i, e in enumerate(d["evidence"], 1):
        out.append(f"  [{i}] {e['finding']}")
        out.append(c.style(f"      source: {e['source']}", "grey"))
        for line in e["excerpt"].splitlines()[:5]:
            out.append(c.style(f"      | {line}", "grey"))

    imp = d["impact"]
    out.append(c.section("6. Impact & risk assessment"))
    sev_color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}.get(imp["severity"], "magenta")
    out.append(f"  Severity: {c.style(imp['severity'], sev_color, 'bold')}   Area: {imp['area']}   "
               f"Release blocked: {'yes' if imp['release_blocked'] else 'no'}")
    out.append("  Blast radius:\n" + c.bullets(imp["blast_radius"], 4))
    out.append(f"  Customer impact if shipped: {imp['customer_impact']}")
    out.append(f"  Production impact now:      {imp['production_impact']}")

    out.append(c.section("7. Recommended solution & fix guide"))
    out.append(c.wrap(d["recommendation"]))
    out.append(c.bullets([f"{i}. {s}" for i, s in enumerate(d["fix_guide"], 1)], 4, ""))
    if d.get("alternatives_considered"):
        out.append("  Alternatives considered:\n" + c.bullets(d["alternatives_considered"], 4))

    out.append(c.section("8. Files proposed for modification"))
    if d["proposed_changes"]:
        for ch in d["proposed_changes"]:
            out.append(f"  {c.style(ch['path'], 'bold')}:{ch['line']}  ({ch['reason']})")
            out.append(c.style(f"    - {ch['old'].strip()}", "red"))
            out.append(c.style(f"    + {ch['new'].strip()}", "green"))
    else:
        out.append("  None - no safe automatic change identified.")
    if not d["auto_remediable"]:
        out.append(f"  {c.badge('ESCALATE')} {d['escalation_reason']}")

    out.append(c.section("9. Validation plan"))
    out.append(c.bullets([f"{i}. {s}" for i, s in enumerate(d["validation_plan"], 1)], 4, ""))
    out.append(c.section("10. Rollback plan"))
    out.append(c.bullets(d["rollback_plan"], 4))
    return out


def render_remediation_summary(r: dict) -> list:
    out = [c.section("11. Final outcome after remediation")]
    out.append(f"  Result: {c.badge(r['result_label'])}   approved by: {r.get('approved_by', '-')}")
    out.append(c.table(["Stage", "Before", "Targeted", "Full rerun"],
                       [[row["name"], c.badge(row["before"]), c.badge(row["targeted"]) if row["targeted"] else "-",
                         c.badge(row["after"])] for row in r["comparison"]]))
    out.append("  Files changed:")
    for f in r["files_changed"]:
        out.append(f"    {f['path']}  sha256 {f['sha256_before'][:10]} -> {f['sha256_after'][:10]}")
    if not r["files_changed"]:
        out.append("    none")
    out.append(f"  Rerun run id: {r.get('rerun_run_id') or '-'}")
    out.append(f"  Audit trail : {r['audit_log']}")
    return out


# --------------------------------------------------------------------------- markdown
def render_markdown(d: dict, remediation=None) -> str:
    status = OUTCOME.get(d["outcome"], d["status"])
    md = [f"# AI CI/CD bot analysis - run `{d['run_id']}`", "",
          f"*{d['analyzer']}* - generated {d['generated_at']}", "",
          "## 1. Executive summary", "", d["executive_summary"], "",
          "## 2. Pipeline status", "",
          f"**{d['status']}** ({status}) - failed stage: `{d['failed_stage'] or '-'}` - duration {d['duration_s']:.2f}s  ",
          f"Commit `{d['commit'].get('sha')}` \"{d['commit'].get('message')}\" by {d['commit'].get('author', '-')}", "",
          "## 3. Stage-by-stage status", "", "| # | Stage | Status | Time | Result |", "|---|---|---|---|---|"]
    md += [f"| {s['order']} | {s['name']} | **{s['status']}** | {s['duration_s']:.2f}s | {s['summary']} |"
           for s in d["stages"]]
    md.append("")
    if d["status"] == "SUCCESS":
        md += ["## 4. Pipeline purpose", "", d["pipeline_purpose"], "", "| Stage | What it did | Result |",
               "|---|---|---|"]
        md += [f"| {s['stage']} | {s['what_it_did']} | {s['result']} |" for s in d["stage_explanations"]]
        md += ["", "## 5. Tests executed", "", "| Suite | Total | Passed | Failed | Skipped | Modules |",
               "|---|---|---|---|---|---|"]
        md += [f"| {t['suite']} | {t['total']} | {t['passed']} | {t['failed']} | {t['skipped']} | "
               f"{', '.join(t['modules'])} |" for t in d["tests"]]
        md += ["", "## 6. Artifacts", ""]
        md += [f"- `{a['path']}` v{a['version']}, {a['size_bytes']} bytes, sha256 `{a['sha256']}`" for a in d["artifacts"]]
        md += ["", "## 7. Quality & security checks", "", "| Check | Result |", "|---|---|"]
        md += [f"| {q['check']} | PASS - {q['result']} |" for q in d["quality_checks"]]
        t = d["timing"]
        md += ["", "## 8. Timing", "", f"Total {t['total_s']:.2f}s; slowest stage {t['slowest_stage']} "
               f"({t['slowest_s']:.2f}s).", "", "## 9. Risk, validation & rollback", "",
               f"Risk: **{d['impact']['severity']}** - {d['impact']['customer_impact']}", "", "Validation plan:"]
        md += [f"- {x}" for x in d["validation_plan"]] + ["", "Rollback plan:"] + [f"- {x}" for x in d["rollback_plan"]]
        r = d["release_readiness"]
        md += ["", "## 10. Release readiness", "", f"**{r['verdict']}** (confidence {d['confidence']:.0%})", ""]
        md += [f"- Condition: {x}" for x in r["conditions"]]
    else:
        md += [f"Passed work: {', '.join(d['passed_work'])}  ", f"Failed work: {', '.join(d['failed_work'])}  ",
               f"Not run: {', '.join(d['skipped_work']) or '-'}", "",
               "## 4. Root-cause analysis", "", f"**{d['title']}**", "",
               f"Class `{d['failure_class']}` - playbook `{d['playbook']}` - confidence **{d['confidence']:.0%}**", "",
               d["root_cause"], "", "Confidence signals:"]
        md += [f"- +{f['weight']:.2f} {f['signal']}" for f in d["confidence_factors"]]
        md += ["", "## 5. Supporting evidence", ""]
        for i, e in enumerate(d["evidence"], 1):
            md.append(f"{i}. **{e['finding']}** - `{e['source']}`")
            if e["excerpt"]:
                md += ["", "   ```", *[f"   {l}" for l in e["excerpt"].splitlines()[:8]], "   ```"]
        imp = d["impact"]
        md += ["", "## 6. Impact & risk assessment", "", f"- Severity: **{imp['severity']}** ({imp['area']})",
               f"- Release blocked: {imp['release_blocked']}", f"- Customer impact if shipped: {imp['customer_impact']}",
               f"- Production impact now: {imp['production_impact']}", "- Blast radius:"]
        md += [f"  - {b}" for b in imp["blast_radius"]]
        md += ["", "## 7. Recommended solution & fix guide", "", d["recommendation"], ""]
        md += [f"{i}. {s}" for i, s in enumerate(d["fix_guide"], 1)]
        if d.get("alternatives_considered"):
            md += ["", "Alternatives considered:"] + [f"- {a}" for a in d["alternatives_considered"]]
        md += ["", "## 8. Files proposed for modification", ""]
        for ch in d["proposed_changes"]:
            md += [f"`{ch['path']}` line {ch['line']} - {ch['reason']}", "", "```diff",
                   f"- {ch['old'].strip()}", f"+ {ch['new'].strip()}", "```"]
        if not d["proposed_changes"]:
            md.append("None.")
        if not d["auto_remediable"]:
            md += ["", f"**Escalated:** {d['escalation_reason']}"]
        md += ["", "## 9. Validation plan", ""] + [f"{i}. {s}" for i, s in enumerate(d["validation_plan"], 1)]
        md += ["", "## 10. Rollback plan", ""] + [f"- {s}" for s in d["rollback_plan"]]
    md += ["", "## 11. Final outcome after remediation", ""]
    if remediation:
        md += [f"**{remediation['result_label']}** - approved by {remediation.get('approved_by', '-')} - rerun "
               f"`{remediation.get('rerun_run_id') or '-'}`", "", "| Stage | Before | Targeted | Full rerun |",
               "|---|---|---|---|"]
        md += [f"| {r['name']} | {r['before']} | {r['targeted'] or '-'} | {r['after']} |" for r in remediation["comparison"]]
        md += ["", "Files changed:"] + [f"- `{f['path']}`" for f in remediation["files_changed"]]
    else:
        md.append("Not applicable." if d["status"] == "SUCCESS" else "Remediation not run.")
    if d.get("llm_narrative"):
        md += ["", "## LLM narrative (advisory)", "", d["llm_narrative"]["text"]]
    return "\n".join(md) + "\n"


def write_diagnosis(run_dir: Path, d: dict) -> list:
    out = bot_dir(run_dir)
    remediation = remediation_result(run_dir)
    return [save_json(out / "diagnosis.json", d),
            _write(out / "diagnosis.md", render_markdown(d, remediation))]


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path
