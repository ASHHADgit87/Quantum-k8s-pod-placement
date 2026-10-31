"""In-memory stand-in for the Kubernetes CoreV1Api, plus builders for the
node/pod objects it returns, so cluster-reading code is tested without a
live cluster."""
import json
from types import SimpleNamespace

from kubernetes import client


def make_node(
    name: str,
    cpu: str,
    memory: str,
    alias: str | None = None,
    ready: bool = True,
    unschedulable: bool = False,
    taint_effect: str | None = None,
) -> client.V1Node:
    labels = {"cep-alias": alias} if alias else {}
    taints = [client.V1Taint(key="test", effect=taint_effect)] if taint_effect else None
    ready_condition = client.V1NodeCondition(type="Ready", status=str(ready))
    return client.V1Node(
        metadata=client.V1ObjectMeta(name=name, labels=labels),
        spec=client.V1NodeSpec(unschedulable=unschedulable, taints=taints),
        status=client.V1NodeStatus(
            allocatable={"cpu": cpu, "memory": memory}, conditions=[ready_condition]
        ),
    )


def make_pod(
    name: str,
    namespace: str,
    node_name: str | None = None,
    cpu: str | None = None,
    memory: str | None = None,
    phase: str = "Running",
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
    scheduler_name: str = "default-scheduler",
) -> client.V1Pod:
    requests = {
        key: value for key, value in (("cpu", cpu), ("memory", memory)) if value
    }
    container = client.V1Container(
        name="app",
        image="test",
        resources=client.V1ResourceRequirements(requests=requests or None),
    )
    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name, namespace=namespace, labels=labels, annotations=annotations
        ),
        spec=client.V1PodSpec(
            containers=[container], node_name=node_name, scheduler_name=scheduler_name
        ),
        status=client.V1PodStatus(phase=phase),
    )


class FakeCoreApi:
    """Answers the handful of CoreV1Api calls the project makes."""

    def __init__(
        self,
        nodes: list[client.V1Node] | None = None,
        pods: list[client.V1Pod] | None = None,
        node_stats: dict[str, dict] | None = None,
    ) -> None:
        self._nodes = nodes or []
        self._pods = pods or []
        self._node_stats = node_stats or {}

    def list_node(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(items=list(self._nodes))

    def list_pod_for_all_namespaces(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(items=list(self._pods))

    def list_namespaced_pod(
        self, namespace: str, **_kwargs: object
    ) -> SimpleNamespace:
        items = [p for p in self._pods if p.metadata.namespace == namespace]
        return SimpleNamespace(items=items)

    def connect_get_node_proxy_with_path(
        self, name: str, path: str, _preload_content: bool = True
    ) -> SimpleNamespace | str:
        if name not in self._node_stats:
            raise ConnectionError(f"kubelet on {name} is not reachable")
        if _preload_content:
            # What the real client does by default: a Python-repr string
            # (single quotes) that is not valid JSON.
            return str(self._node_stats[name])
        return SimpleNamespace(data=json.dumps(self._node_stats[name]).encode())
