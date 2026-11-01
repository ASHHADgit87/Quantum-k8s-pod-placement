"""Batched QAOA scheduler + Kubernetes Binding API."""
import argparse
import logging
import math
import sys
from kubernetes import client

from qiskit_algorithms import QAOA
from qiskit_algorithms.optimizers import COBYLA
from qiskit.primitives import StatevectorSampler

from qiskit_optimization.algorithms import MinimumEigenOptimizer
from src import cluster_metrics, workload
from src.qubo_builder import build_qubo, brute_force_optimum, assignment_from_x

logger = logging.getLogger(__name__)

BATCH_SIZE = 3

def sort_pods_by_traffic():
    """Order pods by heaviest total simulated traffic first."""
    pod_traffic = {pod.name: workload.total_traffic(pod.name) for pod in workload.PODS}
    sorted_names = sorted(pod_traffic.keys(), key=lambda n: pod_traffic[n], reverse=True)
    name_to_pod = {pod.name: pod for pod in workload.PODS}
    return [name_to_pod[name] for name in sorted_names]

def setup_qaoa_optimizer(callback=None):
    """Configures QAOA with a fast-converging Aer simulator Sampler.

    ``callback`` is forwarded to QAOA and receives
    ``(eval_count, parameters, energy, metadata)`` after every optimizer step,
    which is how the benchmark records convergence trajectories.
    """
    sampler = StatevectorSampler()
    # Limited maxiter to ensure fast, responsive benchmarking execution
    qaoa = QAOA(sampler=sampler, optimizer=COBYLA(maxiter=15), callback=callback)
    return MinimumEigenOptimizer(qaoa)

def bind_pod_to_node(api: client.CoreV1Api, pod_name: str, node_name: str, namespace: str = workload.NAMESPACE):
    """Binds a pod to a node using the Kubernetes Binding API."""
    target = client.V1ObjectReference(api_version="v1", kind="Node", name=node_name)
    meta = client.V1ObjectMeta(name=pod_name, namespace=namespace)
    binding = client.V1Binding(target=target, metadata=meta)
    
    try:
        api.create_namespaced_pod_binding(name=pod_name, namespace=namespace, body=binding)
        logger.info("Bound pod %s to node %s", pod_name, node_name)
    except client.ApiException as e:
        logger.exception("Failed to bind %s to %s: %s", pod_name, node_name, e.reason)
        raise

def select_feasible_sample(result, full_qp, batch, available_nodes):
    """Lowest-energy QAOA sample that satisfies the full model, or None.

    QAOA samples the reduced (assignment-only) program; capacity is checked
    here against ``full_qp`` so no slack qubits are needed.
    """
    for sample in sorted(result.samples, key=lambda s: (s.fval, -s.probability)):
        if not full_qp.is_feasible(sample.x):
            continue
        assignment = assignment_from_x(batch, available_nodes, sample.x)
        if assignment is not None:
            return assignment, float(sample.fval)
    return None


def solve_batch(optimizer, batch, available_nodes):
    """Returns (assignment, cost, used_fallback). A fallback is logged, never hidden."""
    batch_names = [p.name for p in batch]
    full_qp = build_qubo(batch, available_nodes, workload.TRAFFIC)
    quantum_qp = build_qubo(batch, available_nodes, workload.TRAFFIC, with_capacity=False)
    try:
        result = optimizer.solve(quantum_qp)
        chosen = select_feasible_sample(result, full_qp, batch, available_nodes)
        if chosen is not None:
            return chosen[0], chosen[1], False
        logger.warning("No feasible QAOA sample for batch %s, falling back to exact classical solve", batch_names)
    except Exception as e:
        logger.warning("QAOA failed (%s), falling back to exact classical solve", e, exc_info=True)

    assign, cost = brute_force_optimum(batch, available_nodes, workload.TRAFFIC)
    return assign, cost, True


def update_budgets(available_nodes, batch, assign):
    """New node list with the batch's CPU/memory usage added; the input is not mutated."""
    updated = list(available_nodes)
    for pod in batch:
        node_name = assign[pod.name]
        for idx, n in enumerate(updated):
            if n.name == node_name:
                updated[idx] = cluster_metrics.NodeBudget(
                    n.name, n.alias, n.schedulable, n.allocatable_cpu_m, n.allocatable_memory_bytes,
                    n.used_cpu_m + int(n.allocatable_cpu_m * pod.cpu_percent / 100),
                    n.used_memory_bytes + int(n.allocatable_memory_bytes * pod.memory_percent / 100)
                )
    return updated

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="Run without live cluster data.")
    parser.add_argument("--dry-run", action="store_true", help="Solve but do not bind pods.")
    parser.add_argument("--context", default=cluster_metrics.CLUSTER_CONTEXT)
    args = parser.parse_args(argv)
    
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    if args.offline:
        from tests.fakes import make_node
        nodes = [make_node(f"agent-{i}", "4", "8Gi", alias=a) for i, a in enumerate(("node-alpha", "node-beta", "node-gamma"))]
        from src.cluster_metrics import NodeBudget
        budgets = [NodeBudget(n.metadata.name, n.metadata.labels["cep-alias"], True, 4000, 8589934592, 0, 0) for n in nodes]
        api = None
    else:
        api = cluster_metrics.load_api(args.context)
        budgets = cluster_metrics.read_node_budgets(api)
    
    available_nodes = [b for b in budgets if b.schedulable]
    sorted_pods = sort_pods_by_traffic()
    batches = [sorted_pods[i:i + BATCH_SIZE] for i in range(0, len(sorted_pods), BATCH_SIZE)]
    optimizer = setup_qaoa_optimizer()
    
    total_cost = 0
    fallback_batches = 0
    final_assignment = {}
    
    for b_idx, batch in enumerate(batches):
        logger.info("Solving batch %d/%d (%d pods)", b_idx + 1, len(batches), len(batch))
        assign, cost, used_fallback = solve_batch(optimizer, batch, available_nodes)
        if assign is None:
            logger.error("Batch %d has no feasible placement on the remaining capacity", b_idx + 1)
            return 1
        if used_fallback:
            fallback_batches += 1

        final_assignment.update(assign)
        total_cost += cost
        available_nodes = update_budgets(available_nodes, batch, assign)
    
    logger.info("Final placement achieved with objective value: %s (%d of %d batches used the classical fallback)",
                total_cost, fallback_batches, len(batches))
    
    if args.dry_run:
        logger.info("Dry-run complete. Placements: %s", final_assignment)
        return 0
        
    if not args.offline:
        for pod_name, node_name in final_assignment.items():
            bind_pod_to_node(api, pod_name, node_name)
            
    return 0

if __name__ == "__main__":
    sys.exit(main())
