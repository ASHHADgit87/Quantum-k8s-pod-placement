"""Live cluster state reader.

Reads, through the Kubernetes Python client:
- each worker node's allocatable capacity, minus what other pods on that node
  already request, so the scheduler never over-commits;
- the workload pods' actual requests and their simulated-traffic annotation;
- best-effort per-node kubelet network counters (rx/tx bytes).

Units everywhere: CPU in millicores, memory in bytes.

    python -m src.cluster_metrics
"""
import argparse
import json
import logging
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType

from kubernetes import client, config

from src.workload import (
    NAMESPACE,
    TRAFFIC_ANNOTATION,
    WORKLOAD_LABEL_KEY,
    WORKLOAD_LABEL_VALUE,
)

logger = logging.getLogger(__name__)

CLUSTER_CONTEXT = "k3d-quantum-cluster"
ALIAS_LABEL = "cep-alias"
KUBELET_STATS_PATH = "stats/summary"
FINISHED_PHASES = frozenset({"Succeeded", "Failed"})
# Taint effects that stop kube-scheduler from placing an ordinary pod on a node.
BLOCKING_TAINT_EFFECTS = frozenset({"NoSchedule", "NoExecute"})
MEBIBYTE = 1024**2

MILLICORES_PER_CORE = 1000
# The numeric part of a quantity: plain ASCII decimal, optional exponent.
_NUMBER = re.compile(r"(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", re.ASCII)
# Suffix -> multiplier that turns the number into millicores.
_CPU_SUFFIXES = {
    "n": Fraction(1, 1_000_000),
    "u": Fraction(1, 1_000),
    "m": Fraction(1),
}
# Suffix -> multiplier that turns the number into bytes. Two-letter binary
# suffixes are matched before the one-letter decimal ones.
_MEMORY_SUFFIXES = {
    "Ki": Fraction(1024),
    "Mi": Fraction(1024**2),
    "Gi": Fraction(1024**3),
    "Ti": Fraction(1024**4),
    "Pi": Fraction(1024**5),
    "Ei": Fraction(1024**6),
    "m": Fraction(1, 1000),
    "k": Fraction(1000),
    "M": Fraction(1000**2),
    "G": Fraction(1000**3),
    "T": Fraction(1000**4),
    "P": Fraction(1000**5),
    "E": Fraction(1000**6),
}


@dataclass(frozen=True)
class NodeBudget:
    """A worker node's capacity and what non-workload pods already request.

    `schedulable` is False for a worker that is cordoned, NotReady or carries
    a NoSchedule/NoExecute taint: kube-scheduler would not place a pod there,
    so the quantum scheduler must not either.
    """

    name: str
    alias: str
    schedulable: bool
    allocatable_cpu_m: int
    allocatable_memory_bytes: int
    used_cpu_m: int
    used_memory_bytes: int

    @property
    def free_cpu_m(self) -> int:
        return max(0, self.allocatable_cpu_m - self.used_cpu_m)

    @property
    def free_memory_bytes(self) -> int:
        return max(0, self.allocatable_memory_bytes - self.used_memory_bytes)


@dataclass(frozen=True)
class WorkloadPod:
    """A workload pod as it exists in the cluster right now.

    `traffic_mbps` maps each peer pod to the Mbps exchanged with it. Every
    link appears on BOTH of its pods, so summing it across all pods counts
    each link twice.
    """

    name: str
    cpu_m: int
    memory_bytes: int
    node_name: str | None  # None while the pod is still Pending
    scheduler_name: str | None
    # Read-only mapping; left out of the hash so instances stay hashable.
    traffic_mbps: Mapping[str, int] = field(hash=False)


@dataclass(frozen=True)
class NetworkCounters:
    """Cumulative bytes a node's kubelet has seen on its default interface.

    Node-wide, not per pod: it includes system traffic (API server, image
    pulls) as well as the workload's.
    """

    node_name: str
    rx_bytes: int
    tx_bytes: int


def _to_fraction(number: str, quantity: str) -> Fraction:
    if not _NUMBER.fullmatch(number):
        raise ValueError(f"invalid Kubernetes quantity: {quantity!r}")
    return Fraction(number)


def parse_cpu(quantity: str) -> int:
    """Kubernetes CPU quantity ("250m", "2", "0.5") -> millicores, rounded up."""
    text = quantity.strip()
    suffix = text[-1:]
    if suffix in _CPU_SUFFIXES:
        return math.ceil(_to_fraction(text[:-1], quantity) * _CPU_SUFFIXES[suffix])
    return math.ceil(_to_fraction(text, quantity) * MILLICORES_PER_CORE)


