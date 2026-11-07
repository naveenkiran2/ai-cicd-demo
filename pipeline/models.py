"""Structured records produced by every pipeline run (serialised to run.json)."""
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


@dataclass
class StageResult:
    key: str
    name: str
    order: int
    status: str = Status.SKIPPED.value
    summary: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_s: float = 0.0
    log_file: Optional[str] = None
    reports: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class RunRecord:
    run_id: str
    scenario: str
    created_at: str
    pipeline: str = "order-service-ci"
    status: str = "RUNNING"          # SUCCESS | FAILED
    outcome: str = "running"         # success | failure | partial_success
    failed_stage: Optional[str] = None
    trigger: str = "manual"
    parent_run_id: Optional[str] = None
    commit: dict = field(default_factory=dict)
    environment: dict = field(default_factory=dict)
    stages: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    duration_s: float = 0.0
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, run_dir: Path) -> Path:
        path = Path(run_dir) / "run.json"
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, run_dir: Path) -> "RunRecord":
        data = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
        data["stages"] = [StageResult(**s) for s in data.get("stages", [])]
        return cls(**data)

    def stage(self, key: str) -> Optional[StageResult]:
        for s in self.stages:
            if (s.key if isinstance(s, StageResult) else s["key"]) == key:
                return s
        return None
