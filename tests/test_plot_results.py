"""Tests for result charts and summary generation (src/plot_results.py)."""
import json
import statistics
from pathlib import Path

import pytest

from src import plot_results

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
EXPECTED_FILES = {
    "latency_comparison.png",
    "resource_balance.png",
    "convergence_plot.png",
    "summary.json",
}


def _run(iteration, mode, duration, imbalance, traffic, fallback=0, trajectories=None):
    run = {
        "iteration": iteration,
        "mode": mode,
        "duration_sec": duration,
        "resource_imbalance_pct": imbalance,
        "cross_node_traffic_mbps": traffic,
        "fallback_batches": fallback,
        "assignment": {"frontend": "node-alpha"},
    }
    if trajectories is not None:
        run["qaoa_energy_trajectories"] = trajectories
    return run


@pytest.fixture
def payload():
    return {
        "metadata": {"iterations": 3, "timestamp": 1.0, "exact_optimum_objective": 95},
        "default_scheduler": [
            _run(1, "default", 0.01, 2.0, 180),
            _run(2, "default", 0.02, 2.5, 180),
            _run(3, "default", 0.03, 3.0, 180),
        ],
        "quantum_scheduler": [
            _run(1, "quantum", 1.5, 1.0, 120, fallback=1,
                 trajectories=[[10.0, 8.0, 5.0], [7.0, 6.5]]),
            _run(2, "quantum", 1.7, 1.2, 110, fallback=0,
                 trajectories=[[9.0, 8.0], [7.0]]),
            _run(3, "quantum", 1.6, 0.8, 130, fallback=2,
                 trajectories=[[11.0], [8.0]]),
        ],
    }


@pytest.fixture
def input_file(tmp_path, payload):
    path = tmp_path / "benchmark_data.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _main(input_file: Path, out_dir: Path) -> int:
    return plot_results.main(["--input", str(input_file), "--output-dir", str(out_dir)])


def test_main_produces_exactly_four_files(input_file, tmp_path):
    out_dir = tmp_path / "out"
    assert _main(input_file, out_dir) == 0
    assert {p.name for p in out_dir.iterdir()} == EXPECTED_FILES
    for name in EXPECTED_FILES - {"summary.json"}:
        assert (out_dir / name).read_bytes().startswith(PNG_MAGIC)


def test_summary_json_statistics(input_file, tmp_path, payload):
    out_dir = tmp_path / "out"
    _main(input_file, out_dir)
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))

    assert summary["iterations"] == 3
    assert summary["exact_optimum_objective"] == 95
    assert summary["fallback_batches"] == 3

    durations = [r["duration_sec"] for r in payload["quantum_scheduler"]]
    quantum = summary["metrics"]["quantum_scheduler"]["duration_sec"]
    assert quantum["mean"] == round(statistics.fmean(durations), 4)
    assert quantum["std"] == round(statistics.pstdev(durations), 4)
    assert quantum["min"] == min(durations)
    assert quantum["max"] == max(durations)

    default_traffic = summary["metrics"]["default_scheduler"]["cross_node_traffic_mbps"]
    assert default_traffic["mean"] == 180
    assert default_traffic["std"] == 0


def test_console_table_matches_summary(input_file, tmp_path, capsys):
    out_dir = tmp_path / "out"
    _main(input_file, out_dir)
    printed = capsys.readouterr().out
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))

    for mode, metrics in summary["metrics"].items():
        assert mode in printed
        for stats in metrics.values():
            assert f"{stats['mean']:.4f}" in printed
            assert f"{stats['std']:.4f}" in printed
    assert str(summary["fallback_batches"]) in printed
    assert str(summary["exact_optimum_objective"]) in printed


def test_convergence_plot_without_trajectories_still_written(tmp_path, payload):
    for run in payload["quantum_scheduler"]:
        del run["qaoa_energy_trajectories"]
    input_file = tmp_path / "old_format.json"
    input_file.write_text(json.dumps(payload), encoding="utf-8")
    out_dir = tmp_path / "out"

    assert _main(input_file, out_dir) == 0
    assert (out_dir / "convergence_plot.png").read_bytes().startswith(PNG_MAGIC)


def test_missing_input_file_returns_error(tmp_path, capsys):
    exit_code = _main(tmp_path / "nope.json", tmp_path / "out")
    assert exit_code == 1
    assert "Error" in capsys.readouterr().err


@pytest.mark.parametrize(
    "broken",
    [
        {"metadata": {}},
        {"metadata": {}, "default_scheduler": [], "quantum_scheduler": []},
        {"metadata": {}, "default_scheduler": [{"duration_sec": "fast"}],
         "quantum_scheduler": [{"duration_sec": 1.0}]},
        {"metadata": {}, "default_scheduler": [{"duration_sec": 1.0}],
         "quantum_scheduler": [{"resource_imbalance_pct": 1.0}]},
        {"metadata": "not an object", "default_scheduler": [_run(1, "d", 1, 1, 1)],
         "quantum_scheduler": [_run(1, "q", 1, 1, 1)]},
        {"metadata": {}, "default_scheduler": [_run(1, "d", 1, 1, 1)],
         "quantum_scheduler": [_run(1, "q", 1, 1, 1, fallback=-1)]},
        {"metadata": {}, "default_scheduler": [_run(1, "d", 1, 1, 1)],
         "quantum_scheduler": [_run(1, "q", 1, 1, 1, trajectories=[["x"]])]},
        {"metadata": {}, "default_scheduler": [_run(1, "d", 1, 1, 1)],
         "quantum_scheduler": [_run(1, "q", 1, 1, 1, trajectories="nope")]},
    ],
)
def test_malformed_payload_returns_error(tmp_path, capsys, broken):
    input_file = tmp_path / "bad.json"
    input_file.write_text(json.dumps(broken), encoding="utf-8")
    assert _main(input_file, tmp_path / "out") == 1
    assert "Error" in capsys.readouterr().err


def test_invalid_json_returns_error(tmp_path, capsys):
    input_file = tmp_path / "bad.json"
    input_file.write_text("{not json", encoding="utf-8")
    assert _main(input_file, tmp_path / "out") == 1
    assert "Error" in capsys.readouterr().err


def test_metric_stats_single_value():
    stats = plot_results.metric_stats([4.2])
    assert stats == {"mean": 4.2, "std": 0.0, "min": 4.2, "max": 4.2}


def test_first_trajectories_uses_first_quantum_iteration(payload):
    assert plot_results.first_trajectories(payload) == [[10.0, 8.0, 5.0], [7.0, 6.5]]


def test_build_summary_is_pure(payload):
    before = json.dumps(payload, sort_keys=True)
    plot_results.build_summary(payload)
    assert json.dumps(payload, sort_keys=True) == before


def test_non_utf8_input_returns_error(tmp_path, capsys):
    input_file = tmp_path / "latin1.json"
    input_file.write_bytes(b'{"metadata": {}, "x": "caf\xe9"}')
    assert _main(input_file, tmp_path / "out") == 1
    assert "Error" in capsys.readouterr().err


def test_output_dir_that_is_a_file_returns_error(input_file, tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("occupied", encoding="utf-8")
    assert _main(input_file, blocker) == 1
    assert "existing file" in capsys.readouterr().err