def parse_memory(quantity: str) -> int:
    """Kubernetes memory quantity ("256Mi", "1Gi", "129M") -> bytes, rounded up."""
    text = quantity.strip()
    for suffix, multiplier in _MEMORY_SUFFIXES.items():
        if text.endswith(suffix):
            number = text[: -len(suffix)]
            return math.ceil(_to_fraction(number, quantity) * multiplier)
    return math.ceil(_to_fraction(text, quantity))


def load_api(context: str = CLUSTER_CONTEXT) -> client.CoreV1Api:
    """CoreV1Api for the k3d cluster — never kubectl's current context."""
    config.load_kube_config(context=context)
    return client.CoreV1Api()


def _container_requests(container: client.V1Container) -> tuple[int, int]:
    requests = (container.resources.requests or {}) if container.resources else {}
    return parse_cpu(requests.get("cpu", "0")), parse_memory(requests.get("memory", "0"))


def _pod_requests(pod: client.V1Pod) -> tuple[int, int]:
    """A pod's effective request as (millicores, bytes), computed the way
    kube-scheduler does: the larger of the containers' sum and the biggest
    init container, plus any pod overhead."""
    main = [_container_requests(c) for c in pod.spec.containers]
    init = [_container_requests(c) for c in pod.spec.init_containers or []]
    overhead = pod.spec.overhead or {}
    cpu_m = max(sum(cpu for cpu, _ in main), max((cpu for cpu, _ in init), default=0))
    memory_bytes = max(sum(mem for _, mem in main), max((mem for _, mem in init), default=0))
    return (
        cpu_m + parse_cpu(overhead.get("cpu", "0")),
        memory_bytes + parse_memory(overhead.get("memory", "0")),
    )


def _is_schedulable(node: client.V1Node) -> bool:
    """Ready, not cordoned, and free of taints that block ordinary pods."""
    spec = node.spec
    if spec and spec.unschedulable:
        return False
    taints = (spec.taints or []) if spec else []
    if any(taint.effect in BLOCKING_TAINT_EFFECTS for taint in taints):
        return False
    conditions = node.status.conditions or []
    return any(c.type == "Ready" and c.status == "True" for c in conditions)


def _used_by_node(
    pods: Sequence[client.V1Pod], workload_namespace: str
) -> dict[str, tuple[int, int]]:
    """Requests of every running, non-workload pod, summed per node."""
    used: dict[str, tuple[int, int]] = {}
    for pod in pods:
        node_name = pod.spec.node_name
        if (
            not node_name
            or pod.metadata.namespace == workload_namespace
            or pod.status.phase in FINISHED_PHASES
        ):
            continue
        cpu_m, memory_bytes = _pod_requests(pod)
        node_cpu, node_memory = used.get(node_name, (0, 0))
        used[node_name] = (node_cpu + cpu_m, node_memory + memory_bytes)
    return used


def read_node_budgets(
    api: client.CoreV1Api, workload_namespace: str = NAMESPACE
) -> tuple[NodeBudget, ...]:
    """Budgets of the worker nodes (those with a cep-alias), sorted by alias.

    The workload namespace's own pods are not counted as used, so the result
    is the capacity available TO the workload. Workers that cannot take pods
    right now are still listed, with schedulable=False.
    """
    workers = [
        node for node in api.list_node().items
        if ALIAS_LABEL in (node.metadata.labels or {})
    ]
    used = _used_by_node(api.list_pod_for_all_namespaces().items, workload_namespace)
    budgets = [
        NodeBudget(
            name=node.metadata.name,
            alias=node.metadata.labels[ALIAS_LABEL],
            schedulable=_is_schedulable(node),
            allocatable_cpu_m=parse_cpu(node.status.allocatable["cpu"]),
            allocatable_memory_bytes=parse_memory(node.status.allocatable["memory"]),
            used_cpu_m=used.get(node.metadata.name, (0, 0))[0],
            used_memory_bytes=used.get(node.metadata.name, (0, 0))[1],
        )
        for node in workers
    ]
    return tuple(sorted(budgets, key=lambda budget: budget.alias))


def _parse_traffic(pod: client.V1Pod) -> Mapping[str, int]:
    """The pod's traffic annotation as {peer: Mbps}; empty when absent."""
    raw = (pod.metadata.annotations or {}).get(TRAFFIC_ANNOTATION)
    if raw is None:
        return MappingProxyType({})
    name = pod.metadata.name
    try:
        traffic = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"pod {name}: traffic annotation is not valid JSON") from None
    if not isinstance(traffic, dict):
        raise ValueError(f"pod {name}: traffic annotation must be a JSON object")
    for peer, mbps in traffic.items():
        if isinstance(mbps, bool) or not isinstance(mbps, int) or mbps < 0:
            raise ValueError(
                f"pod {name}: traffic to {peer!r} must be a non-negative integer"
            )
    return MappingProxyType(traffic)


