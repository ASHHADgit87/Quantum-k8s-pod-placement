"""The workload table is the single source of truth for the whole project, so
its invariants are pinned here: 10 pods, sane demands, a consistent traffic
graph, and a pod set that actually fits on 3 worker nodes."""
import itertools
import re

from src import workload

WORKER_COUNT = 3
FULL_NODE_PERCENT = 100
DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def test_workload_has_exactly_ten_pods() -> None:
    assert len(workload.PODS) == 10


def test_pod_names_are_unique_valid_kubernetes_names() -> None:
    names = workload.pod_names()

    assert len(set(names)) == len(names)
    assert all(DNS_LABEL.match(name) for name in names)


def test_every_demand_is_a_positive_share_of_one_node() -> None:
    for pod in workload.PODS:
        assert 0 < pod.cpu_percent <= FULL_NODE_PERCENT
        assert 0 < pod.memory_percent <= FULL_NODE_PERCENT


def test_workload_fits_on_three_workers() -> None:
    feasible = any(
        _fits(assignment)
        for assignment in itertools.product(range(WORKER_COUNT), repeat=len(workload.PODS))
    )

    assert feasible


def _fits(assignment: tuple[int, ...]) -> bool:
    cpu = [0] * WORKER_COUNT
    memory = [0] * WORKER_COUNT
    for pod, node in zip(workload.PODS, assignment):
        cpu[node] += pod.cpu_percent
        memory[node] += pod.memory_percent
    return max(cpu) <= FULL_NODE_PERCENT and max(memory) <= FULL_NODE_PERCENT


def test_workload_does_not_fit_on_two_workers() -> None:
    """Otherwise placement is trivial and the benchmark shows nothing."""
    total_cpu = sum(pod.cpu_percent for pod in workload.PODS)

    assert total_cpu > 2 * FULL_NODE_PERCENT


def test_traffic_edges_connect_two_different_known_pods() -> None:
    names = set(workload.pod_names())

    for edge in workload.TRAFFIC:
        assert edge.source in names
        assert edge.target in names
        assert edge.source != edge.target
        assert edge.mbps > 0


def test_traffic_has_no_duplicate_pod_pairs() -> None:
    pairs = [frozenset((edge.source, edge.target)) for edge in workload.TRAFFIC]

    assert len(set(pairs)) == len(pairs)


def test_every_pod_talks_to_at_least_one_other_pod() -> None:
    for name in workload.pod_names():
        assert workload.traffic_peers(name)


def test_traffic_peers_is_symmetric() -> None:
    for edge in workload.TRAFFIC:
        assert workload.traffic_peers(edge.source)[edge.target] == edge.mbps
        assert workload.traffic_peers(edge.target)[edge.source] == edge.mbps


def test_total_traffic_is_the_sum_over_peers() -> None:
    for name in workload.pod_names():
        assert workload.total_traffic(name) == sum(workload.traffic_peers(name).values())


def test_sum_of_pod_totals_counts_every_edge_twice() -> None:
    edge_total = sum(edge.mbps for edge in workload.TRAFFIC)
    pod_total = sum(workload.total_traffic(name) for name in workload.pod_names())

    assert pod_total == 2 * edge_total


def test_traffic_graph_has_a_node_per_pod_and_a_weighted_edge_per_link() -> None:
    graph = workload.traffic_graph()

    assert set(graph.nodes) == set(workload.pod_names())
    assert graph.number_of_edges() == len(workload.TRAFFIC)
    first = workload.TRAFFIC[0]
    assert graph[first.source][first.target]["mbps"] == first.mbps
