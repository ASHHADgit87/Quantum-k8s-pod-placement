"""Default vs quantum scheduler benchmark engine."""
import argparse
import json
import logging
import sys
import time
from pathlib import Path
from src import cluster_metrics, workload
from src.qubo_builder import brute_force_optimum
from src.quantum_scheduler import sort_pods_by_traffic, setup_qaoa_optimizer, solve_batch, update_budgets, BATCH_SIZE

logger = logging.getLogger(__name__)
RESULTS_DIR = Path("results")


class EnergyRecorder:
    """QAOA callback that groups the optimizer's energy estimates per batch.

    QAOA calls it as ``(eval_count, parameters, energy, metadata)`` after each
    classical optimizer step; only ``energy`` is kept.
    """

    def __init__(self):
        self._batches: list[list[float]] = []

    def start_batch(self) -> None:
        self._batches.append([])

    def reset(self) -> None:
        self._batches = []

    def __call__(self, _eval_count, _parameters, energy, _metadata) -> None:
        if not self._batches:
            self.start_batch()
        self._batches[-1].append(float(energy))

    def trajectories(self) -> list[list[float]]:
        """Copy of the recorded energies, one list per batch."""
        return [list(batch) for batch in self._batches]


def calculate_resource_imbalance(nodes):
    """Calculates percentage CPU/memory load variance across active nodes."""
    cpu_usages = [n.used_cpu_m / n.allocatable_cpu_m for n in nodes if n.allocatable_cpu_m > 0]
    if not cpu_usages:
        return 0.0
    mean_load = sum(cpu_usages) / len(cpu_usages)
    variance = sum((load - mean_load) ** 2 for load in cpu_usages) / len(cpu_usages)
    return round(variance * 100, 2)


def compute_exact_optimum(pods, nodes) -> float:
    """Exact minimum cross-node traffic (Mbps) for placing all pods at once."""
    _, cost = brute_force_optimum(list(pods), nodes, workload.TRAFFIC)
    return cost


def _solve_quantum_batch(optimizer, batch, nodes, recorder=None):
    """Returns (assignment, used_fallback). Fallback is recorded, never hidden."""
    if recorder is not None:
        recorder.start_batch()
    assign_batch, _, used_fallback = solve_batch(optimizer, batch, nodes)
    if assign_batch:
        return assign_batch, used_fallback
    logger.error("Batch %s does not fit the remaining capacity; placing round-robin (over capacity)",
                 [p.name for p in batch])
    return _solve_default_batch(batch, nodes), True


def _solve_default_batch(batch, nodes):
    return {pod.name: nodes[idx % len(nodes)].name for idx, pod in enumerate(batch)}


def _run_single_iteration(mode, optimizer, nodes, recorder=None):
    """Returns (assignment, cross-node traffic in Mbps, fallback batches, final node budgets).

    Node usage is carried forward between batches (a new list each time, the
    input is never mutated) so later batches see what earlier ones consumed and
    the resource-imbalance metric reflects the real placement.
    """
    sorted_pods = sort_pods_by_traffic()
    batches = [sorted_pods[j:j + BATCH_SIZE] for j in range(0, len(sorted_pods), BATCH_SIZE)]
    assignment = {}
    fallback_batches = 0

    for batch in batches:
        if mode == "quantum":
            batch_assign, used_fallback = _solve_quantum_batch(optimizer, batch, nodes, recorder)
            fallback_batches += int(used_fallback)
        else:
            batch_assign = _solve_default_batch(batch, nodes)
        assignment.update(batch_assign)
        nodes = update_budgets(nodes, batch, batch_assign)

    cross_node_traffic_mbps = sum(
        edge.mbps for edge in workload.TRAFFIC
        if assignment.get(edge.source) != assignment.get(edge.target)
    )

    return assignment, cross_node_traffic_mbps, fallback_batches, nodes


def fresh_nodes():
    """The simulated three-node cluster every iteration starts from."""
    return [
        cluster_metrics.NodeBudget("agent-0", "node-alpha", True, 4000, 8589934592, 0, 0),
        cluster_metrics.NodeBudget("agent-1", "node-beta", True, 4000, 8589934592, 0, 0),
        cluster_metrics.NodeBudget("agent-2", "node-gamma", True, 4000, 8589934592, 0, 0),
    ]


def simulate_scheduler_run(mode: str, iterations: int):
    """Executes benchmark iterations for either 'default' or 'quantum' mode."""
    results = []
    recorder = EnergyRecorder() if mode == "quantum" else None
    # Setup runs fast if mocked, or initializes real QAOA in production
    optimizer = setup_qaoa_optimizer(callback=recorder)

    for i in range(iterations):
        if recorder is not None:
            recorder.reset()
        start_time = time.perf_counter()
        nodes = fresh_nodes()

        assignment, traffic_mbps, fallback_batches, nodes = _run_single_iteration(mode, optimizer, nodes, recorder)
        duration = time.perf_counter() - start_time
        imbalance = calculate_resource_imbalance(nodes)

        run = {
            "iteration": i + 1,
            "mode": mode,
            "duration_sec": round(duration, 4),
            "resource_imbalance_pct": imbalance,
            "cross_node_traffic_mbps": traffic_mbps,
            "fallback_batches": fallback_batches,
            "assignment": assignment,
        }
        if recorder is not None:
            run["qaoa_energy_trajectories"] = recorder.trajectories()
        results.append(run)

    return results


def positive_int(text: str) -> int:
    """argparse type: an integer >= 1."""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=positive_int, default=20, help="Number of test iterations")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Starting benchmarking: %d iterations per scheduler", args.iterations)

    default_runs = simulate_scheduler_run("default", args.iterations)
    quantum_runs = simulate_scheduler_run("quantum", args.iterations)

    logger.info("Computing exact optimum over all %d pods", len(workload.PODS))
    exact_optimum = compute_exact_optimum(sort_pods_by_traffic(), fresh_nodes())

    benchmark_payload = {
        "metadata": {
            "iterations": args.iterations,
            "timestamp": time.time(),
            "exact_optimum_objective": exact_optimum,
        },
        "default_scheduler": default_runs,
        "quantum_scheduler": quantum_runs,
    }

    # SonarCloud fix: Use standard open() context manager instead of write_text()
    target_file = RESULTS_DIR / "benchmark_data.json"
    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(benchmark_payload, f, indent=2)

    logger.info("Benchmark complete. Data written to %s", target_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
