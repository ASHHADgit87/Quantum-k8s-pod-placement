"""QUBO formulation for Quantum-Assisted Kubernetes Pod Placement.

The full model (``build_qubo``) has one binary variable per (pod, node) pair,
an equality constraint per pod (placed on exactly one node) and an inequality
constraint per node (CPU and memory not exceeded, measured against the
capacity that is still free on that node).

Converting the inequality constraints to a QUBO needs about seven slack
qubits each, so a 3-pod / 3-node batch grows from 9 to 51 qubits, far beyond
a laptop simulator. ``build_qubo(..., with_capacity=False)`` therefore gives
the 9-qubit program QAOA actually samples, and the scheduler keeps the
lowest-energy sample that is feasible for the full model.
"""
import itertools

from qiskit_optimization import QuadraticProgram

FULL_CAPACITY_PERCENT = 100.0
# Same spirit as QuadraticProgram.is_feasible: an exactly-full node is feasible.
CAPACITY_TOLERANCE = 1e-6


def remaining_capacity_percent(node) -> tuple[float, float]:
    """(CPU %, memory %) still free on ``node``.

    Nodes that only carry a name (as in unit tests) are treated as empty.
    """
    alloc_cpu = getattr(node, "allocatable_cpu_m", 0)
    alloc_mem = getattr(node, "allocatable_memory_bytes", 0)
    cpu = FULL_CAPACITY_PERCENT * (1 - getattr(node, "used_cpu_m", 0) / alloc_cpu) if alloc_cpu else FULL_CAPACITY_PERCENT
    mem = FULL_CAPACITY_PERCENT * (1 - getattr(node, "used_memory_bytes", 0) / alloc_mem) if alloc_mem else FULL_CAPACITY_PERCENT
    return cpu, mem


def variable_name(pod, node) -> str:
    return f"x_{pod.name}_{node.name}"


def _add_variables(qp, pods, nodes):
    for pod in pods:
        for node in nodes:
            qp.binary_var(variable_name(pod, node))


def _add_assignment_constraints(qp, pods, nodes):
    for pod in pods:
        qp.linear_constraint(
            linear={variable_name(pod, node): 1 for node in nodes},
            sense="==",
            rhs=1,
            name=f"assign_{pod.name}",
        )


def _add_capacity_constraints(qp, pods, nodes):
    for node in nodes:
        cpu_free, mem_free = remaining_capacity_percent(node)
        qp.linear_constraint(
            linear={variable_name(pod, node): pod.cpu_percent for pod in pods},
            sense="<=",
            rhs=cpu_free,
            name=f"cpu_{node.name}",
        )
        qp.linear_constraint(
            linear={variable_name(pod, node): pod.memory_percent for pod in pods},
            sense="<=",
            rhs=mem_free,
            name=f"mem_{node.name}",
        )


def _edge(edge):
    """(source, target, mbps) from either a TrafficEdge or a plain tuple."""
    if isinstance(edge, tuple):
        return edge[0], edge[1], edge[2]
    return edge.source, edge.target, edge.mbps


def _build_objective(pods, nodes, traffic):
    pod_names = {p.name for p in pods}
    quadratic_obj = {}
    for edge in traffic:
        p1, p2, mbps = _edge(edge)
        if p1 not in pod_names or p2 not in pod_names:
            continue
        for n1 in nodes:
            for n2 in nodes:
                if n1.name != n2.name:
                    key = (f"x_{p1}_{n1.name}", f"x_{p2}_{n2.name}")
                    quadratic_obj[key] = quadratic_obj.get(key, 0) + mbps
    return quadratic_obj


def build_qubo(pods, nodes, traffic, *, with_capacity: bool = True) -> QuadraticProgram:
    """Builds the QuadraticProgram with hard linear constraints.

    ``with_capacity=False`` omits the node-capacity inequalities (see the
    module docstring for why QAOA samples that reduced program).
    """
    qp = QuadraticProgram()
    _add_variables(qp, pods, nodes)
    _add_assignment_constraints(qp, pods, nodes)
    if with_capacity:
        _add_capacity_constraints(qp, pods, nodes)
    qp.minimize(quadratic=_build_objective(pods, nodes, traffic))
    return qp


def assignment_from_x(pods, nodes, x) -> dict | None:
    """Decode a solution vector (variable order = pods x nodes) into {pod: node}.

    Returns None when any pod is not assigned to exactly one node.
    """
    assignment = {}
    for i, pod in enumerate(pods):
        chosen = [node.name for j, node in enumerate(nodes) if x[i * len(nodes) + j] > 0.5]
        if len(chosen) != 1:
            return None
        assignment[pod.name] = chosen[0]
    return assignment


def reference_cost(assignment, traffic):
    """Independent reference cost function to verify QUBO."""
    cost = 0
    for edge in traffic:
        p1, p2, mbps = _edge(edge)
        if p1 in assignment and p2 in assignment and assignment[p1] != assignment[p2]:
            cost += mbps
    return cost


def fits_capacity(pods, nodes, assignment) -> bool:
    """True when every node's free CPU and memory cover the pods assigned to it."""
    for node in nodes:
        cpu_free, mem_free = remaining_capacity_percent(node)
        placed = [pod for pod in pods if assignment.get(pod.name) == node.name]
        cpu_over = sum(p.cpu_percent for p in placed) > cpu_free + CAPACITY_TOLERANCE
        mem_over = sum(p.memory_percent for p in placed) > mem_free + CAPACITY_TOLERANCE
        if cpu_over or mem_over:
            return False
    return True


def brute_force_optimum(pods, nodes, traffic):
    """Finds exact feasible optimum for small batches; (None, inf) if none fits."""
    best_cost, best_assign = float("inf"), None
    for combo in itertools.product(nodes, repeat=len(pods)):
        assignment = {pods[i].name: combo[i].name for i in range(len(pods))}
        if not fits_capacity(pods, nodes, assignment):
            continue
        cost = reference_cost(assignment, traffic)
        if cost < best_cost:
            best_cost, best_assign = cost, assignment
    return best_assign, best_cost
