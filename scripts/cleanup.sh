#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="quantum-cluster"
NAMESPACE="quantum-sched-test"
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
