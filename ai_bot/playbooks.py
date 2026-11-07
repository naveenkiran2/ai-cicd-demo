"""Remediation playbooks: reusable, deterministic failure patterns.

Each playbook inspects RunEvidence and either returns a Finding (root cause,
evidence, impact, a minimal proposed change, validation scope, confidence) or
None. Playbooks never touch files; they only *propose*. Applying a change is
the job of ai_bot.remediate, gated by ai_bot.safety.

Adding a new pattern = adding a class here. That is how fixes become reusable
organisational knowledge instead of tribal knowledge.
"""
import ast
import difflib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from ai_bot.evidence import RunEvidence, item, test_module_path


@dataclass
class ProposedChange:
    path: str
    line: int
    old: str
    new: str
    reason: str
    sha256_before: str


@dataclass
class Finding:
    playbook: str
    failure_class: str
    title: str
    root_cause: str
    evidence: list
    confidence_factors: list          # [(description, weight)]
    impact: dict
    recommendation: str
    fix_steps: list
    changes: list = field(default_factory=list)
    targeted_validation: list = field(default_factory=list)
    alternatives_considered: list = field(default_factory=list)
    auto_remediable: bool = False
    escalation_reason: Optional[str] = None

    @property
    def confidence(self) -> float:
        return round(min(0.97, sum(w for _, w in self.confidence_factors)), 2)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["confidence"] = self.confidence
        data["confidence_factors"] = [{"signal": d, "weight": w} for d, w in self.confidence_factors]
        return data


NUM_PAIR = re.compile(r"assert (?:Decimal\()?'(-?[\d.]+)'\)? == (?:Decimal\()?'(-?[\d.]+)'")


class Playbook:
    id = "base"
    stages: tuple = ()

    def applies(self, ev: RunEvidence) -> bool:
        return ev.record.failed_stage in self.stages

    def match(self, ev: RunEvidence) -> Optional[Finding]:
        raise NotImplementedError


