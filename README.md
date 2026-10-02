# Quantum-Assisted Kubernetes Pod Placement — Master Build Roadmap


This is the terminal-to-terminal build plan for the system itself — nothing else. No research-paper phase, no LaTeX, no filler. Every command below is either a Kali WSL2 command, an Ubuntu command, a `git`/`gh` command, or a command that's identical on both machines, and every phase says explicitly, up front, whose job it is.

**Roles for the whole project:**
- **Ashhadullah** — owns the GitHub repo (creates it, invites Misbah, generates all Issues), works on Kali Linux under WSL2, owns the `quantum-core` branch (the QAOA/QUBO scheduler and the benchmark).
- **Misbah** — collaborator on the repo, works on native Ubuntu (dual boot), owns the `infra-k8s` branch (the k3d cluster, the manifests, the plots).
- Anything neither role-specific list below claims is something **both of you run, identically, on your own machine.**

This document gives you commands, directory structure, and exact "who does this" labels. It does **not** paste the Python source files themselves — you're writing/pairing on those directly in VS Code once the repo and issues exist; this roadmap is the scaffolding and the sequence, not the code.

---

## PHASE 1 — GitHub Repository, Folder Skeleton & Issue Board (Ashhadullah only)

Everything in this phase happens on **Ashhadullah's Kali WSL2 machine, before Misbah touches anything.** The repo has to exist and have issues on it before there's anything for Misbah to clone or pick up.

### 1.1 Install and authenticate the GitHub CLI

```bash
(type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
	&& sudo mkdir -p -m 755 /etc/apt/keyrings \
	&& out=$(mktemp) && wget -nv -O "$out" https://cli.github.com/packages/githubcli-archive-keyring.gpg \
	&& cat "$out" | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
	&& sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
	&& sudo mkdir -p -m 755 /etc/apt/sources.list.d \
	&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
	| sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
	&& sudo apt update \
	&& sudo apt install gh -y

gh --version
gh auth login --hostname github.com --git-protocol https --web
gh auth status   # confirm: "Logged in to github.com as <your-username>"
```

### 1.2 Create the local folder skeleton (directories only — no code files yet)

```bash
mkdir -p ~/projects/quantum-k8s-pod-placement && cd ~/projects/quantum-k8s-pod-placement

mkdir -p src tests scripts manifests results .github/workflows
touch src/__init__.py tests/__init__.py
touch README.md requirements.txt .gitignore

git init -b main
```

`.gitignore` (paste this in as-is — `nano .gitignore` or your editor of choice):
```gitignore
# Python
quantum_env/
__pycache__/
*.pyc
.pytest_cache/

# Kubernetes credentials — never commit these
kubeconfig
*.kubeconfig
.kube/

# Generated (regenerate, don't diff)
results/*.json
manifests/test-pods*.yaml

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
```

```bash
git add .
git commit -m "chore: initial project skeleton (folders only, no implementation yet)"
```

### 1.3 Create the GitHub repo from this folder and push

```bash
gh repo create quantum-k8s-pod-placement \
    --private \
    --source=. \
    --remote=origin \
    --description "CS-351 CEP: Quantum-Assisted Kubernetes Pod Placement — QAOA scheduler vs kube-scheduler on K3s" \
    --push

gh repo view --web=false
```
`--private` keeps it off public search until grading/portfolio time; flip it later with `gh repo edit --visibility public`.

### 1.4 Open the repo in VS Code

```bash
# from inside ~/projects/quantum-k8s-pod-placement
code .
```
If `code` isn't on your WSL2 PATH: install the "WSL" extension in VS Code on the Windows side once — after that, `code .` from any WSL2 terminal opens that folder in a VS Code window running against the WSL2 filesystem.

### 1.5 Invite Misbah as a collaborator

This needs Misbah's **GitHub username** (not his email — the collaborator-invite endpoint only accepts a username; GitHub deliberately doesn't expose email-to-account lookup). Get it from him once, then:

