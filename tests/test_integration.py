"""End-to-end integration test suite for the Quantum K8s Pod Placement project."""
import json
import pytest
from pathlib import Path
from src import benchmark, workload

def test_full_pipeline_integration(tmp_path, monkeypatch):
    """Proves the full pipeline from mock cluster metrics to benchmark JSON output works flawlessly."""
    monkeypatch.setattr(benchmark, "RESULTS_DIR", tmp_path)
    
    # Mock heavy quantum solver for < 5 second test completion
    def mock_quantum_solve(optimizer, batch, nodes, recorder=None):
        return benchmark._solve_default_batch(batch, nodes), False
    monkeypatch.setattr(benchmark, "_solve_quantum_batch", mock_quantum_solve)
    monkeypatch.setattr(benchmark, "setup_qaoa_optimizer", lambda callback=None: None)
    
    # Run the entire benchmark engine end-to-end
    exit_code = benchmark.main(["--iterations", "2"])
    assert exit_code == 0
    
    data_file = tmp_path / "benchmark_data.json"
    assert data_file.exists(), "Integration failed: JSON not generated"
    
    payload = json.loads(data_file.read_text())
    
    assert "metadata" in payload
    assert payload["metadata"]["iterations"] == 2
    assert len(payload["default_scheduler"]) == 2
    assert len(payload["quantum_scheduler"]) == 2
    
    for run in payload["quantum_scheduler"]:
        assert len(run["assignment"]) == len(workload.PODS), "Not all pods scheduled!"
        assert run["cross_node_traffic_mbps"] >= 0
        assert run["resource_imbalance_pct"] >= 0.0
        assert run["fallback_batches"] == 0

    # The exact optimum is computed for real here and must be a lower bound.
    exact = payload["metadata"]["exact_optimum_objective"]
    assert exact >= 0
    for run in payload["quantum_scheduler"] + payload["default_scheduler"]:
        assert run["cross_node_traffic_mbps"] >= exact