# --------------------------------------------------------------------------- PB-001
class PercentageNotNormalized(Playbook):
    """A 0-100 percentage multiplied directly instead of divided by 100."""
    id = "PB-001 percentage-scale-error"
    stages = ("unit_tests",)

    @staticmethod
    def _scan(source: str):
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                for operand in (node.left, node.right):
                    if isinstance(operand, ast.Name) and operand.id.endswith(("_pct", "_percent")):
                        yield operand
        return

    def match(self, ev):
        tests = ev.test_summary("unit")
        if not tests or not tests["failures"]:
            return None
        failures = tests["failures"]
        test_files = sorted({test_module_path(f["test"]) for f in failures})
        reach = {t: ev.transitive_app_imports(t) for t in test_files if ev.exists(t)}
        changed = ev.changed_lines()
        suspects = sorted(set().union(*reach.values()), key=lambda p: (p not in changed, p))
        for rel in suspects:
            source = ev.read(rel)
            for name_node in self._scan(source):
                return self._finding(ev, rel, source, name_node, failures, test_files, reach, changed, tests)
        return None

    def _finding(self, ev, rel, source, node, failures, test_files, reach, changed, tests):
        lines = source.splitlines()
        line_no, old = node.lineno, lines[node.lineno - 1]
        divisor = "HUNDRED" if re.search(r"^HUNDRED\s*=", source, re.M) else "100"
        new = old[:node.col_offset] + f"({node.id} / {divisor})" + old[node.end_col_offset:]
        func = next((n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)
                     and n.lineno <= line_no <= n.end_lineno), "<module>")
        module = rel[:-3].replace("/", ".")

        ratios = []
        for f in failures:
            m = NUM_PAIR.search(f["message"])
            if m and float(m.group(2)) != 0:
                ratios.append((f["test"].split("::")[-1], float(m.group(1)) / float(m.group(2)),
                               f["message"].splitlines()[0].replace("AssertionError: ", "")))
        exact_100x = [r for r in ratios if abs(r[1] - 100) < 1e-9]
        in_commit = line_no in changed.get(rel, set())
        all_reach = all(rel in deps for deps in reach.values())

        evidence = [item(ev.stage("unit_tests").log_file,
                         f"{len(failures)} of {tests['totals']['tests']} unit tests failed",
                         "\n".join(f"FAILED {f['test']}" for f in failures))]
        for test, _ratio, text in exact_100x:
            evidence.append(item("test-reports/junit-unit.xml", f"{test}: actual value is exactly 100x expected", text))
        negative = [t for t, r, _ in ratios if r < 0]
        if negative:
            evidence.append(item("test-reports/junit-unit.xml", f"order totals go negative in {', '.join(negative)}",
                                 next(x for t, r, x in ratios if r < 0)))
        evidence.append(item(f"workspace:{rel}:{line_no}",
                             f"'{node.id}' (0-100 scale) used as a raw multiplier in {func}()", old))
        if in_commit:
            evidence.append(item("commit.diff", f"line {line_no} of {rel} was changed by the failing commit",
                                 _diff_excerpt(ev.commit_diff(), rel)))
        evidence.append(item("static analysis", f"every failing test module imports {module} (directly or "
                             f"transitively)" if all_reach else f"some failing tests reach {module}",
                             "\n".join(f"{t} -> {', '.join(sorted(d))}" for t, d in reach.items())))

        factors = [("percentage variable multiplied without /100 on the failing code path", 0.55)]
        if in_commit:
            factors.append(("suspect line was modified in the latest commit", 0.2))
        if exact_100x:
            factors.append((f"{len(exact_100x)} assertion(s) off by exactly 100x (scale error signature)", 0.15))
        if all_reach:
            factors.append(("all failing tests share the suspect module", 0.05))

        dependents = ev.importers_of(rel)
        routes = _affected_routes(ev, [rel] + dependents)
        return Finding(
            playbook=self.id, failure_class="unit_test_regression / calculation_defect",
            title=f"Percentage not normalised in {func}() ({rel}:{line_no})",
            root_cause=(f"The latest commit changed {rel}:{line_no} in {func}() to multiply by '{node.id}' "
                        f"directly. '{node.id}' is on a 0-100 scale, so a 10% discount is applied as 1000%. "
                        f"Every failing assertion is consistent with this: observed discounts are exactly 100x "
                        f"the expected value, and totals go negative."),
            evidence=evidence,
            confidence_factors=factors,
            impact={
                "severity": "HIGH",
                "area": "customer-facing pricing",
                "blast_radius": [f"{rel} :: {func}() (defect location)"]
                                + [f"{d} (depends on {module})" for d in dependents]
                                + [f"HTTP API {r}" for r in routes],
                "customer_impact": "Any discounted order would be mispriced (discount 100x too large, negative "
                                   "totals) - direct revenue and trust impact if released.",
                "production_impact": "None. The pipeline stopped at unit tests; no artifact was built or deployed.",
                "release_blocked": True,
            },
            recommendation=f"Restore percentage normalisation: change '{node.id}' to '({node.id} / {divisor})' "
                           f"on {rel}:{line_no}. One-line change, no behaviour change for 0% discounts.",
            fix_steps=[
                f"Open {rel} at line {line_no} ({func}).",
                f"Replace:  {old.strip()}",
                f"With:     {new.strip()}",
                "Re-run lint and the unit test stage (targeted validation).",
                "Re-run the full pipeline to rebuild the artifact and run integration tests.",
                "Add the 100x-ratio assertion pattern to code review guidance for money/percentage code.",
            ],
            changes=[ProposedChange(rel, line_no, old, new, f"normalise 0-100 percentage in {func}()",
                                    ev.sha256(rel))],
            targeted_validation=["lint", "unit_tests"],
            alternatives_considered=[
                "Change tests to match new behaviour - rejected: tests encode the pricing contract; bot may not edit tests.",
                "Revert the whole commit - viable, but broader than the one-line defect.",
            ],
            auto_remediable=True,
        )


