"""Result charts + summary for the default vs quantum scheduler benchmark.

Reads results/benchmark_data.json (written by ``python -m src.benchmark``) and
produces exactly four files in the output directory:

- latency_comparison.png: box-plot of scheduling duration per scheduler
- resource_balance.png:   box-plot of resource imbalance per scheduler
- convergence_plot.png:   QAOA energy per optimizer step, one line per batch,
                          taken from the first quantum iteration
- summary.json:           mean/std/min/max per metric, exact-optimum objective
                          and total fallback-batch count

Headless-safe: the Agg backend is selected before pyplot is imported.
"""
import argparse
import json
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (backend must be set first)

RESULTS_DIR = Path("results")
INPUT_FILE = "benchmark_data.json"
LATENCY_PNG = "latency_comparison.png"
BALANCE_PNG = "resource_balance.png"
CONVERGENCE_PNG = "convergence_plot.png"
SUMMARY_JSON = "summary.json"

MODES = ("default_scheduler", "quantum_scheduler")
MODE_LABELS = {"default_scheduler": "kube-scheduler", "quantum_scheduler": "QAOA scheduler"}
# metric key -> axis label
METRICS = {
    "duration_sec": "Scheduling duration (s)",
    "resource_imbalance_pct": "Resource imbalance (%)",
    "cross_node_traffic_mbps": "Cross-node traffic (Mbps)",
}
DECIMALS = 4
FIGURE_SIZE = (7, 4.5)
DPI = 120


class BenchmarkDataError(ValueError):
    """The benchmark payload is missing or malformed."""


def validate_payload(payload: object) -> None:
    """Fail fast with a clear message when the JSON does not look like benchmark output."""
    if not isinstance(payload, Mapping):
        raise BenchmarkDataError("top level must be a JSON object")
    if not isinstance(payload.get("metadata", {}), Mapping):
        raise BenchmarkDataError("'metadata' must be an object")
    for mode in MODES:
        runs = payload.get(mode)
        if not isinstance(runs, list) or not runs:
            raise BenchmarkDataError(f"'{mode}' must be a non-empty list of runs")
        for index, run in enumerate(runs, start=1):
            _validate_run(mode, index, run)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_run(mode: str, index: int, run: object) -> None:
    if not isinstance(run, Mapping):
        raise BenchmarkDataError(f"{mode} run {index} must be an object")
    where = f"{mode} run {index}"
    for metric in METRICS:
        if not _is_number(run.get(metric)):
            raise BenchmarkDataError(f"{where}: '{metric}' must be a number")
    fallbacks = run.get("fallback_batches", 0)
    if not isinstance(fallbacks, int) or isinstance(fallbacks, bool) or fallbacks < 0:
        raise BenchmarkDataError(f"{where}: 'fallback_batches' must be a non-negative integer")
    trajectories = run.get("qaoa_energy_trajectories", [])
    if not isinstance(trajectories, list) or not all(
        isinstance(batch, list) and all(_is_number(e) for e in batch) for batch in trajectories
    ):
        raise BenchmarkDataError(f"{where}: 'qaoa_energy_trajectories' must be a list of number lists")


def load_benchmark(path: Path) -> dict:
    """Read and validate the benchmark JSON file."""
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BenchmarkDataError(f"{path} is not valid UTF-8 JSON: {exc}") from exc
    validate_payload(payload)
    return payload


def metric_stats(values: Sequence[float]) -> dict[str, float]:
    """Mean, population std, min and max, rounded so JSON and console agree."""
    return {
        "mean": round(statistics.fmean(values), DECIMALS),
        "std": round(statistics.pstdev(values), DECIMALS),
        "min": round(min(values), DECIMALS),
        "max": round(max(values), DECIMALS),
    }


def _series(payload: Mapping, mode: str, metric: str) -> list[float]:
    return [float(run[metric]) for run in payload[mode]]


