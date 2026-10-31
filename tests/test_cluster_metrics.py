"""cluster_metrics against a fake in-memory API: node budgets subtract what
other pods already use, workload pods carry their traffic annotation, and
network counters are best-effort."""
import json

import pytest

from src import cluster_metrics, workload
from tests.fakes import FakeCoreApi, make_node, make_pod

GI = 1024**3
MI = 1024**2
WORKLOAD_LABELS = {workload.WORKLOAD_LABEL_KEY: workload.WORKLOAD_LABEL_VALUE}


def _three_workers_and_a_server() -> list:
    return [
        make_node("server-0", "4", "8Gi"),
        make_node("agent-1", "4", "8Gi", alias="node-beta"),
        make_node("agent-0", "4", "8Gi", alias="node-alpha"),
        make_node("agent-2", "2", "4Gi", alias="node-gamma"),
    ]


def test_node_budgets_cover_only_aliased_workers_sorted_by_alias() -> None:
    api = FakeCoreApi(nodes=_three_workers_and_a_server())

    budgets = cluster_metrics.read_node_budgets(api)

    assert [b.alias for b in budgets] == ["node-alpha", "node-beta", "node-gamma"]
    assert [b.name for b in budgets] == ["agent-0", "agent-1", "agent-2"]


def test_node_budget_reports_allocatable_capacity() -> None:
    api = FakeCoreApi(nodes=_three_workers_and_a_server())

    gamma = cluster_metrics.read_node_budgets(api)[2]

    assert gamma.allocatable_cpu_m == 2000
    assert gamma.allocatable_memory_bytes == 4 * GI
    assert gamma.free_cpu_m == 2000
    assert gamma.free_memory_bytes == 4 * GI


def test_node_budget_subtracts_requests_of_other_pods_on_that_node() -> None:
    pods = [
        make_pod("dns", "kube-system", "agent-0", cpu="100m", memory="70Mi"),
        make_pod("metrics", "kube-system", "agent-0", cpu="150m", memory="30Mi"),
        make_pod("elsewhere", "kube-system", "agent-1", cpu="1", memory="1Gi"),
    ]
    api = FakeCoreApi(nodes=_three_workers_and_a_server(), pods=pods)

    alpha, beta, gamma = cluster_metrics.read_node_budgets(api)

    assert alpha.used_cpu_m == 250
    assert alpha.used_memory_bytes == 100 * MI
    assert alpha.free_cpu_m == 3750
    assert alpha.free_memory_bytes == 8 * GI - 100 * MI
    assert beta.free_cpu_m == 3000
    assert gamma.used_cpu_m == 0


def test_node_budget_ignores_workload_pending_and_finished_pods() -> None:
    pods = [
        make_pod("ours", workload.NAMESPACE, "agent-0", cpu="1", memory="1Gi"),
        make_pod("pending", "default", None, cpu="1", memory="1Gi"),
        make_pod("done", "default", "agent-0", cpu="1", memory="1Gi", phase="Succeeded"),
        make_pod("crashed", "default", "agent-0", cpu="1", memory="1Gi", phase="Failed"),
        make_pod("no-requests", "default", "agent-0"),
    ]
    api = FakeCoreApi(nodes=_three_workers_and_a_server(), pods=pods)

    alpha = cluster_metrics.read_node_budgets(api)[0]

    assert alpha.used_cpu_m == 0
    assert alpha.used_memory_bytes == 0


def test_free_budget_never_goes_negative() -> None:
    pods = [make_pod("hog", "default", "agent-2", cpu="3", memory="6Gi")]
    api = FakeCoreApi(nodes=_three_workers_and_a_server(), pods=pods)

    gamma = cluster_metrics.read_node_budgets(api)[2]

    assert gamma.free_cpu_m == 0
    assert gamma.free_memory_bytes == 0