# --------------------------------------------------------------------------- PB-002
class HealthProbePathMismatch(Playbook):
    """Deployment manifest probes a path the service does not serve."""
    id = "PB-002 readiness-probe-path-mismatch"
    stages = ("integration",)
    MANIFEST = "config/deploy.json"
    SERVICE = "app/service.py"

    @staticmethod
    def _routes(source: str) -> dict:
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "GET_ROUTES" for t in node.targets):
                return {k.value: node.lineno for k in node.value.keys if isinstance(k, ast.Constant)}
        return {}

    def match(self, ev):
        hits = ev.grep_log("integration", r"readiness probe FAILED: GET (\S+) -> HTTP (\d+)")
        if not hits or not ev.exists(self.MANIFEST):
            return None
        log_no, log_line = hits[-1]
        probe_path, code = re.search(r"GET (\S+) -> HTTP (\d+)", log_line).groups()
        manifest_text = ev.read(self.MANIFEST)
        manifest = json.loads(manifest_text)
        routes = self._routes(ev.read(self.SERVICE))
        if code != "404" or manifest.get("health_path") != probe_path or probe_path in routes:
            return None
        close = difflib.get_close_matches(probe_path, list(routes), n=1, cutoff=0.5)
        if not close:
            return None
        target = close[0]
        lines = manifest_text.splitlines()
        line_no = next(i for i, l in enumerate(lines, 1) if '"health_path"' in l)
        old = lines[line_no - 1]
        new = old.replace(f'"{probe_path}"', f'"{target}"')

        tests = ev.test_summary("integration") or {"failures": [], "cases": [], "totals": {}}
        passed = [c["test"].split("::")[-1] for c in tests["cases"] if c["outcome"] == "passed"]
        contract_ok = "test_health_contract_fields" in passed
        in_commit = line_no in ev.changed_lines().get(self.MANIFEST, set())
        package = ev.stage("package")

        evidence = [
            item(ev.log_ref("integration", log_no), "readiness probe returned 404 for the manifest's health_path",
                 log_line.split("] ", 1)[-1]),
            item(f"workspace:{self.MANIFEST}:{line_no}", f"manifest declares health_path {probe_path}", old),
            item(f"workspace:{self.SERVICE}:{routes[target]}", f"service only serves GET routes: {sorted(routes)}",
                 f"GET_ROUTES keys = {sorted(routes)}"),
        ]
        for f in tests["failures"]:
            evidence.append(item("test-reports/junit-integration.xml", f"{f['test'].split('::')[-1]} failed",
                                 f["message"].splitlines()[0]))
        if contract_ok:
            evidence.append(item("test-reports/junit-integration.xml",
                                 f"service itself is healthy: {len(passed)} integration tests passed, "
                                 f"including the {target} health contract", ", ".join(passed)))
        if in_commit:
            evidence.append(item("commit.diff", f"{self.MANIFEST} line {line_no} changed in the failing commit",
                                 _diff_excerpt(ev.commit_diff(), self.MANIFEST)))
        if package and package.status == "PASS":
            evidence.append(item(package.log_file, "artifact built and checksummed before the failure - reusable",
                                 f"sha256:{package.metrics.get('sha256')}"))

        factors = [("probe path absent from service routes with a close match present", 0.6),
                   ("404 (not 5xx/timeout) - service is up, path is wrong", 0.15)]
        if in_commit:
            factors.append(("manifest line changed by the latest commit", 0.15))
        if contract_ok:
            factors.append((f"health contract passes on {target}", 0.05))
        return Finding(
            playbook=self.id, failure_class="deployment_config_drift / readiness_probe_mismatch",
            title=f"Readiness probe path {probe_path} not served (service exposes {target})",
            root_cause=(f"The latest commit changed health_path in {self.MANIFEST} from {target} to {probe_path}. "
                        f"The service ({self.SERVICE}) only serves {target}, so the platform's readiness probe gets "
                        f"HTTP 404 and the deployment can never become ready. Application code and the artifact "
                        f"are healthy: all other integration and contract tests pass."),
            evidence=evidence,
            confidence_factors=factors,
            impact={
                "severity": "MEDIUM",
                "area": "deployment configuration",
                "blast_radius": [f"{self.MANIFEST} (environment config, not packaged in the artifact)",
                                 "platform readiness probe and rollout gating for order-service",
                                 "no application code affected; artifact sha256 unchanged"],
                "customer_impact": "If promoted, pods would never pass readiness: rollout stalls or restart-loops "
                                   "and capacity drops during deploy.",
                "production_impact": "None. Failure was caught in isolated local staging validation.",
                "release_blocked": True,
            },
            recommendation=f"Point the manifest back at the served route: set health_path to {target} in "
                           f"{self.MANIFEST}. Config-only, one line, no rebuild needed.",
            fix_steps=[
                f"Open {self.MANIFEST} line {line_no}.",
                f"Replace:  {old.strip()}",
                f"With:     {new.strip()}",
                "Re-run ONLY the integration & deployment-validation stage against the existing artifact.",
                "If it passes, re-run the full pipeline for a clean, auditable green build.",
                f"If {probe_path} is a genuine platform convention, raise a separate change to add the route in "
                f"{self.SERVICE} together with contract tests - do not mix that into this fix.",
            ],
            changes=[ProposedChange(self.MANIFEST, line_no, old, new, "align readiness probe with served route",
                                    ev.sha256(self.MANIFEST))],
            targeted_validation=["integration"],
            alternatives_considered=[
                f"Add a {probe_path} route to the service - rejected for auto-fix: code change, needs rebuild and "
                "a contract decision; broader than necessary.",
            ],
            auto_remediable=True,
        )