```bash
gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "/repos/$(gh api user --jq .login)/quantum-k8s-pod-placement/collaborators/MISBAH_GH_USERNAME" \
    -f permission='push'

# confirm the invite is pending
gh api "/repos/$(gh api user --jq .login)/quantum-k8s-pod-placement/invitations" \
    --jq '.[] | {invitee: .invitee.login, permission: .permissions, created: .created_at}'
```

`permission='push'` gives Misbah read+write (branches, commits, PRs) without repo-admin rights (settings, deleting the repo) — the right level for a co-author who isn't the owner.

### 1.6 Generate every GitHub Issue from the terminal (labels + full detail, nothing missing)

One script creates the labels first, then one Issue per unit of work across the whole build — each with an owner, a technical spec, and checkbox acceptance criteria. Save this as `scripts/create_issues.sh`:

```bash
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
  --body "$(cat <<'EOF'
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
EOF
)"

gh issue create \
  --title "[Infra] Docker + K3s + Python venv on native Ubuntu" \
  --label infrastructure \
  --body "$(cat <<'EOF'
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
EOF
)"

# ---------- Kubernetes cluster + workload -----------------------------------
gh issue create \
  --title "[Infra] k3d 3-worker cluster, aliased node labels (scripts/create_cluster.sh)" \
  --label infrastructure \
  --body "$(cat <<'EOF'
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
EOF
)"

gh issue create \
  --title "[Infra] Workload table + manifest generator (src/workload.py, src/generate_manifests.py)" \
  --label infrastructure \
  --body "$(cat <<'EOF'
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
EOF
)"

gh issue create \
  --title "[Infra] Live cluster state reader (src/cluster_metrics.py)" \
  --label infrastructure \
  --body "$(cat <<'EOF'
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
EOF
)"

# ---------- Quantum core ------------------------------------------------------
gh issue create \
  --title "[Quantum] QUBO formulation + builder (src/qubo_builder.py)" \
  --label quantum-core \
  --body "$(cat <<'EOF'
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
EOF
)"

gh issue create \
  --title "[Quantum] Batched QAOA scheduler + Kubernetes Binding API (src/quantum_scheduler.py)" \
  --label quantum-core \
  --body "$(cat <<'EOF'
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
EOF
)"

# ---------- Benchmarking -------------------------------------------------------
gh issue create \
  --title "[Benchmarking] Default vs quantum scheduler benchmark (src/benchmark.py)" \
  --label benchmarking \
  --body "$(cat <<'EOF'
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
EOF
)"

gh issue create \
  --title "[Benchmarking] Result charts + summary (src/plot_results.py)" \
  --label benchmarking \
  --body "$(cat <<'EOF'
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
EOF
)"

gh issue create \
  --title "[Benchmarking] Test suite for everything above" \
  --label benchmarking \
  --body "$(cat <<'EOF'
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
EOF
)"

# ---------- Documentation / repo housekeeping ---------------------------------
gh issue create \
  --title "[Docs] README, requirements.txt, branch protection" \
  --label documentation --assignee "@me" \
  --body "$(cat <<'EOF'
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
EOF
)"

echo "Done. Run 'gh issue list' to verify everything landed."
```

```bash
chmod +x scripts/create_issues.sh
./scripts/create_issues.sh
gh issue list --limit 20
git add scripts/create_issues.sh
git commit -m "chore: add issue-generation script"
git push
```

---

## PHASE 2 — Local Environment Setup (both machines — labeled where it differs)

### 2.1 Misbah: accept the invite and clone

```bash
# Install and authenticate gh exactly as in Phase 1.1 (identical commands on Ubuntu)

# Accept the invite — the one step gh can't do for you: GitHub requires the
# invitee's own authenticated session to confirm it (anti-abuse measure).
# Check your email or https://github.com/notifications, click Accept.

gh repo view Ashhadullah_GH_USERNAME/quantum-k8s-pod-placement   # should now succeed, not 404
gh repo clone Ashhadullah_GH_USERNAME/quantum-k8s-pod-placement
cd quantum-k8s-pod-placement
code .   # same VS Code / WSL-or-native flow as Ashhadullah used
```

### 2.2 Docker + K3s — **this is the one step that genuinely differs by OS**

