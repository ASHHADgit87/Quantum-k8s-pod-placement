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
    
    eval_same = qp.objective.evaluate({"x_frontend_alpha": 1, "x_backend_alpha": 1})
    ref_same = reference_cost({"frontend": "alpha", "backend": "alpha"}, traffic)
    assert eval_same == ref_same == 0
    
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
    
    assert best_assign["p1"] != best_assign["p2"]
    assert best_cost == 100


import pytest
from qiskit_optimization.converters import QuadraticProgramToQubo
from src.cluster_metrics import NodeBudget
from src.qubo_builder import assignment_from_x, fits_capacity, remaining_capacity_percent


def _budget(name, used_cpu_m=0, used_mem=0):
    return NodeBudget(name, name, True, 4000, 8589934592, used_cpu_m, used_mem)


def test_assignment_constraints_require_exactly_one_node():
    """Regression: constraints used to be '<= 0', which made every QAOA sample infeasible."""
    pods = [PodDemand("a", 20, 20), PodDemand("b", 20, 20)]
    nodes = [Node("n1"), Node("n2")]
    qp = build_qubo(pods, nodes, [])

    assign = {c.name: c for c in qp.linear_constraints if c.name.startswith("assign_")}
    assert set(assign) == {"assign_a", "assign_b"}
    for constraint in assign.values():
        assert constraint.sense.name == "EQ"
        assert constraint.rhs == 1

    assert qp.is_feasible([1, 0, 0, 1])
    assert not qp.is_feasible([0, 0, 0, 1])
    assert not qp.is_feasible([1, 1, 0, 1])


def test_capacity_constraints_use_remaining_capacity():
    pods = [PodDemand("a", 30, 10)]
    nodes = [_budget("n1", used_cpu_m=3000), _budget("n2")]
    qp = build_qubo(pods, nodes, [])

    cpu = {c.name: c for c in qp.linear_constraints if c.name.startswith("cpu_")}
    assert cpu["cpu_n1"].sense.name == "LE"
    assert cpu["cpu_n1"].rhs == pytest.approx(25.0)
    assert cpu["cpu_n2"].rhs == pytest.approx(100.0)
    assert not qp.is_feasible([1, 0]), "30% does not fit on a node with 25% free"
    assert qp.is_feasible([0, 1])


def test_reduced_program_has_no_capacity_constraints_and_nine_qubits():
    pods = [PodDemand(f"p{i}", 20, 20) for i in range(3)]
    nodes = [Node("n1"), Node("n2"), Node("n3")]
    full = build_qubo(pods, nodes, [])
    reduced = build_qubo(pods, nodes, [], with_capacity=False)

    assert {c.name for c in reduced.linear_constraints} == {"assign_p0", "assign_p1", "assign_p2"}
    assert len(full.linear_constraints) == 3 + 2 * 3
    assert QuadraticProgramToQubo().convert(reduced).get_num_vars() == 9
    assert QuadraticProgramToQubo().convert(full).get_num_vars() > 9


def test_remaining_capacity_percent():
    assert remaining_capacity_percent(Node("bare")) == (100.0, 100.0)
    cpu, mem = remaining_capacity_percent(_budget("n", used_cpu_m=1000, used_mem=8589934592 // 2))
    assert (cpu, mem) == (pytest.approx(75.0), pytest.approx(50.0))


def test_assignment_from_x_decodes_and_rejects():
    pods = [PodDemand("a", 1, 1), PodDemand("b", 1, 1)]
    nodes = [Node("n1"), Node("n2")]
    assert assignment_from_x(pods, nodes, [1, 0, 0, 1]) == {"a": "n1", "b": "n2"}
    assert assignment_from_x(pods, nodes, [0.9, 0.1, 0.0, 1.0]) == {"a": "n1", "b": "n2"}
    assert assignment_from_x(pods, nodes, [0, 0, 0, 1]) is None
    assert assignment_from_x(pods, nodes, [1, 1, 0, 1]) is None


def test_brute_force_respects_remaining_capacity():
    pods = [PodDemand("a", 30, 10), PodDemand("b", 30, 10)]
    nodes = [_budget("n1", used_cpu_m=3000), _budget("n2")]
    assignment, cost = brute_force_optimum(pods, nodes, [("a", "b", 100)])
    assert assignment == {"a": "n2", "b": "n2"}
    assert cost == 0
    assert fits_capacity(pods, nodes, assignment)
    assert not fits_capacity(pods, nodes, {"a": "n1", "b": "n1"})


def test_brute_force_returns_none_when_nothing_fits():
    pods = [PodDemand("huge", 150, 10)]
    assert brute_force_optimum(pods, [Node("n1")], []) == (None, float("inf"))


def test_fits_capacity_accepts_exactly_full_node():
    pods = [PodDemand("a", 60, 50), PodDemand("b", 40, 50)]
    nodes = [Node("n1")]
    assert fits_capacity(pods, nodes, {"a": "n1", "b": "n1"})
    assert not fits_capacity([PodDemand("c", 101, 1)], nodes, {"c": "n1"})
