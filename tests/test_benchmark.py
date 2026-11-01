"""Tests for benchmark engine and output data validation."""
import json
from pathlib import Path
from src import benchmark

def test_benchmark_execution_and_json(tmp_path, monkeypatch):
    """Benchmark runner must complete, produce valid JSON, and ensure feasibility."""
    monkeypatch.setattr(benchmark, "RESULTS_DIR", tmp_path)
    
    # Mock heavy quantum solver for < 5 second test completion
    def mock_quantum_solve(*args, **kwargs):
        return benchmark._solve_default_batch(args[1], args[2])
    monkeypatch.setattr(benchmark, "_solve_quantum_batch", mock_quantum_solve)
    monkeypatch.setattr(benchmark, "setup_qaoa_optimizer", lambda: None)
    
    exit_code = benchmark.main(["--iterations", "1"])
    assert exit_code == 0
    
    data_file = tmp_path / "benchmark_data.json"
    assert data_file.exists()
    
    payload = json.loads(data_file.read_text())
    assert "metadata" in payload
    assert "default_scheduler" in payload
    assert "quantum_scheduler" in payload
    
    for run in payload["quantum_scheduler"] + payload["default_scheduler"]:
        assert len(run["assignment"]) == 10
        assert "resource_imbalance_pct" in run
        assert "cross_node_traffic_mbps" in run
