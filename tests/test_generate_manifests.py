"""generate_manifests: two YAML files with the same 10 pods (one for the
default scheduler, one for quantum-scheduler), requests scaled to the
per-node budget, written without needing a live cluster in --offline mode."""
import json
from pathlib import Path

import pytest
import yaml

from src import cluster_metrics, generate_manifests, workload
from src.generate_manifests import PerNodeBudget
from tests.fakes import FakeCoreApi, make_node, make_pod

GI = 1024**3
MI = 1024**2
BUDGET = PerNodeBudget(cpu_m=4000, memory_bytes=8 * GI)


def _load(path: Path) -> list[dict]:
    return list(yaml.safe_load_all(path.read_text()))


def _pods(documents: list[dict]) -> list[dict]:
    return [d for d in documents if d["kind"] == "Pod"]


def test_documents_are_one_namespace_then_ten_pods() -> None:
    documents = generate_manifests.build_documents(BUDGET, scheduler_name=None)

    assert [d["kind"] for d in documents] == ["Namespace"] + ["Pod"] * 10
    assert documents[0]["metadata"]["name"] == workload.NAMESPACE
    assert [p["metadata"]["name"] for p in _pods(documents)] == list(workload.pod_names())
    assert all(p["metadata"]["namespace"] == workload.NAMESPACE for p in _pods(documents))


def test_default_pods_have_no_scheduler_name() -> None:
    documents = generate_manifests.build_documents(BUDGET, scheduler_name=None)

    assert all("schedulerName" not in p["spec"] for p in _pods(documents))


def test_quantum_pods_name_the_quantum_scheduler() -> None:
    documents = generate_manifests.build_documents(
        BUDGET, scheduler_name=workload.QUANTUM_SCHEDULER_NAME
    )

    assert all(p["spec"]["schedulerName"] == "quantum-scheduler" for p in _pods(documents))


def test_requests_are_the_pod_share_of_the_per_node_budget() -> None:
    documents = generate_manifests.build_documents(BUDGET, scheduler_name=None)

    for spec, pod in zip(workload.PODS, _pods(documents)):
        requests = pod["spec"]["containers"][0]["resources"]["requests"]
        assert cluster_metrics.parse_cpu(requests["cpu"]) == 4000 * spec.cpu_percent // 100
        expected_mib = 8 * 1024 * spec.memory_percent // 100
        assert cluster_metrics.parse_memory(requests["memory"]) == expected_mib * MI


def test_pods_carry_their_traffic_annotation_and_workload_label() -> None:
    documents = generate_manifests.build_documents(BUDGET, scheduler_name=None)

    for pod in _pods(documents):
        metadata = pod["metadata"]
        traffic = json.loads(metadata["annotations"][workload.TRAFFIC_ANNOTATION])
        assert traffic == dict(workload.traffic_peers(metadata["name"]))
        assert metadata["labels"][workload.WORKLOAD_LABEL_KEY] == workload.WORKLOAD_LABEL_VALUE


