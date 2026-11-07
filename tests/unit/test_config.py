import json

import pytest

from app.config import ConfigError, load_deploy_config, validate_deploy_config

VALID = {"service": "order-service", "environment": "staging", "port": 8080, "health_path": "/health", "replicas": 2}


def test_valid_manifest_passes():
    validate_deploy_config(dict(VALID))


@pytest.mark.parametrize("key,value", [("port", 80), ("port", "8080"), ("environment", "production"), ("replicas", 0)])
def test_invalid_values_rejected(key, value):
    with pytest.raises(ConfigError):
        validate_deploy_config({**VALID, key: value})


def test_missing_key_rejected():
    data = dict(VALID)
    del data["health_path"]
    with pytest.raises(ConfigError):
        validate_deploy_config(data)


def test_load_from_file(tmp_path):
    path = tmp_path / "deploy.json"
    path.write_text(json.dumps(VALID))
    assert load_deploy_config(path)["port"] == 8080
