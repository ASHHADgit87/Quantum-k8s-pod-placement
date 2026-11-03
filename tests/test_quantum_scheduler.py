"""Tests for Batched QAOA scheduler and Binding API."""
import logging
from unittest.mock import patch, MagicMock
import pytest
from src import quantum_scheduler

def test_sort_pods_by_traffic():
    """Pods should be ordered heaviest communicators first."""
    sorted_pods = quantum_scheduler.sort_pods_by_traffic()
    assert len(sorted_pods) == 10
    assert sorted_pods[0].name == "gateway"
    assert sorted_pods[1].name == "catalog"

@patch("src.quantum_scheduler.bind_pod_to_node")
def test_main_offline_dry_run(mock_bind, caplog):
    """Offline dry-run must complete, print feasible assignment, and NOT bind."""
    caplog.set_level(logging.INFO)
    
    exit_code = quantum_scheduler.main(["--offline", "--dry-run"])
    
    assert exit_code == 0
    
    mock_bind.assert_not_called()
    
    logs = caplog.text
    assert "Final placement achieved" in logs
    assert "Dry-run complete. Placements:" in logs
    
    placements_str = [line for line in logs.splitlines() if "Placements:" in line][0]
    
    for pod_name in ["frontend", "gateway", "auth", "catalog", "cart", "orders", "payments", "database", "cache", "queue"]:
        assert f"'{pod_name}':" in placements_str


def test_setup_qaoa_optimizer_forwards_callback():
    """The benchmark relies on the callback reaching QAOA to record energies."""
    def callback(eval_count, parameters, energy, metadata):
        pass

    optimizer = quantum_scheduler.setup_qaoa_optimizer(callback=callback)
    assert optimizer.min_eigen_solver.callback is callback

    assert quantum_scheduler.setup_qaoa_optimizer().min_eigen_solver.callback is None


from types import SimpleNamespace

from src import workload
from src.cluster_metrics import NodeBudget
from src.qubo_builder import build_qubo


def _nodes():
    return [NodeBudget(f"agent-{i}", a, True, 4000, 8589934592, 0, 0)
            for i, a in enumerate(("node-alpha", "node-beta", "node-gamma"))]


def _sample(x, fval):
    return SimpleNamespace(x=x, fval=fval, probability=0.1, status=None)


def test_select_feasible_sample_prefers_lowest_energy_feasible():
    batch = list(workload.PODS[:2])  # frontend, gateway
    nodes = _nodes()[:2]
    full_qp = build_qubo(batch, nodes, workload.TRAFFIC)
    result = SimpleNamespace(samples=[
        _sample([1, 1, 1, 0], -5.0),   # frontend on both nodes: infeasible
        _sample([1, 0, 0, 1], 50.0),   # feasible, cross-node
        _sample([0, 1, 0, 1], 0.0),    # feasible, same node, best
        _sample([0, 0, 0, 0], -9.0),   # nothing assigned: infeasible
    ])

    assignment, cost = quantum_scheduler.select_feasible_sample(result, full_qp, batch, nodes)
    assert assignment == {"frontend": "agent-1", "gateway": "agent-1"}
    assert cost == 0.0


def test_select_feasible_sample_returns_none_without_feasible_samples():
    batch = list(workload.PODS[:1])
    nodes = _nodes()[:2]
    full_qp = build_qubo(batch, nodes, workload.TRAFFIC)
    result = SimpleNamespace(samples=[_sample([0, 0], 0.0), _sample([1, 1], 0.0)])
    assert quantum_scheduler.select_feasible_sample(result, full_qp, batch, nodes) is None


def test_solve_batch_falls_back_when_solver_raises(caplog):
    class BrokenOptimizer:
        def solve(self, qp):
            raise RuntimeError("simulator exploded")

    caplog.set_level(logging.WARNING)
    batch = list(workload.PODS[:3])
    assignment, cost, used_fallback = quantum_scheduler.solve_batch(BrokenOptimizer(), batch, _nodes())

    assert used_fallback is True
    assert set(assignment) == {p.name for p in batch}
    assert cost >= 0
    assert "falling back" in caplog.text


def test_solve_batch_uses_qaoa_sample_when_feasible():
    batch = list(workload.PODS[:2])
    nodes = _nodes()[:2]

    class FakeOptimizer:
        def solve(self, qp):
            assert len(qp.linear_constraints) == 2, "QAOA must get the reduced program"
            return SimpleNamespace(samples=[_sample([0, 1, 0, 1], 0.0)])

    assignment, cost, used_fallback = quantum_scheduler.solve_batch(FakeOptimizer(), batch, nodes)
    assert used_fallback is False
    assert assignment == {"frontend": "agent-1", "gateway": "agent-1"}
    assert cost == 0.0


def test_real_qaoa_produces_feasible_sample_for_one_batch():
    """End-to-end: the real 9-qubit QAOA run must yield at least one feasible sample."""
    batch = list(workload.PODS[:3])
    nodes = _nodes()
    optimizer = quantum_scheduler.setup_qaoa_optimizer()
    assignment, cost, used_fallback = quantum_scheduler.solve_batch(optimizer, batch, nodes)

    assert used_fallback is False
    assert set(assignment) == {p.name for p in batch}
    assert cost >= 0


def test_update_budgets_uses_each_nodes_allocatable():
    small = NodeBudget("small", "s", True, 2000, 4294967296, 0, 0)
    pod = workload.PODS[0]  # frontend: 20% cpu, 15% memory
    (updated,) = quantum_scheduler.update_budgets([small], [pod], {pod.name: "small"})

    assert updated.used_cpu_m == 400
    assert updated.used_memory_bytes == int(4294967296 * 0.15)
    assert small.used_cpu_m == 0, "input must not be mutated"


def test_select_feasible_sample_breaks_ties_by_probability():
    batch = list(workload.PODS[:1])
    nodes = _nodes()[:2]
    full_qp = build_qubo(batch, nodes, workload.TRAFFIC)
    rare = SimpleNamespace(x=[1, 0], fval=0.0, probability=0.01, status=None)
    common = SimpleNamespace(x=[0, 1], fval=0.0, probability=0.9, status=None)
    result = SimpleNamespace(samples=[rare, common])

    assignment, _ = quantum_scheduler.select_feasible_sample(result, full_qp, batch, nodes)
    assert assignment == {"frontend": "agent-1"}