# --------------------------------------------------------------------------- guidance-only playbooks
class MissingDependency(Playbook):
    id = "PB-003 missing-dependency"
    stages = ("dependencies",)

    def match(self, ev):
        hits = ev.grep_log("dependencies", r"missing dependency: (.+)")
        if not hits:
            return None
        missing = [re.search(r"missing dependency: (.+)", l).group(1) for _, l in hits]
        return Finding(
            playbook=self.id, failure_class="environment / dependency_resolution",
            title=f"Missing or incompatible dependency: {', '.join(missing)}",
            root_cause="The build environment does not provide a declared dependency at a compatible version.",
            evidence=[item(ev.log_ref("dependencies", n), "dependency not resolvable", l) for n, l in hits],
            confidence_factors=[("explicit resolver error in dependency stage log", 0.9)],
            impact={"severity": "LOW", "area": "build environment", "blast_radius": ["this runner only"],
                    "customer_impact": "None.", "production_impact": "None.", "release_blocked": True},
            recommendation="Install the declared requirements on the runner (environment change, not a code change).",
            fix_steps=["pip install -r requirements.txt", "python -m pipeline.run --scenario <name> --install-deps"],
            auto_remediable=False,
            escalation_reason="Runner/environment changes are outside the bot's allow-list (repo files only).",
        )


