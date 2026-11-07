"""The seven pipeline stages.

Every stage receives a RunContext and a StageLog, writes a real log file, and
returns a StageOutcome. Tests run in subprocesses with JUnit XML output so the
AI bot can read the same structured evidence a CI server would produce.
"""
import gzip
import io
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Callable, Optional

from pipeline import lint, workspace as ws
from pipeline.models import Status

PIPELINE_PURPOSE = (
    "Continuously verify, package and deployment-validate the order-service so that every "
    "commit produces a tested, versioned, traceable artifact that is safe to promote."
)


@dataclass
class RunContext:
    run_id: str
    run_dir: Path
    workspace: Path
    scenario: dict
    options: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)

    @property
    def logs_dir(self) -> Path:
        return self.run_dir / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.run_dir / "test-reports"

    @property
    def artifacts_dir(self) -> Path:
        return self.run_dir / "artifacts"

    def rel(self, path: Path) -> str:
        return Path(path).relative_to(self.run_dir).as_posix()


@dataclass
class StageOutcome:
    status: Status
    summary: str
    metrics: dict = field(default_factory=dict)
    error: Optional[str] = None
    reports: list = field(default_factory=list)


class StageLog:
    """Timestamped, append-only stage log file."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("w", encoding="utf-8")

    def _write(self, level: str, message: str) -> None:
        for line in str(message).splitlines() or [""]:
            self._fh.write(f"{ws.utcnow()} [{level}] {line}\n")
        self._fh.flush()

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def warn(self, message: str) -> None:
        self._write("WARN", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)

    def output(self, text: str) -> None:
        for line in text.rstrip("\n").splitlines():
            self._fh.write(f"    | {line}\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def _env(extra: Optional[dict] = None, pythonpath: Optional[Path] = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().endswith(("_TOKEN", "_SECRET", "_API_KEY"))}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
    if pythonpath:
        env["PYTHONPATH"] = str(pythonpath)
    env.update(extra or {})
    return env


def parse_junit(path: Path) -> dict:
    """Summarise a JUnit XML file: counts plus every failing test case."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time_s": 0.0}
    failures, cases = [], []
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            totals[key] += int(suite.get(key, 0))
        totals["time_s"] += float(suite.get("time", 0))
        for case in suite.iter("testcase"):
            name = f"{case.get('classname')}::{case.get('name')}"
            problem = case.find("failure")
            if problem is None:
                problem = case.find("error")
            outcome = "failed" if problem is not None else ("skipped" if case.find("skipped") is not None else "passed")
            cases.append({"test": name, "outcome": outcome, "time_s": float(case.get("time", 0))})
            if problem is not None:
                failures.append({"test": name, "file": case.get("file"), "kind": problem.tag,
                                 "message": problem.get("message", ""), "details": (problem.text or "")[:4000]})
    totals["failed"] = totals["failures"] + totals["errors"]
    totals["passed"] = totals["tests"] - totals["failed"] - totals["skipped"]
    totals["time_s"] = round(totals["time_s"], 3)
    return {"totals": totals, "failures": failures, "cases": cases}


