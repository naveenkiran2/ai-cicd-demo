"""Dependency-free static analysis and secret scanning used by the lint stage.

Checks (deterministic, stdlib only):
  syntax        every .py file compiles
  unused-import imported names never referenced (app/ only)
  bare-except   `except:` without an exception type
  no-print      print() calls in application code (use logging)
  line-length   lines longer than MAX_LINE
  whitespace    trailing whitespace / tab indentation
  secrets       hard-coded keys, private keys, password literals (all files)
"""
import ast
import re
from pathlib import Path

MAX_LINE = 120
CHECKS = ["syntax", "unused-import", "bare-except", "no-print", "line-length", "whitespace", "secrets"]
SECRET_PATTERNS = [
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("credential-literal", re.compile(
        r"(?i)\b(password|passwd|secret|api_key|apikey|token)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
]
TEXT_SUFFIXES = {".py", ".json", ".toml", ".txt", ".cfg", ".ini", ".yml", ".yaml", ".md", ".env"}


def _finding(check, path, line, message, severity="error"):
    return {"check": check, "file": path, "line": line, "message": message, "severity": severity}


def _unused_imports(tree, rel):
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported[alias.asname or alias.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    return [_finding("unused-import", rel, line, f"'{name}' imported but unused")
            for name, line in sorted(imported.items(), key=lambda kv: kv[1]) if name not in used]


def lint_python(path: Path, rel: str, is_app: bool) -> list:
    source = path.read_text(encoding="utf-8")
    findings = []
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        return [_finding("syntax", rel, exc.lineno or 0, f"syntax error: {exc.msg}")]
    if is_app and not rel.endswith("__init__.py"):
        findings += _unused_imports(tree, rel)
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append(_finding("bare-except", rel, node.lineno, "bare 'except:' hides errors"))
        if is_app and isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            findings.append(_finding("no-print", rel, node.lineno, "use logging instead of print()"))
    for number, line in enumerate(source.splitlines(), 1):
        if len(line) > MAX_LINE:
            findings.append(_finding("line-length", rel, number, f"line too long ({len(line)} > {MAX_LINE})"))
        if line != line.rstrip():
            findings.append(_finding("whitespace", rel, number, "trailing whitespace", "warning"))
        if line.startswith("\t"):
            findings.append(_finding("whitespace", rel, number, "tab indentation", "warning"))
    return findings


def scan_secrets(path: Path, rel: str) -> list:
    findings = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(_finding("secrets", rel, number, f"possible hard-coded secret ({name})"))
    return findings


def run_lint(workspace: Path) -> dict:
    findings, py_files, scanned = [], 0, 0
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(workspace).as_posix()
        if path.suffix == ".py":
            py_files += 1
            findings += lint_python(path, rel, is_app=rel.startswith("app/"))
        if path.suffix in TEXT_SUFFIXES or path.name.startswith(".env"):
            scanned += 1
            findings += scan_secrets(path, rel)
    errors = [f for f in findings if f["severity"] == "error"]
    return {
        "checks": CHECKS,
        "python_files": py_files,
        "files_secret_scanned": scanned,
        "errors": len(errors),
        "warnings": len(findings) - len(errors),
        "secret_findings": sum(1 for f in findings if f["check"] == "secrets"),
        "findings": findings,
    }
