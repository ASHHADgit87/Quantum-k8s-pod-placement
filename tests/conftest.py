"""Shared pytest fixtures.

Live-cluster tests are isolated: each one gets a throwaway namespace that is
deleted afterwards (pass or fail), so they never touch the project's real
quantum-sched-test namespace. When the k3d cluster is not running they are
skipped, so `python -m pytest -q` gives the same result on any machine.
"""
import time
import uuid
from collections.abc import Iterator

import pytest
from kubernetes import client, config
from kubernetes.client.rest import ApiException

CLUSTER_CONTEXT = "k3d-quantum-cluster"
TEST_NAMESPACE_PREFIX = "cep-test-"
API_TIMEOUT_SECONDS = 5
NAMESPACE_DELETE_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.5


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: needs the running k3d cluster (skipped when it is down)"
    )


@pytest.fixture(scope="session")
def core_api() -> client.CoreV1Api:
    """CoreV1Api bound to the k3d cluster — never kubectl's current context."""
    try:
        config.load_kube_config(context=CLUSTER_CONTEXT)
        api = client.CoreV1Api()
        api.list_node(_request_timeout=API_TIMEOUT_SECONDS)
    except Exception as exc:  # no kubeconfig, no such context, cluster stopped
        pytest.skip(f"k3d cluster {CLUSTER_CONTEXT} is not reachable: {exc}")
    return api


def _wait_until_namespace_gone(api: client.CoreV1Api, name: str) -> None:
    deadline = time.monotonic() + NAMESPACE_DELETE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            api.read_namespace(name)
        except ApiException as exc:
            if exc.status == 404:
                return
            raise
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"namespace {name} was not deleted in time")


@pytest.fixture
def test_namespace(core_api: client.CoreV1Api) -> Iterator[str]:
    """A fresh namespace for one test, removed with everything in it afterwards."""
    name = f"{TEST_NAMESPACE_PREFIX}{uuid.uuid4().hex[:8]}"
    core_api.create_namespace(
        client.V1Namespace(metadata=client.V1ObjectMeta(name=name))
    )
    try:
        yield name
    finally:
        core_api.delete_namespace(name, grace_period_seconds=0)
        _wait_until_namespace_gone(core_api, name)
