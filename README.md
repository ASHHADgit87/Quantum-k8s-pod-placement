# Quantum-Assisted Kubernetes Pod Placement

**Quantum-Assisted Kubernetes Pod Placement** is a hybrid quantum-classical scheduling engine built with **Python, Qiskit, Kubernetes Python Client, K3s/k3d, and Docker**. Cluster operators can simulate network-heavy workloads, formulate Quadratic Unconstrained Binary Optimization (QUBO) models, and securely bind pods to optimal nodes. Every workload batch is validated, optimized via QAOA, fallback-protected, and benchmarked against the default Kubernetes scheduler in a strictly isolated local cluster.

---

# Problem Statement

Modern microservices generate massive amounts of cross-node network traffic, leading to latency bottlenecks and increased ingress/egress costs. Standard Kubernetes scheduling heuristics focus on resource availability but fail to globally optimize for inter-pod communication graphs.

Solving graph-partitioning and network-aware placement optimally is an NP-Hard problem. Classical brute-force algorithms scale exponentially, making them unusable for large clusters. 

Quantum-Assisted Kubernetes Pod Placement solves this by framing the placement state space as a QUBO problem, leveraging the Quantum Approximate Optimization Algorithm (QAOA) to find near-optimal placements, and utilizing the native Kubernetes Binding API to execute the result seamlessly.

---

# Core Integration

The system uses **Python 3.14**, **Qiskit Aer Simulator**, **Kubernetes API**, **k3d**, and **pytest** to deliver a mathematically verified, high-performance scheduling pipeline.

### Stack Integration

| Component | Role |
|---|---|
| `Python 3.14` | Core engine, data structures, and CLI execution |
| `Qiskit` | Quantum circuit compilation and statevector sampling |
| `Qiskit Optimization` | QUBO formulation and Minimum Eigen optimization |
| `Kubernetes Client` | Live cluster metrics ingestion and Pod Binding API |
| `K3s / k3d` | Lightweight, isolated local Kubernetes cluster infrastructure |
| `Pytest` | Test orchestration with dynamic QAOA optimization patches |
| `SonarCloud` | Static analysis, complexity tracking, and security hardening |

---

### Request Pipeline
Cluster Metrics Ingestion -> Workload Parsing -> Batching -> QUBO Formulation -> QAOA Statevector Solve -> Feasibility Validation -> Classical Fallback (if needed) -> Kubernetes Binding API

---

# Architecture

The system follows a **hybrid modular architecture**:

| Layer | Technology |
|---|---|
| Infrastructure | Docker, K3s, k3d (3-worker topology) |
| API Interface | Kubernetes Python Client (`client.CoreV1Api`) |
| Optimization Core | Qiskit `MinimumEigenOptimizer`, COBYLA |
| Mathematical Formulation | `QuadraticProgram`, Docplex |
| Validation | Built-in brute-force exact optimum reference |
| Testing | Pytest with `conftest.py` global mocking |

---

# BaaS

While operating as a local script, the scheduling engine functions conceptually as a **Backend-as-a-Service (BaaS)** for Kubernetes clusters. Administrators can deploy workloads with a custom `schedulerName`, and this engine acts as an external, mathematically rigorous placement webhook—assuming full responsibility for the binding lifecycle without modifying the core control plane.

---

# Features

### Scheduling System

| Capability | Detail |
|---|---|
| Quantum solver | QAOA (qiskit-algorithms, StatevectorSampler) on a 9-qubit per-batch program; the lowest-energy sample that fits node capacity is kept |
| Fallback mechanism | Deterministic classical brute-force exact optimum for infeasible quantum samples |
| Batch processing | Pods are sorted by traffic weight and processed in sub-batches to manage qubit limits |
| Native K8s binding | Utilizes `V1Binding` to assign pods to nodes directly, bypassing default scheduling |
| Workload generation | Deterministic 10-pod generation with simulated cross-node traffic matrix |

### Security & Hardening

| Capability | Detail |
|---|---|
| Path traversal protection | Absolute path resolution and `is_relative_to` checks for all file outputs |
| Safe file handling | Context managers (`with open()`) used strictly to satisfy SonarCloud sinks |
| Offline mode | CLI flags to execute full mathematical pipeline without a live cluster |
| Type safety | Type hints and deterministic string parsing for K8s resource quantities |
| SonarCloud 'A' Rating | Zero code smells, zero vulnerabilities, strict complexity boundaries |

### Benchmarking & Analytics

