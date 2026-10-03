"""Live checks that scripts/create_cluster.sh built the cluster the project
expects: 1 control plane + 3 Ready workers with distinct cep-alias labels,
and that a pod created in an isolated namespace actually gets scheduled."""
import time

import pytest
from kubernetes import client

pytestmark = pytest.mark.live

ALIAS_LABEL = "cep-alias"
EXPECTED_ALIASES = {"node-alpha", "node-beta", "node-gamma"}
CONTROL_PLANE_LABEL = "node-role.kubernetes.io/control-plane"
# Already present on every k3s node (it is the sandbox image), so no pull.
TEST_POD_IMAGE = "rancher/mirrored-pause:3.6"
SCHEDULE_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 0.5


def _is_ready(node: client.V1Node) -> bool:
    return any(
        c.type == "Ready" and c.status == "True" for c in node.status.conditions
    )


def _is_control_plane(node: client.V1Node) -> bool:
    return CONTROL_PLANE_LABEL in (node.metadata.labels or {})


def _wait_for_node_name(api: client.CoreV1Api, namespace: str, pod_name: str) -> str:
    deadline = time.monotonic() + SCHEDULE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        node_name = api.read_namespaced_pod(pod_name, namespace).spec.node_name
        if node_name:
            return node_name
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"pod {pod_name} was not scheduled in time")


def test_cluster_has_one_control_plane_and_three_workers_all_ready(
    core_api: client.CoreV1Api,
) -> None:
    nodes = core_api.list_node().items

    control_planes = [n for n in nodes if _is_control_plane(n)]
    workers = [n for n in nodes if not _is_control_plane(n)]

    assert len(control_planes) == 1
    assert len(workers) == 3
    assert all(_is_ready(n) for n in nodes)


def test_each_worker_has_a_distinct_cep_alias(core_api: client.CoreV1Api) -> None:
    nodes = core_api.list_node().items

    worker_aliases = [
        n.metadata.labels.get(ALIAS_LABEL) for n in nodes if not _is_control_plane(n)
    ]

    assert sorted(worker_aliases) == sorted(EXPECTED_ALIASES)


def test_control_plane_has_no_cep_alias(core_api: client.CoreV1Api) -> None:
    nodes = core_api.list_node().items

    control_plane = next(n for n in nodes if _is_control_plane(n))

    assert ALIAS_LABEL not in control_plane.metadata.labels


def test_pod_in_isolated_namespace_gets_scheduled_onto_a_cluster_node(
    core_api: client.CoreV1Api, test_namespace: str
) -> None:
    pod = client.V1Pod(
        metadata=client.V1ObjectMeta(name="probe"),
        spec=client.V1PodSpec(
            containers=[
                client.V1Container(
                    name="app",
                    image=TEST_POD_IMAGE,
                    resources=client.V1ResourceRequirements(
                        requests={"cpu": "50m", "memory": "32Mi"}
                    ),
                )
            ]
        ),
    )
    core_api.create_namespaced_pod(test_namespace, pod)

    node_name = _wait_for_node_name(core_api, test_namespace, "probe")

    cluster_nodes = {n.metadata.name for n in core_api.list_node().items}
    assert node_name in cluster_nodes


def test_namespace_fixture_gives_an_empty_namespace(
    core_api: client.CoreV1Api, test_namespace: str
) -> None:
    pods = core_api.list_namespaced_pod(test_namespace).items

    assert pods == []
