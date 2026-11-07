"""Deployment-manifest loading and validation (config/deploy.json)."""
import json
from pathlib import Path

ALLOWED_ENVIRONMENTS = ("dev", "staging")  # production is out of scope for this demo
REQUIRED_KEYS = ("service", "environment", "port", "health_path", "replicas")


class ConfigError(ValueError):
    """Raised when a deployment manifest is invalid."""


def load_deploy_config(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_deploy_config(data)
    return data


def validate_deploy_config(data) -> None:
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise ConfigError(f"missing keys: {', '.join(missing)}")
    if data["environment"] not in ALLOWED_ENVIRONMENTS:
        raise ConfigError(f"environment must be one of {ALLOWED_ENVIRONMENTS}, got {data['environment']!r}")
    if not isinstance(data["port"], int) or not 1024 <= data["port"] <= 65535:
        raise ConfigError(f"port must be an integer in 1024-65535, got {data['port']!r}")
    if not isinstance(data["health_path"], str) or not data["health_path"].startswith("/"):
        raise ConfigError("health_path must be a string starting with '/'")
    if not isinstance(data["replicas"], int) or data["replicas"] < 1:
        raise ConfigError("replicas must be a positive integer")