def run_pytest(ctx: RunContext, log: StageLog, label: str, targets: list, extra_env=None) -> StageOutcome:
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    junit = ctx.reports_dir / f"junit-{label}.xml"
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", "-rfE", "-p", "no:cacheprovider", f"--junitxml={junit}"]
    log.info("$ " + " ".join(["python", "-m", "pytest", *targets, "-q", "-rfE", f"--junitxml={ctx.rel(junit)}"]))
    proc = subprocess.run(cmd, cwd=ctx.workspace, capture_output=True, text=True, timeout=300,
                          env=_env(extra_env, pythonpath=ctx.workspace))
    log.output(proc.stdout + proc.stderr)
    log.info(f"pytest exit code: {proc.returncode}")
    if not junit.exists():
        return StageOutcome(Status.FAIL, "test runner produced no report", error=proc.stderr[-500:] or "no junit xml")
    report = parse_junit(junit)
    (ctx.reports_dir / f"{label}-summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    t = report["totals"]
    metrics = {"tests": t["tests"], "passed": t["passed"], "failed": t["failed"], "skipped": t["skipped"],
               "test_time_s": t["time_s"], "suites": sorted({c["test"].split("::")[0] for c in report["cases"]})}
    reports = [ctx.rel(junit), ctx.rel(ctx.reports_dir / f"{label}-summary.json")]
    if proc.returncode == 0 and t["failed"] == 0:
        return StageOutcome(Status.PASS, f"{t['passed']} passed", metrics, reports=reports)
    names = ", ".join(f["test"].split("::")[-1] for f in report["failures"][:3])
    return StageOutcome(Status.FAIL, f"{t['failed']} failed, {t['passed']} passed", metrics,
                        error=f"failing tests: {names}", reports=reports)


# --------------------------------------------------------------------------- stage 1
def stage_checkout(ctx: RunContext, log: StageLog) -> StageOutcome:
    source = ctx.options.get("source_workspace")
    if source:
        log.info(f"checkout: snapshot of patched workspace {Path(source).relative_to(ws.PROJECT_ROOT).as_posix()}")
        ws.copy_snapshot(Path(source), ctx.workspace)
        diff = ctx.options.get("commit_diff", "")
    else:
        log.info(f"checkout: repository baseline -> {ctx.rel(ctx.workspace)}")
        ws.copy_snapshot(ws.PROJECT_ROOT, ctx.workspace)
        changes = ctx.scenario.get("changes", [])
        diff = ws.apply_scenario_changes(ctx.workspace, changes)
        for change in changes:
            log.info(f"applied commit change to {change['file']}")
    (ctx.run_dir / "commit.diff").write_text(diff, encoding="utf-8")
    sha = ws.tree_digest(ctx.workspace)
    ctx.state["tree_sha"] = sha
    log.info(f"source tree digest: {sha}")
    if diff:
        log.info("commit diff:")
        log.output(diff)

    problems = []
    if sys.version_info < (3, 10):
        problems.append(f"python >= 3.10 required, found {platform.python_version()}")
    for required in ("app/__init__.py", "tests/unit", "tests/integration", "config/deploy.json", "requirements.txt"):
        if not (ctx.workspace / required).exists():
            problems.append(f"missing required path: {required}")
    log.info(f"python {platform.python_version()} on {platform.system()} {platform.machine()}")
    for problem in problems:
        log.error(problem)
    files = sum(1 for p in ctx.workspace.rglob("*") if p.is_file())
    metrics = {"tree_sha": sha, "files": files, "python": platform.python_version()}
    if problems:
        return StageOutcome(Status.FAIL, problems[0], metrics, error="; ".join(problems))
    return StageOutcome(Status.PASS, f"tree {sha}, {files} files, python {platform.python_version()}", metrics)


# --------------------------------------------------------------------------- stage 2
REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*([<>=!~,.\d\s]*)")


def _version_tuple(text: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3])


def _satisfies(version: str, spec: str) -> bool:
    v = _version_tuple(version)
    for clause in filter(None, (c.strip() for c in spec.split(","))):
        op, target = re.match(r"(>=|<=|==|<|>|~=|!=)?\s*(.*)", clause).groups()
        t = _version_tuple(target)
        checks = {">=": v >= t, "<=": v <= t, "==": v[:len(t)] == t, "<": v < t, ">": v > t,
                  "!=": v[:len(t)] != t, "~=": v >= t and v[:len(t) - 1] == t[:-1], None: True}
        if not checks[op]:
            return False
    return True


