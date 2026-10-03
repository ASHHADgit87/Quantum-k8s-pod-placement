#!/usr/bin/env bash
# scripts/create_cluster.sh — create the k3d cluster the project runs against:
# 1 server (control plane) + 3 agents (workers), each agent labelled
# cep-alias=node-alpha / node-beta / node-gamma so nothing downstream depends
# on Docker's auto-generated container names.
#
# Idempotent: re-running it never errors or duplicates the cluster — an
# existing cluster is started (if stopped) and re-labelled, not re-created.
# Tear it down with scripts/cleanup.sh --all.
set -euo pipefail

CLUSTER_NAME="quantum-cluster"
AGENT_COUNT=3
ALIASES=(node-alpha node-beta node-gamma)
READY_TIMEOUT="120s"
# Always target the k3d cluster explicitly, never whatever kubectl's current
# context happens to be (e.g. a host-level k3s install).
CONTEXT="k3d-${CLUSTER_NAME}"

for tool in docker k3d kubectl; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "Error: ${tool} is not installed or not on PATH." >&2
    exit 1
  fi
done

if k3d cluster list "${CLUSTER_NAME}" >/dev/null 2>&1; then
  echo "Cluster ${CLUSTER_NAME} already exists — making sure it is running."
  k3d cluster start "${CLUSTER_NAME}"
else
  echo "Creating cluster ${CLUSTER_NAME} (1 server + ${AGENT_COUNT} agents)."
  k3d cluster create "${CLUSTER_NAME}" \
      --servers 1 --agents "${AGENT_COUNT}" \
      --k3s-arg "--disable=traefik@server:0" \
      --wait
fi

# Make sure the kubeconfig has this cluster's context and that plain `kubectl`
# points at it (covers the already-existed path too).
k3d kubeconfig merge "${CLUSTER_NAME}" \
    --kubeconfig-merge-default --kubeconfig-switch-context >/dev/null

# Agents register a moment after the server reports ready — wait until every
# node object exists before waiting on its Ready condition.
expected_nodes=$((AGENT_COUNT + 1))
for _ in $(seq 1 60); do
  current_nodes=$(kubectl --context "${CONTEXT}" get nodes --no-headers 2>/dev/null | wc -l)
  [ "${current_nodes}" -ge "${expected_nodes}" ] && break
  sleep 2
done
kubectl --context "${CONTEXT}" wait --for=condition=Ready nodes --all --timeout="${READY_TIMEOUT}"

for i in "${!ALIASES[@]}"; do
  kubectl --context "${CONTEXT}" label node \
      "k3d-${CLUSTER_NAME}-agent-${i}" "cep-alias=${ALIASES[$i]}" --overwrite
done

kubectl --context "${CONTEXT}" get nodes -L cep-alias
