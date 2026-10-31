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
from src.qubo_builder import build_qubo, brute_force_optimum

logger = logging.getLogger(__name__)

BATCH_SIZE = 3

def sort_pods_by_traffic():
    """Order pods by heaviest total simulated traffic first."""
    pod_traffic = {pod.name: workload.total_traffic(pod.name) for pod in workload.PODS}
    sorted_names = sorted(pod_traffic.keys(), key=lambda n: pod_traffic[n], reverse=True)
    name_to_pod = {pod.name: pod for pod in workload.PODS}
    return [name_to_pod[name] for name in sorted_names]

def setup_qaoa_optimizer():
    """Configures QAOA with an Aer simulator Sampler."""
    sampler = StatevectorSampler()
    qaoa = QAOA(sampler=sampler, optimizer=COBYLA(maxiter=50))
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

def _solve_batch(optimizer, qp, batch, available_nodes):
    batch_names = {p.name for p in batch}
    try:
        result = optimizer.solve(qp)
        if result.status.name == "SUCCESS":
            assign = {}
            for var_name, val in result.variables_dict.items():
                if math.isclose(val, 1.0, abs_tol=1e-5):
                    _, pod_name, node_name = var_name.split("_")
                    if pod_name in batch_names:
                        assign[pod_name] = node_name
            # Ensure every pod in the batch was assigned a node
            if batch_names.issubset(assign.keys()):
                return assign, result.fval
    except Exception as e:
        logger.warning("QAOA failed (%s), falling back to classical greedy", e)
    
    return brute_force_optimum(batch, available_nodes, workload.TRAFFIC)

def _update_budgets(available_nodes, batch, assign):
    updated = list(available_nodes)
    for pod in batch:
        node_name = assign[pod.name]
        for idx, n in enumerate(updated):
            if n.name == node_name:
                updated[idx] = cluster_metrics.NodeBudget(
                    n.name, n.alias, n.schedulable, n.allocatable_cpu_m, n.allocatable_memory_bytes,
                    n.used_cpu_m + int(4000 * pod.cpu_percent / 100), 
                    n.used_memory_bytes + int(8589934592 * pod.memory_percent / 100)
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
    final_assignment = {}
    
    for b_idx, batch in enumerate(batches):
        logger.info("Solving batch %d/%d (%d pods)", b_idx + 1, len(batches), len(batch))
        qp = build_qubo(batch, available_nodes, workload.TRAFFIC)
        assign, cost = _solve_batch(optimizer, qp, batch, available_nodes)
        
        final_assignment.update(assign)
        total_cost += cost
        available_nodes = _update_budgets(available_nodes, batch, assign)
    
    logger.info("Final placement achieved with objective value: %s", total_cost)
    
    if args.dry_run:
        logger.info("Dry-run complete. Placements: %s", final_assignment)
        return 0
        
    if not args.offline:
        for pod_name, node_name in final_assignment.items():
            bind_pod_to_node(api, pod_name, node_name)
            
    return 0

if __name__ == "__main__":
    sys.exit(main())