def stage_dependencies(ctx: RunContext, log: StageLog) -> StageOutcome:
    req_file = ctx.workspace / "requirements.txt"
    requirements = []
    for raw in req_file.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            name, spec = REQ_RE.match(line).groups()
            requirements.append((name, spec.strip()))
    log.info(f"declared requirements: {', '.join(n + s for n, s in requirements) or 'none'}")
    missing, resolved = [], {}
    for name, spec in requirements:
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(f"{name}{spec} (not installed)")
            continue
        if not _satisfies(version, spec):
            missing.append(f"{name}{spec} (found {version})")
            continue
        resolved[name] = version
        log.info(f"resolved {name}=={version} satisfies '{spec or 'any'}'")
    unpinned = [n for n, s in requirements if "<" not in s and "==" not in s]
    for name in unpinned:
        log.warn(f"dependency '{name}' has no upper bound (supply-chain drift risk)")
    if missing and ctx.options.get("install_deps"):
        log.info("installing missing dependencies: pip install -r requirements.txt")
        proc = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                              capture_output=True, text=True, timeout=600)
        log.output(proc.stdout[-3000:] + proc.stderr[-2000:])
        if proc.returncode == 0 and not ctx.state.get("dep_retry"):
            ctx.state["dep_retry"] = True
            return stage_dependencies(ctx, log)
    metrics = {"declared": len(requirements), "resolved": resolved, "missing": missing, "unbounded": unpinned}
    if missing:
        for item in missing:
            log.error(f"missing dependency: {item}")
        return StageOutcome(Status.FAIL, f"missing: {', '.join(missing)}", metrics,
                            error="dependency resolution failed; run: pip install -r requirements.txt")
    stdlib_note = "app runtime uses stdlib only"
    log.info(stdlib_note)
    return StageOutcome(Status.PASS, f"{len(resolved)}/{len(requirements)} resolved; {stdlib_note}", metrics)


# --------------------------------------------------------------------------- stage 3
def stage_lint(ctx: RunContext, log: StageLog) -> StageOutcome:
    log.info(f"static checks: {', '.join(lint.CHECKS)} (max line {lint.MAX_LINE})")
    result = lint.run_lint(ctx.workspace)
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    report = ctx.reports_dir / "lint.json"
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for f in result["findings"]:
        writer = log.error if f["severity"] == "error" else log.warn
        writer(f"{f['file']}:{f['line']}: [{f['check']}] {f['message']}")
    log.info(f"{result['python_files']} python files linted, {result['files_secret_scanned']} files secret-scanned")
    log.info(f"errors={result['errors']} warnings={result['warnings']} secrets={result['secret_findings']}")
    metrics = {k: result[k] for k in ("python_files", "files_secret_scanned", "errors", "warnings", "secret_findings")}
    metrics["checks"] = result["checks"]
    summary = f"{result['python_files']} files, {result['errors']} errors, {result['secret_findings']} secrets"
    if result["errors"]:
        first = next(f for f in result["findings"] if f["severity"] == "error")
        return StageOutcome(Status.FAIL, summary, metrics, reports=[ctx.rel(report)],
                            error=f"{first['file']}:{first['line']} {first['message']}")
    return StageOutcome(Status.PASS, summary, metrics, reports=[ctx.rel(report)])


# --------------------------------------------------------------------------- stage 4
def stage_unit_tests(ctx: RunContext, log: StageLog) -> StageOutcome:
    targets = ctx.options.get("unit_targets") or ["tests/unit"]
    return run_pytest(ctx, log, "unit", targets)


