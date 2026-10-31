"""Single source of truth for the test workload: the 10-pod table and the
simulated traffic between pods. Nothing else in the project hardcodes these
numbers a second time — import them from here.

Demands are a percentage of ONE worker node's budget, not absolute CPU/RAM,
so the same table works on any machine: generate_manifests scales them to
the real cluster's per-node capacity.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import networkx as nx

NAMESPACE = "quantum-sched-test"
QUANTUM_SCHEDULER_NAME = "quantum-scheduler"
# Label every workload pod carries, and the annotation holding its simulated
# traffic as JSON: {"<peer pod name>": <Mbps>, ...}.
WORKLOAD_LABEL_KEY = "app.kubernetes.io/part-of"
WORKLOAD_LABEL_VALUE = "cep-workload"
TRAFFIC_ANNOTATION = "cep.quantum/traffic-mbps"


@dataclass(frozen=True)
class PodDemand:
    """One pod's demand, as a percentage of a single worker node's budget."""

    name: str
    cpu_percent: int
    memory_percent: int


@dataclass(frozen=True)
class TrafficEdge:
    """Simulated traffic between two pods (undirected), in Mbps."""

    source: str
    target: str
    mbps: int


# A small web shop. Totals: CPU 220%, memory 210% of one node — needs all
# 3 workers (does not fit on 2), with room left for the placement to matter.
PODS: tuple[PodDemand, ...] = (
    PodDemand("frontend", cpu_percent=20, memory_percent=15),
    PodDemand("gateway", cpu_percent=25, memory_percent=15),
    PodDemand("auth", cpu_percent=15, memory_percent=10),
    PodDemand("catalog", cpu_percent=20, memory_percent=20),
    PodDemand("cart", cpu_percent=15, memory_percent=15),
    PodDemand("orders", cpu_percent=25, memory_percent=20),
    PodDemand("payments", cpu_percent=20, memory_percent=15),
    PodDemand("database", cpu_percent=40, memory_percent=45),
    PodDemand("cache", cpu_percent=20, memory_percent=35),
    PodDemand("queue", cpu_percent=20, memory_percent=20),
)

TRAFFIC: tuple[TrafficEdge, ...] = (
    TrafficEdge("frontend", "gateway", 50),
    TrafficEdge("gateway", "auth", 20),
    TrafficEdge("gateway", "catalog", 30),
    TrafficEdge("gateway", "cart", 25),
    TrafficEdge("gateway", "orders", 20),
    TrafficEdge("auth", "cache", 10),
    TrafficEdge("catalog", "database", 30),
    TrafficEdge("catalog", "cache", 40),
    TrafficEdge("cart", "cache", 30),
    TrafficEdge("orders", "database", 35),
    TrafficEdge("orders", "payments", 15),
    TrafficEdge("orders", "queue", 20),
    TrafficEdge("payments", "database", 15),
    TrafficEdge("payments", "queue", 10),
)


def pod_names() -> tuple[str, ...]:
    return tuple(pod.name for pod in PODS)


def traffic_peers(pod_name: str) -> Mapping[str, int]:
    """Every pod this one exchanges traffic with, and how much (Mbps)."""
    peers = {}
    for edge in TRAFFIC:
        if edge.source == pod_name:
            peers[edge.target] = edge.mbps
        elif edge.target == pod_name:
            peers[edge.source] = edge.mbps
    return MappingProxyType(peers)


def total_traffic(pod_name: str) -> int:
    """Total Mbps this pod exchanges with all its peers."""
    return sum(traffic_peers(pod_name).values())


def traffic_graph() -> nx.Graph:
    """The traffic as an undirected graph: one node per pod, `mbps` on edges."""
    graph = nx.Graph()
    graph.add_nodes_from(pod_names())
    graph.add_weighted_edges_from(
        ((edge.source, edge.target, edge.mbps) for edge in TRAFFIC), weight="mbps"
    )
    return graph