class LintViolation(Playbook):
    id = "PB-004 lint-violation"
    stages = ("lint",)

    def match(self, ev):
        report = ev.lint_report()
        if not report:
            return None
        errors = [f for f in report["findings"] if f["severity"] == "error"]
        secrets = [f for f in errors if f["check"] == "secrets"]
        return Finding(
            playbook=self.id, failure_class="static_analysis" + (" / secret_exposure" if secrets else ""),
            title=f"{len(errors)} static-analysis error(s)",
            root_cause="Code violates static analysis rules: " + "; ".join(
                f"{f['file']}:{f['line']} {f['message']}" for f in errors[:5]),
            evidence=[item(f"workspace:{f['file']}:{f['line']}", f"[{f['check']}] {f['message']}") for f in errors],
            confidence_factors=[("deterministic linter output", 0.9)],
            impact={"severity": "HIGH" if secrets else "LOW", "area": "code quality",
                    "blast_radius": sorted({f["file"] for f in errors}), "customer_impact": "None directly.",
                    "production_impact": "None.", "release_blocked": True},
            recommendation="Fix the listed findings" + ("; rotate any exposed credential immediately." if secrets else "."),
            fix_steps=[f"{f['file']}:{f['line']} - {f['message']}" for f in errors],
            auto_remediable=False,
            escalation_reason="Lint fixes are guidance-only in this demo" + (
                "; secret findings always require a human (credential rotation)." if secrets else "."),
        )


class GenericTestFailure(Playbook):
    """Fallback: tests failed but no known pattern explains it -> escalate."""
    id = "PB-999 unclassified-failure"
    stages = ("checkout", "dependencies", "lint", "unit_tests", "package", "integration")

    def match(self, ev):
        stage = ev.stage(ev.record.failed_stage)
        label = {"unit_tests": "unit", "integration": "integration"}.get(stage.key)
        tests = ev.test_summary(label) if label else None
        failures = tests["failures"] if tests else []
        return Finding(
            playbook=self.id, failure_class="unclassified",
            title=f"{stage.name} failed - no known remediation pattern",
            root_cause=stage.error or stage.summary,
            evidence=[item(stage.log_file, stage.summary, stage.error or "")]
            + [item("test report", f["test"], f["message"].splitlines()[0] if f["message"] else "") for f in failures],
            confidence_factors=[("failure observed but no playbook matched", 0.3)],
            impact={"severity": "UNKNOWN", "area": stage.name, "blast_radius": ["undetermined"],
                    "customer_impact": "Unknown.", "production_impact": "None; release blocked.",
                    "release_blocked": True},
            recommendation="Escalate to the owning team with the collected evidence bundle.",
            fix_steps=["Review the evidence below", "Reproduce locally", "Consider adding a new playbook"],
            auto_remediable=False,
            escalation_reason="Confidence below threshold - human engineer required.",
        )


PLAYBOOKS = [PercentageNotNormalized(), HealthProbePathMismatch(), MissingDependency(), LintViolation(),
             GenericTestFailure()]


def find_root_cause(ev: RunEvidence) -> Finding:
    for playbook in PLAYBOOKS:
        if playbook.applies(ev):
            finding = playbook.match(ev)
            if finding:
                return finding
    raise RuntimeError("no playbook produced a finding")  # GenericTestFailure always matches


def _diff_excerpt(diff: str, rel: str) -> str:
    out, active = [], False
    for line in diff.splitlines():
        if line.startswith("--- "):
            active = line.endswith(rel)
        if active and (line.startswith(("+", "-")) and not line.startswith(("+++", "---"))):
            out.append(line)
    return "\n".join(out)


def _affected_routes(ev: RunEvidence, modules: list) -> list:
    """HTTP routes whose handlers call functions imported from affected modules."""
    service = "app/service.py"
    if not ev.exists(service) or service not in modules and not set(modules) & ev.app_imports(service):
        return []
    tree = ast.parse(ev.read(service))
    imported = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                and n.module and n.module.replace(".", "/") + ".py" in modules for a in n.names}
    funcs = {n.name: {c.func.id for c in ast.walk(n) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
             for n in tree.body if isinstance(n, ast.FunctionDef)}
    routes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            verb = getattr(node.targets[0], "id", "").split("_")[0]
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(value, ast.Name) and funcs.get(value.id, set()) & imported:
                    routes.append(f"{verb} {key.value}")
    return routes
