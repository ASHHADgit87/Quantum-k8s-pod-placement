"""Manifest generator.

Writes the same 10 workload pods twice:
- manifests/test-pods.yaml          no schedulerName: kube-scheduler places them
- manifests/test-pods-quantum.yaml  schedulerName: quantum-scheduler, so they
                                    stay Pending until our scheduler binds them

Each pod's requests are its share (from src/workload.py) of the per-node
budget read from the live cluster, or of a fixed budget with --offline.

    python -m src.generate_manifests
    python -m src.generate_manifests --offline
"""
import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from src import cluster_metrics
from src.cluster_metrics import ALIAS_LABEL, CLUSTER_CONTEXT, MEBIBYTE, NodeBudget
from src.workload import (
    NAMESPACE,
    PODS,
    QUANTUM_SCHEDULER_NAME,
    TRAFFIC_ANNOTATION,
    WORKLOAD_LABEL_KEY,
    WORKLOAD_LABEL_VALUE,
    PodDemand,
    traffic_peers,
)

DEFAULT_OUTPUT_DIR = Path("manifests")
DEFAULT_MANIFEST = "test-pods.yaml"
QUANTUM_MANIFEST = "test-pods-quantum.yaml"
POD_IMAGE = "rancher/mirrored-pause:3.6"
PERCENT = 100
MIN_BUDGET_CPU_M = 100
MIN_BUDGET_MEMORY_BYTES = 100 * MEBIBYTE


@dataclass(frozen=True)
class PerNodeBudget:
    """The capacity one worker node offers the workload (what 100% means)."""

    cpu_m: int
    memory_bytes: int


OFFLINE_BUDGET = PerNodeBudget(cpu_m=4000, memory_bytes=8 * 1024**3)


def per_node_budget(budgets: Sequence[NodeBudget]) -> PerNodeBudget:
    """The smallest free capacity across schedulable workers, so a pod sized
    against it fits on any of them."""
    usable = [b for b in budgets if b.schedulable]
    if not usable:
        raise ValueError(
            f"no schedulable worker nodes with a {ALIAS_LABEL} label were found"
        )
    budget = PerNodeBudget(
        cpu_m=min(b.free_cpu_m for b in usable),
        memory_bytes=min(b.free_memory_bytes for b in usable),
    )
    if budget.cpu_m < MIN_BUDGET_CPU_M or budget.memory_bytes < MIN_BUDGET_MEMORY_BYTES:
        raise ValueError("a worker node has too little free capacity for the workload")
    return budget


def _scaled_requests(pod: PodDemand, budget: PerNodeBudget) -> dict[str, str]:
    cpu_m = budget.cpu_m * pod.cpu_percent // PERCENT
    memory_mib = budget.memory_bytes * pod.memory_percent // PERCENT // MEBIBYTE
    return {"cpu": f"{cpu_m}m", "memory": f"{memory_mib}Mi"}


def _workers_only_affinity() -> dict:
    """Only nodes with a cep-alias label: keeps the default scheduler on the
    same 3 workers the quantum scheduler places onto (fair comparison)."""
    return {
        "nodeAffinity": {
            "requiredDuringSchedulingIgnoredDuringExecution": {
                "nodeSelectorTerms": [
                    {"matchExpressions": [{"key": ALIAS_LABEL, "operator": "Exists"}]}
                ]
            }
        }
    }


def _build_pod(pod: PodDemand, budget: PerNodeBudget, scheduler_name: str | None) -> dict:
    spec = {
        "affinity": _workers_only_affinity(),
        "terminationGracePeriodSeconds": 0,
        "containers": [
            {
                "name": "app",
                "image": POD_IMAGE,
                "resources": {"requests": _scaled_requests(pod, budget)},
            }
        ],
    }
    if scheduler_name is not None:
        spec = {"schedulerName": scheduler_name, **spec}
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod.name,
            "namespace": NAMESPACE,
            "labels": {WORKLOAD_LABEL_KEY: WORKLOAD_LABEL_VALUE},
            "annotations": {
                TRAFFIC_ANNOTATION: json.dumps(dict(traffic_peers(pod.name)), sort_keys=True)
            },
        },
        "spec": spec,
    }


def build_documents(budget: PerNodeBudget, scheduler_name: str | None) -> list[dict]:
    """The Namespace document followed by one Pod document per workload pod."""
    namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}}
    return [namespace] + [_build_pod(pod, budget, scheduler_name) for pod in PODS]


def write_manifests(budget: PerNodeBudget, output_dir: Path) -> tuple[Path, Path]:
    """Write both manifest files; returns (default path, quantum path)."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = (
        (output_dir / DEFAULT_MANIFEST, None),
        (output_dir / QUANTUM_MANIFEST, QUANTUM_SCHEDULER_NAME),
    )
    for path, scheduler_name in targets:
        documents = build_documents(budget, scheduler_name)
        path.write_text(yaml.safe_dump_all(documents, sort_keys=False))
    return targets[0][0], targets[1][0]


def _live_budget(context: str) -> PerNodeBudget:
    api = cluster_metrics.load_api(context)
    return per_node_budget(cluster_metrics.read_node_budgets(api))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--offline",
        action="store_true",
        help="do not contact the cluster; size pods against a fixed 4 CPU / 8 GiB node",
    )
    parser.add_argument("--context", default=CLUSTER_CONTEXT, help="kubeconfig context")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="where to write the YAML"
    )
    args = parser.parse_args(argv)

    try:
        budget = OFFLINE_BUDGET if args.offline else _live_budget(args.context)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: could not read worker capacity: {exc}", file=sys.stderr)
        print("Is the cluster up? Use --offline to generate without one.", file=sys.stderr)
        return 1

    try:
        paths = write_manifests(budget, args.output_dir)
    except OSError as exc:
        print(f"Error: could not write manifests to {args.output_dir}: {exc}", file=sys.stderr)
        return 1
    source = "offline default" if args.offline else f"live cluster ({args.context})"
    print(
        f"Per-node budget from {source}: "
        f"{budget.cpu_m}m CPU, {budget.memory_bytes // MEBIBYTE}Mi memory"
    )
    for path in paths:
        print(f"Wrote {path} ({len(PODS)} pods)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
