#!/usr/bin/env bash
# scripts/create_issues.sh — idempotent labels (--force), NOT idempotent issues
# (gh doesn't dedupe issues; check `gh issue list` before re-running this).
set -euo pipefail
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
echo "Creating labels and issues in ${REPO}"

# ---------- Labels ----------------------------------------------------------
gh label create infrastructure --color "0E8A16" --description "K3s/k3d/Docker/cluster setup"   --force
gh label create quantum-core   --color "5319E7" --description "QUBO/QAOA/scheduler logic"       --force
gh label create benchmarking   --color "FBCA04" --description "Benchmark + plotting"            --force
gh label create documentation  --color "1D76DB" --description "README + repo housekeeping"      --force

# ---------- Environment ------------------------------------------------------
gh issue create \
  --title "[Infra] Docker + K3s + Python venv on Kali WSL2" \
  --label infrastructure --assignee "@me" \
  --body "$(cat <<'BODY'
## Owner
Ashhadullah — Kali WSL2

## What has to work
- Docker CE installed via the bookworm apt repo (not bullseye — it's unsigned for current Kali)
- WSL2 systemd enabled in /etc/wsl.conf before starting docker/k3s services
- K3s installed with `curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644`
- Python 3.13/3.14 venv (`quantum_env`) with every package from requirements.txt installed and importable

## Acceptance criteria
- [ ] `docker run hello-world` succeeds
- [ ] `kubectl get nodes` (no sudo) shows a Ready control-plane node
- [ ] venv activated, `python -c "import qiskit_algorithms, qiskit_aer, qiskit_optimization, kubernetes"` runs with no error
BODY
)"

gh issue create \
  --title "[Infra] Docker + K3s + Python venv on native Ubuntu" \
  --label infrastructure \
  --body "$(cat <<'BODY'
## Owner
Misbah — native Ubuntu dual boot

## What has to work
- Docker CE installed via Ubuntu's own apt repo (distro codename, not Kali's bookworm workaround)
- No systemd step needed — native Ubuntu already runs systemd
- K3s installed identically to Ashhadullah's machine
- Same Python venv setup, same requirements.txt, same package versions

## Acceptance criteria
- [ ] `docker run hello-world` succeeds
- [ ] `kubectl get nodes` (no sudo) shows a Ready control-plane node
- [ ] venv activated, `python -c "import qiskit_algorithms, qiskit_aer, qiskit_optimization, kubernetes"` runs with no error
- [ ] `python -m pytest -q` passes locally once src/ and tests/ exist (same result as Ashhadullah's machine)
BODY
)"

# ---------- Kubernetes cluster + workload -----------------------------------
gh issue create \
  --title "[Infra] k3d 3-worker cluster, aliased node labels (scripts/create_cluster.sh)" \
  --label infrastructure \
  --body "$(cat <<'BODY'
## Owner
Misbah — infra-k8s branch

## What has to work
An idempotent script that creates a k3d cluster named quantum-cluster with
1 server (control plane) + 3 agents (workers), then labels each agent
cep-alias=node-alpha / node-beta / node-gamma so nothing downstream depends
on Docker's auto-generated container names.

## Acceptance criteria
- [ ] `kubectl get nodes -L cep-alias` shows 1 Ready control-plane + 3 Ready
      workers, each with a distinct cep-alias
- [ ] Script is safe to re-run without erroring or duplicating the cluster
BODY
)"

gh issue create \
  --title "[Infra] Workload table + manifest generator (src/workload.py, src/generate_manifests.py)" \
  --label infrastructure \
  --body "$(cat <<'BODY'
## Owner
Misbah — infra-k8s branch

## What has to work
- src/workload.py: single source of truth — a 10-pod table (CPU/RAM demand)
  plus a simulated inter-pod traffic graph. Nothing else in the project
  hardcodes these numbers a second time.
- src/generate_manifests.py: reads live worker capacity from the cluster and
  writes manifests/test-pods.yaml (no schedulerName — default kube-scheduler
  places these) and manifests/test-pods-quantum.yaml (schedulerName:
  quantum-scheduler — these stay Pending until our scheduler binds them),
  with pod resource requests scaled to the real cluster's per-node budget.

## Acceptance criteria
- [ ] `python -m src.generate_manifests` produces both YAML files, 10 Pod
      documents each, plus a Namespace document
- [ ] `python -m src.generate_manifests --offline` works without a live
      cluster (for quick local testing / CI)
BODY
)"

gh issue create \
  --title "[Infra] Live cluster state reader (src/cluster_metrics.py)" \
  --label infrastructure \
  --body "$(cat <<'BODY'
## Owner
Misbah — infra-k8s branch

## What has to work
Reads real node allocatable capacity via the Kubernetes Python client,
subtracts what other pods on that node are already using so the scheduler
never over-commits, reads the workload pods' actual requests and their
simulated-traffic annotation, and best-effort reads real per-node kubelet
network counters (rx/tx bytes) for the report's Comparative Analysis.

## Acceptance criteria
- [ ] `python -m src.cluster_metrics` prints live node budgets, workload pods
      and network counters against the running k3d cluster
- [ ] Kubernetes CPU/memory quantity strings (250m, 2, 256Mi, 1Gi, etc.)
      parse correctly — covered by a unit test
BODY
)"

# ---------- Quantum core ------------------------------------------------------
gh issue create \
  --title "[Quantum] QUBO formulation + builder (src/qubo_builder.py)" \
  --label quantum-core \
  --body "$(cat <<'BODY'
## Owner
Ashhadullah — quantum-core branch

