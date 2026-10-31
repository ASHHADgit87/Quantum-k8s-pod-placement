"""Tests for QUBO formulation and builder."""
from collections import namedtuple
from src.qubo_builder import build_qubo, reference_cost, brute_force_optimum
from src.workload import PodDemand

Node = namedtuple("Node", ["name"])

def test_qubo_objective_matches_reference_cost():
    pods = [
        PodDemand("frontend", cpu_percent=20, memory_percent=20),
        PodDemand("backend", cpu_percent=20, memory_percent=20)
    ]
    nodes = [Node("alpha"), Node("beta")]
    traffic = [("frontend", "backend", 50)]
    
    qp = build_qubo(pods, nodes, traffic)
    
    # Simulate both pods on the same node (cross-node traffic = 0)
    eval_same = qp.objective.evaluate({"x_frontend_alpha": 1, "x_backend_alpha": 1})
    ref_same = reference_cost({"frontend": "alpha", "backend": "alpha"}, traffic)
    assert eval_same == ref_same == 0
    
    # Simulate pods on different nodes (cross-node traffic = 50)
    eval_diff = qp.objective.evaluate({"x_frontend_alpha": 1, "x_backend_beta": 1})
    ref_diff = reference_cost({"frontend": "alpha", "backend": "beta"}, traffic)
    assert eval_diff == ref_diff == 50

def test_brute_force_optimum_feasible_and_correct():
    pods = [
        PodDemand("p1", cpu_percent=60, memory_percent=60),
        PodDemand("p2", cpu_percent=60, memory_percent=60)
    ]
    nodes = [Node("n1"), Node("n2")]
    traffic = [("p1", "p2", 100)]
    
    best_assign, best_cost = brute_force_optimum(pods, nodes, traffic)
    
    # Capacity is 100 per node, so 60+60 forces them onto different nodes
    assert best_assign["p1"] != best_assign["p2"]
    assert best_cost == 100  # They incur the 100 Mbps cross-node cost
