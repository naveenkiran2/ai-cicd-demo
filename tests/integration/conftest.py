"""Integration tests run against a live service started by the pipeline.

The pipeline exports SERVICE_URL (the running artifact) and DEPLOY_CONFIG
(the deployment manifest under test). Without them the suite is skipped.
"""
import json
import os
import urllib.error
import urllib.request

import pytest


@pytest.fixture(scope="session")
def service_url():
    url = os.environ.get("SERVICE_URL")
    if not url:
        pytest.skip("SERVICE_URL not set - integration tests run inside the pipeline")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def deploy_config():
    path = os.environ.get("DEPLOY_CONFIG")
    if not path:
        pytest.skip("DEPLOY_CONFIG not set")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def http(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


@pytest.fixture
def call():
    return http