# --------------------------------------------------------------------------- stage 5
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def stage_package(ctx: RunContext, log: StageLog) -> StageOutcome:
    pyproject = (ctx.workspace / "pyproject.toml").read_text(encoding="utf-8")
    name = re.search(r'^name\s*=\s*"([^"]+)"', pyproject, re.M).group(1)
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M).group(1)
    code_version = re.search(r'__version__\s*=\s*"([^"]+)"',
                             (ctx.workspace / "app/__init__.py").read_text(encoding="utf-8")).group(1)
    log.info(f"package metadata: name={name} version={version} (app.__version__={code_version})")
    if not SEMVER.match(version) or version != code_version:
        msg = f"version metadata invalid or inconsistent: pyproject={version} app={code_version}"
        log.error(msg)
        return StageOutcome(Status.FAIL, msg, error=msg)

    files = sorted(p for p in (ctx.workspace / "app").rglob("*.py") if "__pycache__" not in p.parts)
    ctx.artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact = ctx.artifacts_dir / f"{name}-{version}.tar.gz"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:  # deterministic: fixed mtime/owner, sorted entries
        for path in files:
            data = path.read_bytes()
            info = tarfile.TarInfo(path.relative_to(ctx.workspace).as_posix())
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    with gzip.GzipFile(artifact, mode="wb", mtime=0) as gz:
        gz.write(buffer.getvalue())
    artifact_sha = ws.sha256_file(artifact)
    manifest = {
        "name": name, "version": version, "artifact": artifact.name, "sha256": artifact_sha,
        "size_bytes": artifact.stat().st_size, "source_tree": ctx.state.get("tree_sha"),
        "files": [{"path": p.relative_to(ctx.workspace).as_posix(), "sha256": ws.sha256_file(p)} for p in files],
    }
    manifest_path = ctx.artifacts_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    ctx.state["artifact"] = artifact
    for entry in manifest["files"]:
        log.info(f"  + {entry['path']}  sha256:{entry['sha256'][:12]}")
    log.info(f"built {ctx.rel(artifact)} ({manifest['size_bytes']} bytes) sha256:{artifact_sha}")
    metrics = {"artifact": ctx.rel(artifact), "sha256": artifact_sha, "size_bytes": manifest["size_bytes"],
               "files": len(files), "version": version}
    return StageOutcome(Status.PASS, f"{artifact.name} sha256:{artifact_sha[:12]}", metrics,
                        reports=[ctx.rel(manifest_path)])


# --------------------------------------------------------------------------- stage 6
def validate_manifest_policy(manifest: dict) -> list:
    """Platform-side policy for deployment manifests (independent of app code)."""
    problems = []
    for key in ("service", "environment", "port", "health_path", "replicas"):
        if key not in manifest:
            problems.append(f"missing key '{key}'")
    if manifest.get("environment") not in ("dev", "staging"):
        problems.append("environment must be dev or staging (production deploys are out of scope)")
    port = manifest.get("port")
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        problems.append(f"port must be an integer in 1024-65535, got {port!r}")
    if not str(manifest.get("health_path", "")).startswith("/"):
        problems.append("health_path must start with '/'")
    return problems


def _http_get(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, OSError):
        return 0