def read_workload_pods(
    api: client.CoreV1Api, namespace: str = NAMESPACE
) -> tuple[WorkloadPod, ...]:
    """The live workload pods in `namespace`, with their requests and traffic.

    Pods that are being deleted or have finished are left out, so a pod never
    shows up as placed while it is on its way out.
    """
    pods = [
        pod for pod in api.list_namespaced_pod(namespace).items
        if (pod.metadata.labels or {}).get(WORKLOAD_LABEL_KEY) == WORKLOAD_LABEL_VALUE
        and pod.metadata.deletion_timestamp is None
        and pod.status.phase not in FINISHED_PHASES
    ]
    result = []
    for pod in pods:
        cpu_m, memory_bytes = _pod_requests(pod)
        result.append(
            WorkloadPod(
                name=pod.metadata.name,
                cpu_m=cpu_m,
                memory_bytes=memory_bytes,
                node_name=pod.spec.node_name,
                scheduler_name=pod.spec.scheduler_name,
                traffic_mbps=_parse_traffic(pod),
            )
        )
    return tuple(sorted(result, key=lambda pod: pod.name))


def _read_one_node_counters(api: client.CoreV1Api, node_name: str) -> NetworkCounters:
    # _preload_content=False: the client would otherwise turn the JSON body
    # into a Python-repr string that json.loads cannot read back.
    response = api.connect_get_node_proxy_with_path(
        node_name, KUBELET_STATS_PATH, _preload_content=False
    )
    network = json.loads(response.data)["node"]["network"]
    return NetworkCounters(
        node_name=node_name,
        rx_bytes=int(network["rxBytes"]),
        tx_bytes=int(network["txBytes"]),
    )


def read_network_counters(
    api: client.CoreV1Api, node_names: Sequence[str]
) -> tuple[NetworkCounters, ...]:
    """Best-effort kubelet rx/tx counters; nodes that fail are logged and skipped."""
    counters = []
    for node_name in node_names:
        try:
            counters.append(_read_one_node_counters(api, node_name))
        except Exception as exc:  # best-effort: any kubelet/proxy failure
            logger.warning("no network counters for node %s: %s", node_name, exc)
    return tuple(counters)


def _format_budgets(budgets: Sequence[NodeBudget]) -> list[str]:
    lines = ["Node budgets (free = allocatable - other pods' requests)"]
    for budget in budgets:
        lines.append(
            f"  {budget.alias:<12} {budget.name:<30} "
            f"cpu {budget.free_cpu_m}m / {budget.allocatable_cpu_m}m   "
            f"memory {budget.free_memory_bytes // MEBIBYTE}Mi / "
            f"{budget.allocatable_memory_bytes // MEBIBYTE}Mi"
            f"{'' if budget.schedulable else '   (unschedulable)'}"
        )
    return lines


def _format_pods(pods: Sequence[WorkloadPod], namespace: str) -> list[str]:
    lines = [f"Workload pods in namespace {namespace}"]
    if not pods:
        return lines + ["  (no workload pods found)"]
    for pod in pods:
        lines.append(
            f"  {pod.name:<12} cpu {pod.cpu_m}m   "
            f"memory {pod.memory_bytes // MEBIBYTE}Mi   "
            f"node {pod.node_name or 'Pending'}   "
            f"traffic {sum(pod.traffic_mbps.values())} Mbps"
        )
    return lines


def _format_counters(counters: Sequence[NetworkCounters]) -> list[str]:
    lines = ["Kubelet network counters (cumulative bytes)"]
    if not counters:
        return lines + ["  (not available)"]
    for counter in counters:
        lines.append(
            f"  {counter.node_name:<30} rx {counter.rx_bytes}   tx {counter.tx_bytes}"
        )
    return lines


def build_report(api: client.CoreV1Api, namespace: str = NAMESPACE) -> str:
    """Human-readable snapshot of node budgets, workload pods and counters."""
    budgets = read_node_budgets(api, namespace)
    pods = read_workload_pods(api, namespace)
    counters = read_network_counters(api, [budget.name for budget in budgets])
    sections = (
        _format_budgets(budgets),
        _format_pods(pods, namespace),
        _format_counters(counters),
    )
    return "\n\n".join("\n".join(section) for section in sections)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--context", default=CLUSTER_CONTEXT, help="kubeconfig context")
    parser.add_argument("--namespace", default=NAMESPACE, help="workload namespace")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        report = build_report(load_api(args.context), args.namespace)
    except Exception as exc:
        print(f"Error: could not read cluster state: {exc}", file=sys.stderr)
        return 1
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