```bash
# ============ ASHHADULLAH ONLY — Kali WSL2 ============
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y curl wget git build-essential software-properties-common \
    apt-transport-https ca-certificates gnupg iptables iproute2 util-linux-extra \
    python3-venv python3-pip python3-dev

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker

# WSL2-only: enable systemd, then `wsl --shutdown` from PowerShell and reopen
echo -e "[boot]\nsystemd=true" | sudo tee /etc/wsl.conf
```

```bash
# ============ MISBAH ONLY — native Ubuntu ============
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y curl wget git build-essential software-properties-common \
    apt-transport-https ca-certificates gnupg iptables iproute2 \
    python3-venv python3-pip python3-dev

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker

# no systemd step — native Ubuntu already runs systemd
```

```bash
# ============ BOTH MACHINES, identical from here ============
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
sudo systemctl status k3s --no-pager

mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
source ~/.bashrc
alias k=kubectl

kubectl get nodes   # plain kubectl, no sudo — sudo's PATH excludes /usr/local/bin
                     # where K3s installs its kubectl symlink
```

### 2.3 Python virtual environment — **identical on both machines**

```bash
python3 -m venv quantum_env
source quantum_env/bin/activate
python --version    # 3.13.x or 3.14.x on Kali; whatever Ubuntu's repo ships

pip install --upgrade pip
pip install \
    qiskit==2.5.2 \
    qiskit-aer==0.17.2 \
    qiskit-optimization==0.7.0 \
    qiskit-algorithms==0.4.0 \
    kubernetes==36.0.3 \
    networkx==3.7 \
    matplotlib==3.11.2 \
    pyyaml==6.0.3 \
    docplex==2.28.240 \
    pytest

pip freeze > requirements.txt
git add requirements.txt
git commit -m "chore: pin dependency versions"
git push
```

### 2.4 Verification — both machines, identical

Confirm K3s is Ready and Qiskit-Aer's simulator actually runs before writing anything else:

```bash
kubectl get nodes -o wide          # must show a Ready control-plane node

python - <<'PY'
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1); qc.measure_all()
counts = AerSimulator().run(qc, shots=1024).result().get_counts()
print(counts)
assert set(counts).issubset({"00", "11"}), "Aer simulator is broken"
print("Aer OK")
PY
```

**Quick reference — who runs what in Phase 2:**

| Step | Ashhadullah (Kali WSL2) | Misbah (native Ubuntu) |
|---|---|---|
| Clone the repo | already has it (created it) | `gh repo clone ...` after accepting the invite |
| base `apt install` | run | run — same packages |
| Docker APT repo line | `debian`/`bookworm` | `ubuntu`/`$(lsb_release -cs)` |
| `usermod`/`newgrp` docker | run | run — identical |
| `/etc/wsl.conf` systemd | run (WSL2 needs it) | **skip** — native systemd already |
| K3s install, kubeconfig export | run | run — identical |
| Python venv + pip installs | run | run — identical, same pins |
| Verification script | run | run — identical |

---

## PHASE 3 — Kubernetes Cluster & Workload (both machines, identical commands)