## What has to work
Converts nodes/pods into integer CPU/memory units, then builds a real
qiskit_optimization.QuadraticProgram per batch of pods, with genuine linear
equality constraints (each pod assigned exactly once) and linear inequality
constraints (node capacity not exceeded) — not squared soft-penalty terms.
Also needs an independent reference cost function and a brute-force exact
optimum for small batches, so the QUBO's correctness can actually be checked
against something, not just assumed.

## Acceptance criteria
- [ ] The QuadraticProgram's objective matches an independently-written cost
      function on random test assignments (near machine precision)
- [ ] The brute-force optimum is always a feasible assignment (capacity
      respected on every node, every pod placed exactly once)
BODY
)"

gh issue create \
  --title "[Quantum] Batched QAOA scheduler + Kubernetes Binding API (src/quantum_scheduler.py)" \
  --label quantum-core \
  --body "$(cat <<'BODY'
## Owner
Ashhadullah — quantum-core branch

## What has to work
Solving all 10 pods in one QUBO needs 30+ qubits before constraint-slack
qubits are even added — too big for a laptop simulator in reasonable time.
Order pods by total simulated traffic (heaviest communicators first, placed
while the cluster is still empty), solve in small batches (default 3 pods =
9 qubits/batch) using QAOA with an Aer simulator sampler, pick the
lowest-cost FEASIBLE sample, and fall back to a classical greedy placement —
explicitly recorded, never hidden — for any batch that has no feasible
sample or exceeds the qubit budget. Bind the final placement to real nodes
via the Kubernetes Binding API (the same mechanism kube-scheduler itself
uses).

## Watch out for
qiskit-aer's SamplerV2 needs an explicit transpiler passed into QAOA's
constructor, or it raises `AerError: unknown instruction: QAOA` — the
ansatz circuit must be transpiled to gates Aer understands before it's run.

## Acceptance criteria
- [ ] `python -m src.quantum_scheduler --offline --dry-run` completes and
      prints a feasible 10-pod assignment with its QUBO objective value
- [ ] Every batch's assignment respects node CPU and memory capacity
- [ ] With `--dry-run` off and pods created with schedulerName:
      quantum-scheduler, they actually get bound to a real node
BODY
)"

# ---------- Benchmarking -------------------------------------------------------
gh issue create \
  --title "[Benchmarking] Default vs quantum scheduler benchmark (src/benchmark.py)" \
  --label benchmarking \
  --body "$(cat <<'BODY'
## Owner
Ashhadullah — quantum-core branch, reviewed by Misbah

## What has to work
N iterations, each creating the SAME pod set twice: once with no
schedulerName (real kube-scheduler binds them — the actual default
scheduler, not a stand-in for it) and once with schedulerName:
quantum-scheduler (our QAOA solve + Binding API binds them). Time both
end-to-end, score both with the SAME metric function: resource imbalance %,
a disclosed/modelled cross-node-vs-same-node latency (state this as a
modelling assumption, not a measurement — k3d nodes share one Docker host,
so real RTT between them is meaningless), and cross-node traffic in Mbps
(this one IS measured, not modelled). Write results/benchmark_data.json
with full run metadata for reproducibility.

## Acceptance criteria
- [ ] `python -m src.benchmark --iterations 20` completes and writes valid JSON
- [ ] Every recorded run is capacity-feasible for BOTH schedulers — never
      silently report an infeasible placement as a result
BODY
)"

gh issue create \
  --title "[Benchmarking] Result charts + summary (src/plot_results.py)" \
  --label benchmarking \
  --body "$(cat <<'BODY'
## Owner
Misbah — infra-k8s branch, since this consumes benchmark.py's output

## What has to work
Headless-safe (Matplotlib Agg backend — WSL2/no-display-safe) box-plots for
latency and resource imbalance across all iterations (not just mean lines —
variance matters and should be visible), a QAOA convergence plot (per-batch
energy trajectory from the first iteration), and results/summary.json
(mean/std per metric, the exact-optimum objective, fallback-batch count).

## Acceptance criteria
- [ ] `python -m src.plot_results` produces exactly: latency_comparison.png,
      resource_balance.png, convergence_plot.png, summary.json
- [ ] Printed console summary table matches summary.json
BODY
)"

gh issue create \
  --title "[Benchmarking] Test suite for everything above" \
  --label benchmarking \
  --body "$(cat <<'BODY'
## Owner
Both — each partner tests the files they own
(Ashhadullah: qubo_builder, quantum_scheduler; Misbah: cluster_metrics,
generate_manifests, plot_results integration)

## What has to work
Unit tests for CPU/memory string parsing, the QUBO-objective-vs-reference-
cost check, the brute-force-optimum feasibility check, an offline QAOA
schedule end-to-end check, and one test that runs benchmark.py + plot_
results.py together against a fake (in-memory) Kubernetes client so the
whole orchestration is checked without needing a live cluster.

## Acceptance criteria
- [ ] `python -m pytest -q` passes on BOTH machines with the same result
BODY
)"

# ---------- Documentation / repo housekeeping ---------------------------------
gh issue create \
  --title "[Docs] README, requirements.txt, branch protection" \
  --label documentation --assignee "@me" \
  --body "$(cat <<'BODY'
## Owner
Ashhadullah — repo owner

## What has to work
- README.md: what the project is, how to run every phase, the Ashhadullah-
  Kali vs Misbah-Ubuntu setup differences in one table.
- requirements.txt: every package pinned to the exact versions both of you
  actually tested against (not loose/unpinned).
- Branch protection on main requiring 1 approving review before merge.

## Acceptance criteria
- [ ] `pip install -r requirements.txt` reproduces the same environment on
      both machines
- [ ] A direct push to main from a non-admin is rejected (branch protection
      verified working)
BODY
)"

echo "Done. Run 'gh issue list' to verify everything landed."
