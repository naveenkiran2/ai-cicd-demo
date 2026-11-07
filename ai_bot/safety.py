"""Safety policy for self-healing changes. Every check must pass or nothing is written.

Guardrails enforced here:
  * explicit human approval is required before any file is modified
  * only allow-listed paths inside the run's workspace (app/*.py, config/*.json)
  * tests, pipeline code, bot code, CI config and dependency manifests are never edited
  * no deletes, no new files, no symlinks, no path traversal outside the project
  * change-size limits (files and lines) keep repairs narrow
  * file must be byte-identical to what was diagnosed (sha256 precondition)
  * the replaced text must match exactly once
  * patched content must still parse (Python AST / JSON)
  * patched content must not introduce anything that looks like a secret
  * production targets are refused outright
  * diagnosis confidence must meet the auto-fix threshold
"""
import ast
import fnmatch
import json
import os
from pathlib import Path

from ai_bot.diagnose import AUTO_FIX_MIN_CONFIDENCE
from pipeline.lint import SECRET_PATTERNS
from pipeline.workspace import PROJECT_ROOT, sha256_file

ALLOWED_GLOBS = ("app/*.py", "config/*.json")
DENIED_GLOBS = ("tests/*", "pipeline/*", "ai_bot/*", ".github/*", "requirements*.txt", "pyproject.toml", "*.lock")
MAX_FILES = 2
MAX_CHANGED_LINES = 5


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"check": name, "passed": bool(passed), "detail": detail}


def evaluate(diagnosis: dict, workspace: Path, approved: bool) -> list:
    workspace = Path(workspace).resolve()
    changes = diagnosis.get("proposed_changes", [])
    results = [
        _check("human-approval", approved, "explicit --approve given" if approved else "approval missing (dry run)"),
        _check("playbook-auto-remediable", diagnosis.get("auto_remediable", False),
               diagnosis.get("escalation_reason") or f"playbook {diagnosis.get('playbook')} permits auto-fix"),
        _check("confidence-threshold", diagnosis.get("confidence", 0) >= AUTO_FIX_MIN_CONFIDENCE,
               f"{diagnosis.get('confidence', 0):.0%} >= {AUTO_FIX_MIN_CONFIDENCE:.0%}"),
        _check("change-scope", 0 < len(changes) <= MAX_FILES and
               sum(len(c["new"].splitlines()) for c in changes) <= MAX_CHANGED_LINES,
               f"{len(changes)} file(s), limits {MAX_FILES} files / {MAX_CHANGED_LINES} lines"),
        _check("workspace-in-project", PROJECT_ROOT.resolve() in workspace.parents,
               f"workspace {workspace.relative_to(PROJECT_ROOT.resolve()) if PROJECT_ROOT.resolve() in workspace.parents else workspace}"),
        _check("no-production-target", os.environ.get("AI_BOT_TARGET_ENV", "local").lower() != "production",
               f"target environment: {os.environ.get('AI_BOT_TARGET_ENV', 'local')}"),
    ]
    for change in changes:
        results += _file_checks(change, workspace)
    return results


def _file_checks(change: dict, workspace: Path) -> list:
    rel = change["path"]
    target = (workspace / rel)
    resolved = target.resolve()
    inside = workspace in resolved.parents
    allowed = any(fnmatch.fnmatch(rel, g) for g in ALLOWED_GLOBS)
    denied = any(fnmatch.fnmatch(rel, g) for g in DENIED_GLOBS)
    out = [
        _check(f"path-inside-workspace:{rel}", inside and ".." not in Path(rel).parts, str(rel)),
        _check(f"path-allow-listed:{rel}", allowed and not denied,
               f"allowed={ALLOWED_GLOBS}" if allowed and not denied else f"{rel} is not an allow-listed path"),
        _check(f"no-symlink:{rel}", target.exists() and not target.is_symlink(), "regular existing file"),
    ]
    if not (inside and target.exists()):
        return out
    current = target.read_text(encoding="utf-8")
    out.append(_check(f"unchanged-since-diagnosis:{rel}", sha256_file(target) == change["sha256_before"],
                      f"sha256 {change['sha256_before'][:12]}"))
    occurrences = current.count(change["old"])
    out.append(_check(f"exact-single-match:{rel}", occurrences == 1, f"old text found {occurrences}x"))
    patched = current.replace(change["old"], change["new"], 1)
    out.append(_check(f"syntax-valid-after:{rel}", _parses(rel, patched), "patched file parses"))
    leaked = [n for n, p in SECRET_PATTERNS if p.search(change["new"])]
    out.append(_check(f"no-secret-introduced:{rel}", not leaked, ", ".join(leaked) or "clean"))
    if rel.endswith(".json") and _parses(rel, patched):
        env = json.loads(patched).get("environment")
        out.append(_check(f"manifest-not-production:{rel}", env != "production", f"environment={env}"))
    return out


def _parses(rel: str, text: str) -> bool:
    try:
        if rel.endswith(".py"):
            ast.parse(text)
        elif rel.endswith(".json"):
            json.loads(text)
        return True
    except (SyntaxError, ValueError):
        return False


def all_passed(results: list) -> bool:
    return all(r["passed"] for r in results)
