"""cluster_metrics against the real k3d cluster, in a throwaway namespace."""
import json
import time

import pytest
from kubernetes import client

from src import cluster_metrics, workload

pytestmark = pytest.mark.live

TEST_POD_IMAGE = "rancher/mirrored-pause:3.6"
SCHEDULE_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 0.5


def _wait_until_scheduled(api: client.CoreV1Api, namespace: str, pod_name: str) -> str:
    deadline = time.monotonic() + SCHEDULE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        node_name = api.read_namespaced_pod(pod_name, namespace).spec.node_name
        if node_name:
            return node_name
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"pod {pod_name} was not scheduled in time")


def _workload_pod(name: str, cpu: str, memory: str, traffic: dict[str, int]) -> client.V1Pod:
    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name,
            labels={workload.WORKLOAD_LABEL_KEY: workload.WORKLOAD_LABEL_VALUE},
            annotations={workload.TRAFFIC_ANNOTATION: json.dumps(traffic)},
        ),
        spec=client.V1PodSpec(
            containers=[
                client.V1Container(
                    name="app",
                    image=TEST_POD_IMAGE,
                    resources=client.V1ResourceRequirements(
                        requests={"cpu": cpu, "memory": memory}
                    ),
                )
            ]
        ),
    )


def test_live_node_budgets_cover_the_three_aliased_workers(
    core_api: client.CoreV1Api,
) -> None:
    budgets = cluster_metrics.read_node_budgets(core_api)

    assert [b.alias for b in budgets] == ["node-alpha", "node-beta", "node-gamma"]
    for budget in budgets:
        assert 0 < budget.free_cpu_m <= budget.allocatable_cpu_m
        assert 0 < budget.free_memory_bytes <= budget.allocatable_memory_bytes


def test_live_workload_pod_is_read_back_with_requests_and_traffic(
    core_api: client.CoreV1Api, test_namespace: str
) -> None:
    traffic = {"cache": 40, "database": 30}
    core_api.create_namespaced_pod(
        test_namespace, _workload_pod("catalog", "250m", "64Mi", traffic)
    )
    node_name = _wait_until_scheduled(core_api, test_namespace, "catalog")

    pods = cluster_metrics.read_workload_pods(core_api, test_namespace)

    assert len(pods) == 1
    assert pods[0].name == "catalog"
    assert pods[0].cpu_m == 250
    assert pods[0].memory_bytes == 64 * 1024**2
    assert pods[0].node_name == node_name
    assert dict(pods[0].traffic_mbps) == traffic


def test_live_pod_outside_the_workload_namespace_reduces_its_node_budget(
    core_api: client.CoreV1Api, test_namespace: str
) -> None:
    before = {b.name: b for b in cluster_metrics.read_node_budgets(core_api)}
    pod = _workload_pod("occupier", "500m", "128Mi", {})
    pod.spec.node_name = next(iter(before))  # pin it to a known worker
    core_api.create_namespaced_pod(test_namespace, pod)

    after = {b.name: b for b in cluster_metrics.read_node_budgets(core_api)}

    target = pod.spec.node_name
    assert after[target].used_cpu_m == before[target].used_cpu_m + 500
    assert after[target].used_memory_bytes == before[target].used_memory_bytes + 128 * 1024**2


def test_live_network_counters_are_read_for_every_worker(
    core_api: client.CoreV1Api,
) -> None:
    node_names = [b.name for b in cluster_metrics.read_node_budgets(core_api)]

    counters = cluster_metrics.read_network_counters(core_api, node_names)

    assert [c.node_name for c in counters] == node_names
    assert all(c.rx_bytes > 0 and c.tx_bytes > 0 for c in counters)