| Capability | Detail |
|---|---|
| Comparative execution | End-to-end N-iteration runs against default `kube-scheduler` |
| Resource imbalance | Calculates CPU and memory load variance across all active worker nodes |
| Traffic calculation | Precise Mbps evaluation of cross-node vs same-node pod communication |
| JSON reporting | Immutable metadata payload containing iteration duration and exact assignments |
| Automated visualization | Headless Matplotlib box-plots for latency and balance, a per-batch QAOA convergence plot, and `summary.json` with mean/std per metric, the exact-optimum objective and the fallback-batch count |

### Quantum Simulation

| Capability | Detail |
|---|---|
| Qubit scaling | Automatically allocates variables based on `Pods x Nodes` formulation |
| COBYLA optimizer | Classical optimization loop for parameterized quantum circuits |
| Dynamic test patching | `maxiter=1` injection during CI/CD to reduce wait times by 90% |
| Feasibility tracking | Hard constraints for "one node per pod" and "node capacity limit" |

### Data Model

| Entity | Key Fields |
|---|---|
| `NodeBudget` | `name`, `alias`, `allocatable_cpu_m`, `allocatable_memory_bytes` |
| `PodRequest` | `name`, `namespace`, `cpu_m`, `memory_bytes` |
| `TrafficEdge` | `source`, `target`, `mbps` |

---

# CLI Reference

| Command | Target | Mode | Purpose |
|---|---|---|---|
| `python -m src.generate_manifests` | Cluster | Live | Reads capacity and outputs YAML for testing |
| `python -m src.cluster_metrics` | Cluster | Live | Prints node budgets and network interface counters |
| `python -m src.quantum_scheduler` | Scheduler | Live | Executes full QAOA optimization and binds pending pods |
| `python -m src.benchmark` | Benchmarking | Simulated | Runs N iterations and exports `benchmark_data.json` |
| `python -m src.plot_results` | Benchmarking | Offline | Turns `benchmark_data.json` into box-plots, a QAOA convergence plot and `summary.json` |
| `python -m pytest -q` | CI/CD | Offline | Executes test suite with fast-patched quantum limits |

---

# Processing Capability

| Capability | Detail |
|---|---|
| Optimization throughput | Batch processing limits hardware bottleneck (3 pods = 9 qubits per batch) |
| Fallback limit | Brute-force solver handles $3^3$ state spaces instantly |
| Test suite execution | 164 tests (155 offline) execute in < 60 seconds via global `maxiter` restriction |
| Cluster footprint | K3d footprint requires minimal host RAM, fully isolated via containerization |

---

# Tech Stack

| Layer | Technology |
|---|---|
| Core Language | Python 3.14 |
| Quantum Framework | Qiskit 2.5.2, Qiskit Aer 0.17.2, Qiskit Optimization 0.7.0 |
| Classical Math | Docplex, NetworkX, SciPy |
| Kubernetes | Kubernetes Python Client 36.0.3, K3s, k3d |
| Analysis & Visualization | Matplotlib 3.11.2 |
| Testing & CI | Pytest, SonarCloud |

---

# Live Demo

Requires a local Docker install and the k3d cluster creation script. Run each command separately, in order, from the project root.

### 1. Activate the environment
```bash
source venv/bin/activate
```

### 2. Check that Docker is running
```bash
docker ps
```

### 3. Create the cluster (1 server + 3 workers)
```bash
./scripts/create_cluster.sh
```

### 4. Verify all nodes are Ready
```bash
kubectl get nodes
```

### 5. Generate the workload manifests
```bash
python -m src.generate_manifests
```

### 6. List the generated manifests
```bash
ls manifests
```

### 7. Deploy the baseline workload (default kube-scheduler)
```bash
kubectl apply -f manifests/<baseline-manifest>.yaml
```

### 8. Show the baseline placement
```bash
kubectl get pods -A -o wide | grep -v kube-system
```

### 9. Deploy the quantum-scheduled workload (stays Pending)
```bash
kubectl apply -f manifests/<quantum-manifest>.yaml
```

### 10. Show the pods waiting for the custom scheduler
```bash
kubectl get pods -A -o wide | grep -v kube-system
```

### 11. Run the QAOA scheduler (binds the pending pods)
```bash
python -m src.quantum_scheduler
```

### 12. Show the quantum placement
```bash
kubectl get pods -A -o wide | grep -v kube-system
```

### 13. Run the benchmark against the default scheduler
```bash
python -m src.benchmark
```

### 14. Generate the plots and summary
```bash
python -m src.plot_results
```

### 15. Show the summary results
```bash
cat results/summary.json
```

### 16. Run the test suite
```bash
python -m pytest -q
```

### 17. Clean up
```bash
./scripts/cleanup.sh
```

---

## Creator & Developer

- **Muhammad Ashhadullah Zaheer**
- LinkedIn: https://www.linkedin.com/in/muhammad-ashhadullah-zaheer-41194a340/
- **Misbah Sarfraz**
- Co-Creator & Infrastructure Developer