def test_workload_pods_carry_requests_node_and_traffic() -> None:
    traffic = {"cache": 40, "database": 30}
    pods = [
        make_pod(
            "catalog",
            workload.NAMESPACE,
            "agent-1",
            cpu="800m",
            memory="1638Mi",
            labels=WORKLOAD_LABELS,
            annotations={workload.TRAFFIC_ANNOTATION: json.dumps(traffic)},
            scheduler_name="quantum-scheduler",
        ),
        make_pod("stranger", workload.NAMESPACE, "agent-1", cpu="1", memory="1Gi"),
        make_pod("other-ns", "default", "agent-1", labels=WORKLOAD_LABELS),
    ]
    api = FakeCoreApi(pods=pods)

    result = cluster_metrics.read_workload_pods(api)

    assert len(result) == 1
    pod = result[0]
    assert pod.name == "catalog"
    assert pod.cpu_m == 800
    assert pod.memory_bytes == 1638 * MI
    assert pod.node_name == "agent-1"
    assert pod.scheduler_name == "quantum-scheduler"
    assert dict(pod.traffic_mbps) == traffic


def test_pending_workload_pod_has_no_node_and_missing_annotation_means_no_traffic() -> None:
    pods = [make_pod("queue", workload.NAMESPACE, None, cpu="1", memory="1Gi", labels=WORKLOAD_LABELS, phase="Pending")]
    api = FakeCoreApi(pods=pods)

    pod = cluster_metrics.read_workload_pods(api)[0]

    assert pod.node_name is None
    assert dict(pod.traffic_mbps) == {}


@pytest.mark.parametrize("annotation", ["not json", "[1, 2]", '{"cache": "fast"}', '{"cache": -5}'])
def test_malformed_traffic_annotation_is_rejected(annotation: str) -> None:
    pods = [
        make_pod(
            "catalog",
            workload.NAMESPACE,
            "agent-1",
            labels=WORKLOAD_LABELS,
            annotations={workload.TRAFFIC_ANNOTATION: annotation},
        )
    ]
    api = FakeCoreApi(pods=pods)

    with pytest.raises(ValueError, match="catalog"):
        cluster_metrics.read_workload_pods(api)


def test_network_counters_come_from_the_kubelet_summary() -> None:
    stats = {"agent-0": {"node": {"network": {"rxBytes": 1200, "txBytes": 3400}}}}
    api = FakeCoreApi(node_stats=stats)

    counters = cluster_metrics.read_network_counters(api, ["agent-0"])

    assert len(counters) == 1
    assert counters[0].node_name == "agent-0"
    assert counters[0].rx_bytes == 1200
    assert counters[0].tx_bytes == 3400


def test_network_counters_skip_nodes_that_cannot_be_read() -> None:
    stats = {
        "agent-0": {"node": {"network": {"rxBytes": 1, "txBytes": 2}}},
        "agent-2": {"node": {}},  # reachable, but reports no network section
    }
    api = FakeCoreApi(node_stats=stats)

    counters = cluster_metrics.read_network_counters(api, ["agent-0", "agent-1", "agent-2"])

    assert [c.node_name for c in counters] == ["agent-0"]


def test_report_lists_budgets_pods_and_counters() -> None:
    pods = [
        make_pod(
            "catalog",
            workload.NAMESPACE,
            "agent-1",
            cpu="800m",
            memory="1024Mi",
            labels=WORKLOAD_LABELS,
            annotations={workload.TRAFFIC_ANNOTATION: '{"cache": 40}'},
        )
    ]
    stats = {"agent-0": {"node": {"network": {"rxBytes": 1200, "txBytes": 3400}}}}
    api = FakeCoreApi(nodes=_three_workers_and_a_server(), pods=pods, node_stats=stats)

    report = cluster_metrics.build_report(api)

    for expected in ("node-alpha", "node-beta", "node-gamma", "catalog", "800m", "1024Mi", "1200", "3400"):
        assert expected in report