def stage_integration(ctx: RunContext, log: StageLog) -> StageOutcome:
    artifact = ctx.state.get("artifact") or ctx.options.get("reuse_artifact")
    if not artifact or not Path(artifact).exists():
        return StageOutcome(Status.FAIL, "no artifact available to deploy", error="package stage output missing")
    artifact = Path(artifact)
    log.info(f"artifact under test: {artifact.name} sha256:{ws.sha256_file(artifact)}")
    manifest_path = ctx.workspace / "config" / "deploy.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    log.info(f"deployment manifest config/deploy.json: {json.dumps(manifest, sort_keys=True)}")
    problems = validate_manifest_policy(manifest)
    if problems:
        for p in problems:
            log.error(f"manifest policy violation: {p}")
        return StageOutcome(Status.FAIL, "manifest policy violation", error="; ".join(problems))
    log.info(f"manifest policy: OK (environment={manifest['environment']}, port={manifest['port']})")

    staging = ctx.run_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    with tarfile.open(artifact, "r:gz") as tar:
        for member in tar.getmembers():  # refuse path traversal
            if member.name.startswith(("/", "..")) or ".." in Path(member.name).parts:
                raise RuntimeError(f"unsafe path in artifact: {member.name}")
        try:
            tar.extractall(staging, filter="data")
        except TypeError:  # Python < 3.12 without extraction filters
            tar.extractall(staging)
    log.info(f"deployed artifact to isolated local staging dir {ctx.rel(staging)} (ephemeral port, 127.0.0.1 only)")

    service_log = ctx.logs_dir / "service.log"
    proc = subprocess.Popen([sys.executable, "-m", "app.service", "--host", "127.0.0.1", "--port", "0"],
                            cwd=staging, stdout=subprocess.PIPE, stderr=service_log.open("w", encoding="utf-8"),
                            text=True, env=_env(pythonpath=staging))
    try:
        port_box = {}
        reader = threading.Thread(target=lambda: port_box.setdefault("line", proc.stdout.readline()), daemon=True)
        reader.start()
        reader.join(10)
        match = re.search(r"READY port=(\d+)", port_box.get("line", ""))
        if not match:
            log.error("service did not report READY within 10s")
            return StageOutcome(Status.FAIL, "service failed to start", error="no READY line from service")
        url = f"http://127.0.0.1:{match.group(1)}"
        log.info(f"service started pid={proc.pid} url={url}")

        probe_path = manifest["health_path"]
        deadline = time.time() + float(manifest.get("readiness_timeout_seconds", 5))
        attempt, code = 0, 0
        while True:
            attempt += 1
            code = _http_get(url + probe_path)
            log.info(f"readiness probe attempt {attempt}: GET {probe_path} -> HTTP {code}")
            if code == 200 or time.time() > deadline or code == 404:
                break
            time.sleep(0.5)
        probe_ok = code == 200
        (log.info if probe_ok else log.error)(
            f"readiness probe {'PASSED' if probe_ok else 'FAILED'}: GET {probe_path} -> HTTP {code}")

        outcome = run_pytest(ctx, log, "integration", ["tests/integration"],
                             {"SERVICE_URL": url, "DEPLOY_CONFIG": str(manifest_path)})
        outcome.metrics.update({"readiness_probe": {"path": probe_path, "http_status": code, "passed": probe_ok},
                                "environment": manifest["environment"]})
        outcome.reports.append(ctx.rel(service_log))
        if not probe_ok and outcome.status == Status.PASS:
            outcome.status, outcome.error = Status.FAIL, f"readiness probe GET {probe_path} returned {code}"
        if not probe_ok:
            outcome.summary = f"probe {probe_path} -> {code}; " + outcome.summary
        return outcome
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.info("service stopped; staging environment torn down")


# --------------------------------------------------------------------------- stage 7
def stage_publish(ctx: RunContext, log: StageLog) -> StageOutcome:
    from pipeline import reporting  # local import avoids a cycle
    paths = reporting.publish(ctx)
    for p in paths:
        log.info(f"published {ctx.rel(p)}")
    return StageOutcome(Status.PASS, f"{len(paths)} reports published", {"published": [ctx.rel(p) for p in paths]})


@dataclass(frozen=True)
class StageDef:
    key: str
    name: str
    func: Callable
    purpose: str
    always_run: bool = False


STAGES = [
    StageDef("checkout", "Checkout & environment validation", stage_checkout,
             "snapshot the commit and verify interpreter + repository layout"),
    StageDef("dependencies", "Dependency installation", stage_dependencies,
             "resolve declared dependencies against version constraints"),
    StageDef("lint", "Lint, static & secret checks", stage_lint,
             "static analysis, style rules and hard-coded secret scan"),
    StageDef("unit_tests", "Unit tests", stage_unit_tests, "verify domain logic in isolation"),
    StageDef("package", "Build & package artifact", stage_package,
             "validate version metadata and build a reproducible, checksummed artifact"),
    StageDef("integration", "Integration & deployment validation", stage_integration,
             "deploy the artifact to an isolated local staging process, probe readiness, run API/contract tests"),
    StageDef("publish", "Publish pipeline report", stage_publish,
             "write run metadata and the human-readable summary", always_run=True),
]
STAGE_BY_KEY = {s.key: s for s in STAGES}
