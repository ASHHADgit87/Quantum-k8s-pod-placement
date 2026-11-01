"""Tests for benchmark engine and output data validation."""
import json

import pytest

from src import benchmark, workload
from src.cluster_metrics import NodeBudget


def _fresh_nodes():
    return [
        NodeBudget("agent-0", "node-alpha", True, 4000, 8589934592, 0, 0),
        NodeBudget("agent-1", "node-beta", True, 4000, 8589934592, 0, 0),
        NodeBudget("agent-2", "node-gamma", True, 4000, 8589934592, 0, 0),
    ]


def test_benchmark_execution_and_json(tmp_path, monkeypatch):
    """Benchmark runner must complete, produce valid JSON, and ensure feasibility."""
    monkeypatch.setattr(benchmark, "RESULTS_DIR", tmp_path)

    # Mock heavy quantum solver for < 5 second test completion
    def mock_quantum_solve(optimizer, batch, nodes, recorder=None):
        return benchmark._solve_default_batch(batch, nodes), False
    monkeypatch.setattr(benchmark, "_solve_quantum_batch", mock_quantum_solve)
    monkeypatch.setattr(benchmark, "setup_qaoa_optimizer", lambda callback=None: None)
    monkeypatch.setattr(benchmark, "compute_exact_optimum", lambda pods, nodes: 42)

    exit_code = benchmark.main(["--iterations", "1"])
    assert exit_code == 0

    data_file = tmp_path / "benchmark_data.json"
    assert data_file.exists()

    payload = json.loads(data_file.read_text())
    assert "metadata" in payload
    assert payload["metadata"]["exact_optimum_objective"] == 42
    assert "default_scheduler" in payload
    assert "quantum_scheduler" in payload

    for run in payload["quantum_scheduler"] + payload["default_scheduler"]:
        assert len(run["assignment"]) == 10
        assert "resource_imbalance_pct" in run
        assert "cross_node_traffic_mbps" in run
        assert run["fallback_batches"] == 0

    for run in payload["quantum_scheduler"]:
        assert isinstance(run["qaoa_energy_trajectories"], list)


@pytest.mark.parametrize("bad", ["0", "-3", "two"])
def test_iterations_must_be_a_positive_integer(bad):
    with pytest.raises(SystemExit):
        benchmark.main(["--iterations", bad])


def test_positive_int_accepts_one():
    assert benchmark.positive_int("1") == 1


def test_energy_recorder_groups_energies_per_batch():
    recorder = benchmark.EnergyRecorder()
    recorder.start_batch()
    recorder(1, None, 10.0, {})
    recorder(2, None, 8.5, {})
    recorder.start_batch()
    recorder(1, None, 7.0, {})

    assert recorder.trajectories() == [[10.0, 8.5], [7.0]]

    recorder.reset()
    assert recorder.trajectories() == []


def test_energy_recorder_trajectories_are_copies():
    recorder = benchmark.EnergyRecorder()
    recorder.start_batch()
    recorder(1, None, 1.0, {})
    snapshot = recorder.trajectories()
    recorder(2, None, 2.0, {})
    assert snapshot == [[1.0]]


def test_solve_quantum_batch_reports_fallback_when_solver_fails():
    class BrokenOptimizer:
        def solve(self, qp):
            raise RuntimeError("simulator exploded")

    batch = list(workload.PODS[:3])
    assignment, used_fallback = benchmark._solve_quantum_batch(BrokenOptimizer(), batch, _fresh_nodes())

    assert used_fallback is True
    assert set(assignment) == {p.name for p in batch}


def test_compute_exact_optimum_matches_brute_force():
    pods = list(workload.PODS[:3])
    nodes = _fresh_nodes()
    _, expected = benchmark.brute_force_optimum(pods, nodes, workload.TRAFFIC)
    assert benchmark.compute_exact_optimum(pods, nodes) == expected


def test_run_single_iteration_counts_fallbacks(monkeypatch):
    calls = iter([False, True, True, False])

    def fake_solve(optimizer, batch, nodes, recorder=None):
        return benchmark._solve_default_batch(batch, nodes), next(calls)
    monkeypatch.setattr(benchmark, "_solve_quantum_batch", fake_solve)

    assignment, traffic, fallbacks = benchmark._run_single_iteration("quantum", None, _fresh_nodes())

    assert len(assignment) == 10
    assert traffic >= 0
    assert fallbacks == 2


def test_run_single_iteration_default_has_no_fallbacks():
    _, _, fallbacks = benchmark._run_single_iteration("default", None, _fresh_nodes())
    assert fallbacks == 0