def first_trajectories(payload: Mapping) -> list[list[float]]:
    """Per-batch QAOA energy trajectories from the first quantum iteration."""
    first_run = payload["quantum_scheduler"][0]
    trajectories = first_run.get("qaoa_energy_trajectories", [])
    return [[float(e) for e in batch] for batch in trajectories]


def build_summary(payload: Mapping) -> dict:
    """Pure function: payload -> summary dict (does not modify the payload)."""
    metadata = payload.get("metadata", {})
    return {
        "iterations": metadata.get("iterations", len(payload["quantum_scheduler"])),
        "exact_optimum_objective": metadata.get("exact_optimum_objective"),
        "fallback_batches": sum(int(run.get("fallback_batches", 0)) for run in payload["quantum_scheduler"]),
        "metrics": {
            mode: {metric: metric_stats(_series(payload, mode, metric)) for metric in METRICS}
            for mode in MODES
        },
    }


def plot_boxplot(payload: Mapping, metric: str, title: str, out_path: Path) -> None:
    """Box-plot of one metric across all iterations, one box per scheduler."""
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.boxplot(
        [_series(payload, mode, metric) for mode in MODES],
        tick_labels=[MODE_LABELS[mode] for mode in MODES],
        showmeans=True,
    )
    ax.set_ylabel(METRICS[metric])
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)


def plot_convergence(payload: Mapping, out_path: Path) -> None:
    """QAOA energy vs optimizer step for every batch of the first quantum iteration."""
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    trajectories = first_trajectories(payload)
    for index, energies in enumerate(trajectories, start=1):
        ax.plot(range(1, len(energies) + 1), energies, marker="o", label=f"batch {index}")
    if trajectories:
        ax.legend()
    else:
        ax.text(0.5, 0.5, "no QAOA energy trajectories recorded",
                ha="center", va="center", transform=ax.transAxes)
    ax.set_xlabel("Optimizer step")
    ax.set_ylabel("QAOA energy (expectation value)")
    ax.set_title("QAOA convergence (first iteration)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)


def format_summary_table(summary: Mapping) -> str:
    """Console table; the numbers are the same rounded values stored in summary.json."""
    lines = [
        f"iterations: {summary['iterations']}",
        f"exact_optimum_objective: {summary['exact_optimum_objective']}",
        f"fallback_batches: {summary['fallback_batches']}",
        "",
        f"{'scheduler':<18} {'metric':<26} {'mean':>12} {'std':>12} {'min':>12} {'max':>12}",
    ]
    for mode, metrics in summary["metrics"].items():
        for metric, stats in metrics.items():
            lines.append(
                f"{mode:<18} {metric:<26} {stats['mean']:>12.4f} {stats['std']:>12.4f} "
                f"{stats['min']:>12.4f} {stats['max']:>12.4f}"
            )
    return "\n".join(lines)


def write_outputs(payload: Mapping, output_dir: Path) -> dict:
    """Write the three charts and summary.json; returns the summary."""
    output_dir = output_dir.resolve()
    if output_dir.exists() and not output_dir.is_dir():
        raise BenchmarkDataError(f"output directory {output_dir} is an existing file")
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_boxplot(payload, "duration_sec", "Scheduling latency per iteration", output_dir / LATENCY_PNG)
    plot_boxplot(payload, "resource_imbalance_pct", "Resource balance per iteration", output_dir / BALANCE_PNG)
    plot_convergence(payload, output_dir / CONVERGENCE_PNG)
    summary = build_summary(payload)
    with open(output_dir / SUMMARY_JSON, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=RESULTS_DIR / INPUT_FILE,
                        help="benchmark_data.json produced by src.benchmark")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR,
                        help="where the PNGs and summary.json are written")
    args = parser.parse_args(argv)

    try:
        payload = load_benchmark(args.input.resolve())
        summary = write_outputs(payload, args.output_dir)
    except (OSError, BenchmarkDataError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(format_summary_table(summary))
    print(f"\nWrote {LATENCY_PNG}, {BALANCE_PNG}, {CONVERGENCE_PNG}, {SUMMARY_JSON} to {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
