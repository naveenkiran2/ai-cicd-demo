"""Run directories, scenario loading and source-snapshot ("checkout") handling.

Each run gets its own directory under artifacts/runs/<run-id>/ containing a
`workspace/` snapshot of the repository. Scenarios simulate a developer commit
by applying a small, declared change on top of the clean baseline. The AI bot
only ever edits files inside a run's workspace, never the baseline sources.
"""
import difflib
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = PROJECT_ROOT / "artifacts" / "runs"
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
SNAPSHOT_ITEMS = ("app", "config", "tests", "pyproject.toml", "requirements.txt")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
SCENARIOS = ("success", "failure", "partial")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_run_id(scenario: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{scenario}"
    run_id, n = base, 2
    while (RUNS_DIR / run_id).exists():
        run_id, n = f"{base}-{n}", n + 1
    return run_id


def rerun_id(parent_id: str) -> str:
    n = 1
    while (RUNS_DIR / f"{parent_id}-rerun{n}").exists():
        n += 1
    return f"{parent_id}-rerun{n}"


def resolve_run_dir(run_id: str) -> Path:
    """Accept a run id, 'latest', or 'latest-<scenario>'."""
    if run_id.startswith("latest"):
        scenario = run_id.partition("-")[2] or None
        candidates = []
        for path in RUNS_DIR.glob("*/run.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("parent_run_id"):
                continue  # reruns are reachable from their parent run
            if scenario and data.get("scenario") != scenario:
                continue
            candidates.append((data.get("created_at", ""), path.parent))
        if not candidates:
            raise FileNotFoundError(f"no runs found for {run_id!r} under {RUNS_DIR}")
        return max(candidates)[1]
    path = RUNS_DIR / run_id
    if not (path / "run.json").exists():
        raise FileNotFoundError(f"run {run_id!r} not found under {RUNS_DIR}")
    return path


def load_scenario(name: str) -> dict:
    path = SCENARIOS_DIR / name / "scenario.json"
    if not path.exists():
        raise FileNotFoundError(f"unknown scenario {name!r}; expected one of {SCENARIOS}")
    return json.loads(path.read_text(encoding="utf-8"))


def copy_snapshot(src_root: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in SNAPSHOT_ITEMS:
        src = src_root / item
        if src.is_dir():
            shutil.copytree(src, dest / item, ignore=IGNORE)
        elif src.is_file():
            shutil.copy2(src, dest / item)


def apply_scenario_changes(workspace: Path, changes: list) -> str:
    """Apply a scenario's simulated commit; return the unified diff."""
    diffs = []
    for change in changes:
        target = workspace / change["file"]
        before = target.read_text(encoding="utf-8")
        if before.count(change["find"]) != 1:
            raise RuntimeError(f"scenario change for {change['file']} did not match exactly once")
        after = before.replace(change["find"], change["replace"])
        target.write_text(after, encoding="utf-8")
        diffs.append(unified_diff(change["file"], before, after))
    return "".join(diffs)


def unified_diff(rel_path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}"))


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:12]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def changed_lines(diff_text: str) -> dict:
    """Map file -> set of line numbers (new side) added/changed by a unified diff."""
    result, current, new_line = {}, None, 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            result.setdefault(current, set())
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            new_line = int(match.group(1)) if match else 0
        elif current and line.startswith("+") and not line.startswith("+++"):
            result[current].add(new_line)
            new_line += 1
        elif current and not line.startswith("-"):
            new_line += 1
    return result