Both of you create your **own local k3d cluster** on your own machine so you can each develop and test against something real — the cluster used for the actual graded live demo is whichever machine you demo from (Ashhadullah's, by default, unless you decide otherwise).

### 3.1 Install k3d and create the 3-worker cluster

```bash
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
k3d version

k3d cluster create quantum-cluster \
    --servers 1 --agents 3 \
    --k3s-arg "--disable=traefik@server:0"

for i in 0 1 2; do
  alias=$(printf 'node-%s' "$(echo alpha beta gamma | cut -d' ' -f$((i+1)))")
  kubectl label node "k3d-quantum-cluster-agent-$i" cep-alias="$alias" --overwrite
done
kubectl get nodes -L cep-alias
```

This exact sequence belongs in `scripts/create_cluster.sh` (Misbah's issue from Phase 1.6) as an idempotent script — check-before-create, so re-running it doesn't error or duplicate the cluster.

### 3.2 Folder structure this phase fills in

```
quantum-k8s-pod-placement/
├── scripts/
│   ├── create_issues.sh          # done — Phase 1.6
│   └── create_cluster.sh         # this phase — Misbah
├── manifests/
│   ├── test-pods.yaml            # generated — default-scheduler run
│   └── test-pods-quantum.yaml    # generated — quantum-scheduler run
├── src/
│   ├── workload.py                # this phase — Misbah
│   ├── generate_manifests.py      # this phase — Misbah
│   └── cluster_metrics.py         # this phase — Misbah
```

### 3.3 Commands to generate and inspect the workload (once `src/` files exist)

```bash
python -m src.generate_manifests            # reads live k3d capacity
python -m src.generate_manifests --offline  # no cluster needed, quick sanity check
python -m src.cluster_metrics                # prints live node budgets + workload pods
```

---

## PHASE 4 — Quantum Optimization Engine (Ashhadullah, `quantum-core` branch)

This is Ashhadullah's branch end to end — Misbah reviews the PR (Phase 6) but doesn't write this code.

### 4.1 What gets built here

- `src/qubo_builder.py` — integer-unit QUBO formulation per batch of pods, with real linear equality/inequality constraints (not squared soft penalties), plus an independent reference cost function and a brute-force exact optimum to check correctness against.
- `src/quantum_scheduler.py` — orders pods by traffic weight, solves in small batches via QAOA on an Aer simulator, picks the lowest-cost feasible sample per batch, falls back to a classical greedy placement (explicitly recorded) when a batch has no feasible sample, and binds the final placement to real nodes via the Kubernetes Binding API.

### 4.2 Commands to run and sanity-check it

```bash
python -m src.quantum_scheduler --offline --dry-run   # no cluster, no binding — just solve and print
python -m src.quantum_scheduler --dry-run              # solve against the live cluster, don't bind yet
python -m src.quantum_scheduler                        # solve AND bind (needs test-pods-quantum.yaml applied first)
```

### 4.3 The one gotcha worth knowing before you start

`qiskit-aer`'s `SamplerV2` needs QAOA's ansatz circuit **transpiled** before it can run it — pass an explicit transpiler (a preset pass manager built for an `AerSimulator` backend) into QAOA's constructor, or it fails with `AerError: unknown instruction: QAOA`. This is the single most likely place to lose time if you're pattern-matching from an older Qiskit tutorial — worth a line in your own commit message when you hit it, so Misbah (and future-you) knows why it's there.

---

## PHASE 5 — Benchmarking & Comparative Analysis

### 5.1 What gets built here

- `src/benchmark.py` (Ashhadullah, `quantum-core`) — runs N iterations, each creating the same pod set once for the real default `kube-scheduler` and once for the quantum scheduler, times both end-to-end, and scores both with the same metric function: resource imbalance %, a disclosed/modelled latency number, and measured cross-node traffic in Mbps.
- `src/plot_results.py` (Misbah, `infra-k8s`) — turns `results/benchmark_data.json` into box-plots (not just mean lines — variance matters) for latency and imbalance, a QAOA convergence plot, and a `results/summary.json`.

### 5.2 Commands

```bash
python -m src.benchmark --iterations 20
python -m src.plot_results
```

Produces `results/latency_comparison.png`, `results/resource_balance.png`, `results/convergence_plot.png`, `results/summary.json`, `results/benchmark_data.json`.

### 5.3 One honest thing to keep in mind before you present this

At 10 pods / 3 nodes on a classical simulator with a modest shot budget, QAOA will very likely be *slower* and *not consistently better* than `kube-scheduler`'s own heuristics on imbalance/latency — that's the normal, expected result at this scale, not a bug in your implementation. Report what the numbers actually show; don't frame the Comparative Analysis as "our scheduler won" if it didn't.

---

## PHASE 6 — Ongoing Git Workflow: Branches, Commits, PRs, Merges (both of you, continuously)

This isn't a one-time phase — it's how every phase above 2 through 5 actually gets written and merged. Both of you use these same commands throughout.

```bash
# ---- Misbah: infra-k8s branch --------------------------------------------
git checkout main && git pull
git checkout -b infra-k8s
# ... do the work for whichever Phase-3/5 issue you're on ...
git add scripts/create_cluster.sh
git commit -m "feat(infra): add idempotent k3d 3-worker cluster script"
git push -u origin infra-k8s

gh pr create \
    --base main --head infra-k8s \
    --title "Infra: k3d cluster, live metrics, manifest generation" \
    --body "Closes #2, #3, #4. See CEP_Roadmap.md Phase 3." \
    --reviewer AshhadullahGHUsername \
    --label infrastructure

# ---- Ashhadullah: quantum-core branch -------------------------------------
git checkout main && git pull
git checkout -b quantum-core
# ... do the work for whichever Phase-4/5 issue you're on ...
git add src/qubo_builder.py
git commit -m "feat(quantum): QUBO builder with real linear constraints"
git push -u origin quantum-core

gh pr create \
    --base main --head quantum-core \
    --title "Quantum core: batched QAOA scheduler" \
    --body "Closes #6, #7. See CEP_Roadmap.md Phase 4." \
    --reviewer MisbahGHUsername \
    --label quantum-core

# ---- Reviewing and merging (each of you reviews the OTHER's PR) -----------
gh pr list
gh pr view <number>
gh pr diff <number>
gh pr review <number> --approve --body "Reviewed, looks correct, tests pass locally."
gh pr merge <number> --squash --delete-branch
```

**Commit message convention, used by both of you:** `feat:` for new capability, `fix:` for a correction (like the QAOA transpiler fix in Phase 4.3), `docs:`, `test:`, `chore:` for scaffolding/deps. This keeps `git log --oneline` a genuinely readable record of who built what, in what order — which is exactly the kind of thing a Q&A panel can ask you to walk through.

### Optional: branch protection on `main`

```bash
gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "/repos/$(gh api user --jq .login)/quantum-k8s-pod-placement/branches/main/protection" \
    -f required_pull_request_reviews[required_approving_review_count]=1 \
    -F required_status_checks=null \
    -F enforce_admins=false \
    -F restrictions=null
```

---

## Full Directory Structure (end state, after Phase 5)

```
quantum-k8s-pod-placement/
├── scripts/
│   ├── create_issues.sh
│   └── create_cluster.sh
├── manifests/
│   ├── test-pods.yaml
│   └── test-pods-quantum.yaml
├── src/
│   ├── __init__.py
│   ├── workload.py
│   ├── generate_manifests.py
│   ├── cluster_metrics.py
│   ├── qubo_builder.py
│   ├── quantum_scheduler.py
│   ├── benchmark.py
│   └── plot_results.py
├── tests/
│   ├── __init__.py
│   ├── test_parsing.py
│   ├── test_qubo_builder.py
│   ├── test_scheduler_offline.py
│   └── test_benchmark_flow.py
├── results/
│   ├── latency_comparison.png
│   ├── resource_balance.png
│   ├── convergence_plot.png
│   ├── summary.json
│   └── benchmark_data.json
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Execution Order Checklist

1. **Phase 1 (Ashhadullah only):** repo created, folder skeleton pushed, cloned into VS Code, Misbah invited, every Issue generated via `scripts/create_issues.sh`.
2. **Phase 2 (both):** Misbah accepts the invite and clones; Docker/K3s installed (OS-specific step per the table above); identical Python venv on both machines; both verification checks pass.
3. **Phase 3 (both machines run the same commands; Misbah writes the code on `infra-k8s`):** k3d cluster up on each machine, workload table + manifest generator + cluster-state reader implemented and merged via PR.
4. **Phase 4 (Ashhadullah, `quantum-core`):** QUBO builder and batched QAOA scheduler implemented, offline dry-run works, merged via PR.
5. **Phase 5 (both, after 3 and 4 are merged):** `benchmark.py` runs 20 iterations against a live cluster, `plot_results.py` produces every chart + summary.
6. **Phase 6 (ongoing throughout 3-5):** every unit of work above is its own branch, PR, review, and squash-merge — this is what gives you a real, defensible commit history for Q&A, not a story about one.
7. Rehearse the live demo: `kubectl get pods -n quantum-sched-test -o wide` before/after running `quantum_scheduler.py`, showing the `nodeName` assignment change live; have `gh pr list --state merged` and `git log --oneline --graph` ready to show as evidence of the actual collaboration.