def test_pods_may_only_run_on_nodes_with_a_cep_alias() -> None:
    """Keeps the default scheduler on the same 3 workers the quantum one uses."""
    documents = generate_manifests.build_documents(BUDGET, scheduler_name=None)

    for pod in _pods(documents):
        required = pod["spec"]["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]
        expressions = required["nodeSelectorTerms"][0]["matchExpressions"]
        assert expressions == [{"key": cluster_metrics.ALIAS_LABEL, "operator": "Exists"}]


def test_per_node_budget_is_the_smallest_free_capacity_across_workers() -> None:
    nodes = [
        make_node("agent-0", "4", "8Gi", alias="node-alpha"),
        make_node("agent-1", "4", "6Gi", alias="node-beta"),
        make_node("agent-2", "4", "8Gi", alias="node-gamma"),
    ]
    pods = [make_pod("dns", "kube-system", "agent-2", cpu="500m", memory="64Mi")]
    budgets = cluster_metrics.read_node_budgets(FakeCoreApi(nodes=nodes, pods=pods))

    budget = generate_manifests.per_node_budget(budgets)

    assert budget == PerNodeBudget(cpu_m=3500, memory_bytes=6 * GI)


def test_per_node_budget_needs_workers_with_free_capacity() -> None:
    with pytest.raises(ValueError, match="no schedulable worker nodes"):
        generate_manifests.per_node_budget([])

    full = [make_node("agent-0", "1", "1Gi", alias="node-alpha")]
    hog = [make_pod("hog", "default", "agent-0", cpu="1", memory="1Gi")]
    budgets = cluster_metrics.read_node_budgets(FakeCoreApi(nodes=full, pods=hog))
    with pytest.raises(ValueError, match="too little free capacity"):
        generate_manifests.per_node_budget(budgets)


def test_offline_run_writes_both_files_without_a_cluster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_cluster(_context: str) -> None:
        raise AssertionError("--offline must not contact the cluster")

    monkeypatch.setattr(cluster_metrics, "load_api", no_cluster)

    exit_code = generate_manifests.main(["--offline", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    default_docs = _load(tmp_path / "test-pods.yaml")
    quantum_docs = _load(tmp_path / "test-pods-quantum.yaml")
    for documents in (default_docs, quantum_docs):
        assert len(_pods(documents)) == 10
        assert sum(d["kind"] == "Namespace" for d in documents) == 1
    assert all("schedulerName" not in p["spec"] for p in _pods(default_docs))
    assert all(p["spec"]["schedulerName"] == "quantum-scheduler" for p in _pods(quantum_docs))


def test_the_two_files_differ_only_in_scheduler_name(tmp_path: Path) -> None:
    generate_manifests.main(["--offline", "--output-dir", str(tmp_path)])
    default_docs = _load(tmp_path / "test-pods.yaml")
    quantum_docs = _load(tmp_path / "test-pods-quantum.yaml")

    for pod in _pods(quantum_docs):
        del pod["spec"]["schedulerName"]

    assert quantum_docs == default_docs


def test_live_run_scales_requests_to_the_cluster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = [make_node(f"agent-{i}", "2", "4Gi", alias=a) for i, a in enumerate(("node-alpha", "node-beta", "node-gamma"))]
    monkeypatch.setattr(cluster_metrics, "load_api", lambda _context: FakeCoreApi(nodes=nodes))

    exit_code = generate_manifests.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    first_pod = _pods(_load(tmp_path / "test-pods.yaml"))[0]
    requests = first_pod["spec"]["containers"][0]["resources"]["requests"]
    assert cluster_metrics.parse_cpu(requests["cpu"]) == 2000 * workload.PODS[0].cpu_percent // 100


def test_live_run_fails_clearly_when_the_cluster_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(_context: str) -> None:
        raise ConnectionError("cluster is down")

    monkeypatch.setattr(cluster_metrics, "load_api", refuse)

    exit_code = generate_manifests.main(["--output-dir", str(tmp_path)])

    assert exit_code == 1
    assert "cluster is down" in capsys.readouterr().err
    assert not (tmp_path / "test-pods.yaml").exists()


def test_requests_for_known_pods_match_hand_computed_values() -> None:
    """Fixed literals, so a change to the scaling rule cannot hide behind a
    test that repeats the same formula."""
    documents = generate_manifests.build_documents(BUDGET, scheduler_name=None)
    requests = {
        p["metadata"]["name"]: p["spec"]["containers"][0]["resources"]["requests"]
        for p in _pods(documents)
    }

    assert requests["frontend"] == {"cpu": "800m", "memory": "1228Mi"}
    assert requests["database"] == {"cpu": "1600m", "memory": "3686Mi"}


def test_per_node_budget_skips_workers_that_cannot_take_pods() -> None:
    nodes = [
        make_node("agent-0", "4", "8Gi", alias="node-alpha"),
        make_node("agent-1", "1", "1Gi", alias="node-beta", unschedulable=True),
        make_node("agent-2", "2", "2Gi", alias="node-gamma", ready=False),
    ]
    budgets = cluster_metrics.read_node_budgets(FakeCoreApi(nodes=nodes))

    assert generate_manifests.per_node_budget(budgets) == PerNodeBudget(4000, 8 * GI)


def test_per_node_budget_rejects_a_budget_too_small_to_scale() -> None:
    nodes = [make_node("agent-0", "50m", "8Gi", alias="node-alpha")]
    budgets = cluster_metrics.read_node_budgets(FakeCoreApi(nodes=nodes))

    with pytest.raises(ValueError, match="too little free capacity"):
        generate_manifests.per_node_budget(budgets)


def test_capacity_error_does_not_suggest_the_cluster_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cluster_metrics, "load_api", lambda _context: FakeCoreApi())

    exit_code = generate_manifests.main(["--output-dir", str(tmp_path)])

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "no schedulable worker nodes" in err
    assert "Is the cluster up" not in err


def test_unwritable_output_dir_is_reported_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file in the way")

    exit_code = generate_manifests.main(["--offline", "--output-dir", str(blocker)])

    assert exit_code == 1
    assert "could not write manifests" in capsys.readouterr().err
