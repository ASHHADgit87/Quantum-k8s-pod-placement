#!/usr/bin/env bash
# scripts/cleanup.sh — tear down what the project created. Safe to re-run:
# anything already gone is skipped, not an error.
#
#   ./scripts/cleanup.sh          delete the test pods only (cluster stays up)
#   ./scripts/cleanup.sh --all    delete the whole k3d cluster (nodes and pods)
set -euo pipefail

CLUSTER_NAME="quantum-cluster"
NAMESPACE="quantum-sched-test"
# Always target the k3d cluster explicitly, never whatever kubectl's current
# context happens to be (e.g. a host-level k3s install).
CONTEXT="k3d-${CLUSTER_NAME}"

usage() {
  echo "Usage: $0 [--all]"
  echo "  (no flag)  delete the test pods in namespace ${NAMESPACE}"
  echo "  --all      delete the whole k3d cluster ${CLUSTER_NAME}"
}

cluster_exists() {
  command -v k3d >/dev/null 2>&1 && k3d cluster list "${CLUSTER_NAME}" >/dev/null 2>&1
}

delete_pods() {
  if ! cluster_exists; then
    echo "Cluster ${CLUSTER_NAME} does not exist — no pods to delete."
    return
  fi
  # Deleting the namespace removes every pod inside it.
  kubectl --context "${CONTEXT}" delete namespace "${NAMESPACE}" --ignore-not-found --wait=true
  echo "Test pods removed. Cluster ${CLUSTER_NAME} is still running."
}

delete_cluster() {
  if ! cluster_exists; then
    echo "Cluster ${CLUSTER_NAME} does not exist — nothing to delete."
    return
  fi
  k3d cluster delete "${CLUSTER_NAME}"
  echo "Cluster ${CLUSTER_NAME} deleted. Re-create it with scripts/create_cluster.sh."
}

case "${1:-}" in
  "")        delete_pods ;;
  --all)     delete_cluster ;;
  -h|--help) usage ;;
  *)         usage >&2; exit 1 ;;
esac
