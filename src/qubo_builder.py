"""QUBO formulation for Quantum-Assisted Kubernetes Pod Placement."""
import itertools
from qiskit_optimization import QuadraticProgram

def _add_variables(qp, pods, nodes):
    for pod in pods:
        for node in nodes:
            qp.binary_var(f"x_{pod.name}_{node.name}")

def _add_assignment_constraints(qp, pods, nodes):
    for pod in pods:
        qp.linear_constraint(
            linear={f"x_{pod.name}_{node.name}": 1 for node in nodes},
            name=f"assign_{pod.name}"
        )

def _add_capacity_constraints(qp, pods, nodes):
    for node in nodes:
        qp.linear_constraint(
            linear={f"x_{pod.name}_{node.name}": pod.cpu_percent for pod in pods},
            name=f"cpu_{node.name}"
        )
        qp.linear_constraint(
            linear={f"x_{pod.name}_{node.name}": pod.memory_percent for pod in pods},
            name=f"mem_{node.name}"
        )

def _build_objective(pods, nodes, traffic):
    pod_names = {p.name for p in pods}
    quadratic_obj = {}
    for edge in traffic:
        p1 = edge[0] if isinstance(edge, tuple) else edge.source
        p2 = edge[1] if isinstance(edge, tuple) else edge.target
        mbps = edge[2] if isinstance(edge, tuple) else edge.mbps
        
        if p1 in pod_names and p2 in pod_names:
            for n1 in nodes:
                for n2 in nodes:
                    if n1.name != n2.name:
                        var1, var2 = f"x_{p1}_{n1.name}", f"x_{p2}_{n2.name}"
                        quadratic_obj[(var1, var2)] = quadratic_obj.get((var1, var2), 0) + mbps
    return quadratic_obj

def build_qubo(pods, nodes, traffic):
    """Builds the QuadraticProgram with hard linear constraints."""
    qp = QuadraticProgram()
    _add_variables(qp, pods, nodes)
    _add_assignment_constraints(qp, pods, nodes)
    _add_capacity_constraints(qp, pods, nodes)
    qp.minimize(quadratic=_build_objective(pods, nodes, traffic))
    return qp

def reference_cost(assignment, traffic):
    """Independent reference cost function to verify QUBO."""
    cost = 0
    for edge in traffic:
        p1 = edge[0] if isinstance(edge, tuple) else edge.source
        p2 = edge[1] if isinstance(edge, tuple) else edge.target
        mbps = edge[2] if isinstance(edge, tuple) else edge.mbps
        
        if p1 in assignment and p2 in assignment:
            if assignment[p1] != assignment[p2]:
                cost += mbps
    return cost

def brute_force_optimum(pods, nodes, traffic):
    """Finds exact feasible optimum for small batches."""
    best_cost, best_assign = float('inf'), None
    for combo in itertools.product(nodes, repeat=len(pods)):
        assignment = {pods[i].name: combo[i].name for i in range(len(pods))}
        
        feasible = True
        for node in nodes:
            cpu_used = sum(pods[i].cpu_percent for i in range(len(pods)) if combo[i].name == node.name)
            mem_used = sum(pods[i].memory_percent for i in range(len(pods)) if combo[i].name == node.name)
            if cpu_used > 100 or mem_used > 100:
                feasible = False
                break
                
        if feasible:
            cost = reference_cost(assignment, traffic)
            if cost < best_cost:
                best_cost, best_assign = cost, assignment
                
    return best_assign, best_cost
