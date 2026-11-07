"""Evidence collection: everything the bot knows about a run comes from here.

Sources: run.json (stage metadata), stage logs, JUnit-derived test summaries,
lint report, the commit diff, and read-only access to the run's workspace.
"""
import ast
import json
import re
from pathlib import Path
from typing import Optional

from pipeline import workspace as ws
from pipeline.models import RunRecord


class RunEvidence:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.record = RunRecord.load(self.run_dir)
        self.workspace = self.run_dir / "workspace"

    # ---- stage metadata & logs
    def stage(self, key):
        return self.record.stage(key)

    def log_lines(self, key) -> list:
        stage = self.stage(key)
        if not stage or not stage.log_file:
            return []
        path = self.run_dir / stage.log_file
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def grep_log(self, key, pattern) -> list:
        regex = re.compile(pattern)
        return [(i + 1, line) for i, line in enumerate(self.log_lines(key)) if regex.search(line)]

    def log_ref(self, key, line_no) -> str:
        return f"{self.stage(key).log_file}:{line_no}"

    # ---- structured reports
    def test_summary(self, label) -> Optional[dict]:
        path = self.run_dir / "test-reports" / f"{label}-summary.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def lint_report(self) -> Optional[dict]:
        path = self.run_dir / "test-reports" / "lint.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def manifest(self) -> Optional[dict]:
        path = self.run_dir / "artifacts" / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    # ---- source control
    def commit_diff(self) -> str:
        path = self.run_dir / "commit.diff"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def changed_lines(self) -> dict:
        return ws.changed_lines(self.commit_diff())

    # ---- repository files (read-only)
    def read(self, rel: str) -> str:
        return (self.workspace / rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        return (self.workspace / rel).exists()

    def sha256(self, rel: str) -> str:
        return ws.sha256_file(self.workspace / rel)

    def app_imports(self, rel: str) -> set:
        """Return app modules (as file paths) imported by a workspace Python file."""
        tree = ast.parse(self.read(rel))
        found = set()
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if name == "app" or name.startswith("app."):
                    path = name.replace(".", "/") + ".py"
                    path = "app/__init__.py" if name == "app" else path
                    if self.exists(path):
                        found.add(path)
        return found

    def transitive_app_imports(self, rel: str) -> set:
        seen, stack = set(), [rel]
        while stack:
            for dep in self.app_imports(stack.pop()):
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        return seen

    def importers_of(self, target: str) -> list:
        """App modules that depend (transitively) on target."""
        result = []
        for path in sorted((self.workspace / "app").glob("*.py")):
            rel = path.relative_to(self.workspace).as_posix()
            if rel != target and target in self.transitive_app_imports(rel):
                result.append(rel)
        return result


def item(source: str, finding: str, excerpt: str = "") -> dict:
    """One piece of supporting evidence."""
    return {"source": source, "finding": finding, "excerpt": excerpt.strip()}


def test_module_path(test_id: str) -> str:
    """'tests.unit.test_pricing::test_x' -> 'tests/unit/test_pricing.py'."""
    return test_id.split("::")[0].replace(".", "/") + ".py"
