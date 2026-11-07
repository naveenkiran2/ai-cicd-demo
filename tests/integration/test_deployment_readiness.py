"""Deployment validation: the manifest must describe a service the platform can probe."""


def test_manifest_targets_this_service(deploy_config):
    assert deploy_config["service"] == "order-service"


def test_readiness_probe_path_is_served(service_url, deploy_config, call):
    path = deploy_config["health_path"]
    status, _ = call("GET", f"{service_url}{path}")
    assert status == 200, f"readiness probe GET {path} returned HTTP {status}"
