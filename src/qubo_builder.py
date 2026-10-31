"""QUBO formulation for Quantum-Assisted Kubernetes Pod Placement."""
import itertools
from qiskit_optimization import QuadraticProgram

def build_qubo(pods, nodes, traffic):
    """Builds the QuadraticProgram with hard linear constraints."""
    qp = QuadraticProgram()
    
    # Variables: x_i_j = 1 if pod i is on node j
    for pod in pods:
        for node in nodes:
            qp.binary_var(f"x_{pod.name}_{node.name}")
            
    # Constraint 1: Each pod placed exactly once (Linear Equality)
    for pod in pods:
        qp.linear_constraint(
            linear={f"x_{pod.name}_{node.name}": 1 for node in nodes},
            sense="==",
            rhs=1,
            name=f"assign_{pod.name}"
        )
        
    # Constraint 2: Node capacity not exceeded (Linear Inequality)
    for node in nodes:
        qp.linear_constraint(
            linear={f"x_{pod.name}_{node.name}": pod.cpu_percent for pod in pods},
            sense="<=",
            rhs=100,
            name=f"cpu_{node.name}"
        )
        qp.linear_constraint(
            linear={f"x_{pod.name}_{node.name}": pod.memory_percent for pod in pods},
            sense="<=",
            rhs=100,
            name=f"mem_{node.name}"
        )
        
    # Objective: Minimize cross-node traffic cost
    quadratic_obj = {}
    for (p1, p2, mbps) in traffic:
        for n1 in nodes:
            for n2 in nodes:
                if n1.name != n2.name:
                    var1, var2 = f"x_{p1}_{n1.name}", f"x_{p2}_{n2.name}"
                    quadratic_obj[(var1, var2)] = quadratic_obj.get((var1, var2), 0) + mbps
                    
    qp.minimize(quadratic=quadratic_obj)
    return qp

def reference_cost(assignment, traffic):
    """Independent reference cost function to verify QUBO."""
    cost = 0
    for (p1, p2, mbps) in traffic:
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