def test_report_says_so_when_there_are_no_pods_or_counters() -> None:
    api = FakeCoreApi(nodes=_three_workers_and_a_server())

    report = cluster_metrics.build_report(api)

    assert "no workload pods" in report
    assert "not available" in report


def test_main_returns_error_code_when_cluster_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(_context: str) -> None:
        raise ConnectionError("cluster is down")

    monkeypatch.setattr(cluster_metrics, "load_api", refuse)

    assert cluster_metrics.main([]) == 1
    assert "cluster is down" in capsys.readouterr().err


def test_main_prints_the_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeCoreApi(nodes=_three_workers_and_a_server())
    monkeypatch.setattr(cluster_metrics, "load_api", lambda _context: api)

    assert cluster_metrics.main([]) == 0
    assert "node-alpha" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("node_kwargs", "expected"),
    [
        ({}, True),
        ({"ready": False}, False),
        ({"unschedulable": True}, False),
        ({"taint_effect": "NoSchedule"}, False),
        ({"taint_effect": "NoExecute"}, False),
        ({"taint_effect": "PreferNoSchedule"}, True),
    ],
)
def test_node_budget_flags_workers_that_cannot_take_pods(
    node_kwargs: dict, expected: bool
) -> None:
    nodes = [make_node("agent-0", "4", "8Gi", alias="node-alpha", **node_kwargs)]

    budget = cluster_metrics.read_node_budgets(FakeCoreApi(nodes=nodes))[0]

    assert budget.schedulable is expected


def test_pod_request_uses_the_larger_of_containers_and_init_plus_overhead() -> None:
    from kubernetes import client

    pod = make_pod("sys", "kube-system", "agent-0", cpu="200m", memory="100Mi")
    heavy_init = client.V1Container(
        name="init",
        image="test",
        resources=client.V1ResourceRequirements(requests={"cpu": "1", "memory": "50Mi"}),
    )
    pod.spec.init_containers = [heavy_init]
    pod.spec.overhead = {"cpu": "100m", "memory": "10Mi"}
    api = FakeCoreApi(nodes=_three_workers_and_a_server(), pods=[pod])

    alpha = cluster_metrics.read_node_budgets(api)[0]

    assert alpha.used_cpu_m == 1100  # init container (1000m) wins, plus overhead
    assert alpha.used_memory_bytes == 110 * MI  # containers (100Mi) win, plus overhead


def test_workload_pods_leave_out_terminating_and_finished_pods() -> None:
    from datetime import datetime, timezone

    terminating = make_pod("cart", workload.NAMESPACE, "agent-0", labels=WORKLOAD_LABELS)
    terminating.metadata.deletion_timestamp = datetime.now(timezone.utc)
    pods = [
        terminating,
        make_pod("auth", workload.NAMESPACE, "agent-0", labels=WORKLOAD_LABELS, phase="Failed"),
        make_pod("queue", workload.NAMESPACE, "agent-0", labels=WORKLOAD_LABELS, phase="Succeeded"),
        make_pod("cache", workload.NAMESPACE, "agent-0", labels=WORKLOAD_LABELS),
    ]

    result = cluster_metrics.read_workload_pods(FakeCoreApi(pods=pods))

    assert [pod.name for pod in result] == ["cache"]


def test_workload_pod_and_node_budget_are_hashable() -> None:
    pods = [make_pod("cache", workload.NAMESPACE, "agent-0", labels=WORKLOAD_LABELS, annotations={workload.TRAFFIC_ANNOTATION: '{"cart": 30}'})]
    api = FakeCoreApi(nodes=_three_workers_and_a_server(), pods=pods)

    assert len({*cluster_metrics.read_workload_pods(api)}) == 1
    assert len({*cluster_metrics.read_node_budgets(api)}) == 3


def test_report_marks_unschedulable_workers() -> None:
    nodes = [make_node("agent-0", "4", "8Gi", alias="node-alpha", unschedulable=True)]

    assert "(unschedulable)" in cluster_metrics.build_report(FakeCoreApi(nodes=nodes))
