# Cascade Shield: An Intelligent Framework for Cascading Failure Containment and Recovery in Microservice Systems

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen.svg)]()
[![Tests](https://img.shields.io/badge/tests-50%20passed-success.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 1. Executive Summary

Modern cloud-native architectures rely on deeply interconnected networks of microservices. While microservice designs enable rapid iteration and modular scalability, they introduce severe systemic vulnerability to **cascading failures**—where localized disruptions (such as high latency, network timeouts, or process crashes) trigger cascading resource exhaustion and outages across dependent services.

**Cascade Shield** is a deterministic simulation and resilience framework designed to:
1. **Model** realistic cascading fault propagation through directed dependency topologies.
2. **Contain** failure spread autonomously using multi-strategy policies (Circuit Breakers, Token-Bucket Rate Limiters, Bulkheads, Service Isolation, and Backup Failover).
3. **Decide** optimal mitigation actions using an explainable, deterministic multi-factor heuristic scoring engine.
4. **Recover** failed subsystems safely via dependency-ordered (topological) health checks and staged canary traffic restoration (20% → 40% → 60% → 80% → 100%).
5. **Benchmark** resilience across 16 scenarios in 4 real-world domains against baseline policies under identical conditions.

---

## 2. Mathematical Modeling & Metrics

### 2.1 Effective Availability ($A_{eff}$)
System availability accounts for degraded operation rather than binary up/down states:
$$A_{eff} = \frac{N_{healthy} + 0.5 \times N_{degraded}}{N_{total}}$$
- If all services are healthy: $A_{eff} = 1.0$ (100%).
- If all services are degraded: $A_{eff} = 0.5$ (50%).
- If $N_{total} = 0$, $A_{eff} = 1.0$ (vacuously available).

### 2.2 Critical Tier Availability ($A_{crit}$)
Evaluates only mission-critical tier services ($S_{crit} \cup S_{high}$):
$$A_{crit} = \frac{N_{crit,healthy} + 0.5 \times N_{crit,degraded}}{N_{crit,total}}$$

### 2.3 Blast Radius Analysis
For a failed service $v \in V$:
- **Direct Dependents**: $\text{Pred}(v) = \{u \in V \mid (u, v) \in E\}$
- **Transitive Blast Radius**: $\text{TransPred}(v) = \{u \in V \mid u \rightsquigarrow v\}$
- **Critical Services At Risk**: $\{u \in \text{TransPred}(v) \mid \text{Crit}(u) \in \{\text{CRITICAL}, \text{HIGH}\}\}$

### 2.4 Failure Exhaustion Dynamics
When critical downstream dependencies become unavailable, dependent callers enter a `DEGRADED` state. If critical dependencies remain unreachable for $k \ge K_{exhaustion}$ consecutive ticks (default $K_{exhaustion} = 3$), the service exhausts its buffers/threads and transitions to `FAILED`, propagating the cascade further upstream. Containment strategies halt this exhaustion loop.

---

## 3. Core Architecture & Modules

```
cascade_shield/
├── config.py              # Global thresholds, state definitions, heuristic weights
├── models/
│   └── service.py         # Type-safe dataclasses (ServiceInstance, DependencyEdge, Events)
├── graph/
│   ├── dependency_graph.py# NetworkX-backed topology, blast radius, routing engine
│   └── profiles.py        # 4 domain presets (ecommerce, banking, streaming, saas)
├── failure/
│   └── simulator.py       # Deterministic injection, propagation, auto-healing
├── containment/
│   └── policies.py        # Circuit breaker, rate limiter, bulkhead, failover manager
├── recovery/
│   └── manager.py         # Read-only health probing, canary staged restoration
├── engine/
│   └── decision_engine.py # Heuristic multi-factor scoring & explainability
├── metrics/
│   └── collector.py       # Point-in-time snapshots, downtime, availability aggregation
└── experiment/
    └── runner.py          # Benchmark suite runner, winner evaluation, CSV/JSON export
```

---

## 4. Multi-Strategy Containment & Decision Engine

The **Decision Engine** evaluates every candidate containment action using weighted scoring:

$$\text{Score}(A, s) = w_c \cdot C(s) + w_b \cdot B(s) + w_f \cdot F(s) + w_d \cdot D(s) - w_r \cdot R(s) + M(A, s)$$

| Weight Variable | Value | Description |
|---|---|---|
| $w_c$ (`WEIGHT_CRITICALITY`) | `0.25` | Criticality tier score (CRITICAL=1.0, HIGH=0.75, MED=0.5, LOW=0.25) |
| $w_b$ (`WEIGHT_BLAST_RADIUS`) | `0.20` | Normalized blast radius proportion across system |
| $w_f$ (`WEIGHT_FAILURE_SEVERITY`) | `0.20` | Severity (Unavailable=1.0, Timeout=0.8, ErrorRate=0.6, Latency=0.4) |
| $w_d$ (`WEIGHT_DEPENDENCY_IMPACT`) | `0.15` | Number of high-criticality callers at immediate risk |
| $w_r$ (`WEIGHT_RECOVERY_HISTORY`) | `0.10` | Penalty proportional to exhausted recovery attempts |
| $M(A, s)$ | Variable | Policy-specific action modifier (e.g. +0.20 for Failover when backup ready) |
| **Infeasible Penalty** | `-100.0` | Immediate disqualification if preconditions are violated |

### Supported Containment Actions:
1. `OPEN_CIRCUIT_BREAKER`: Drops traffic immediately, preventing upstream thread starvation.
2. `RATE_LIMIT`: Throttles request rates using token-bucket rate limiting during error storms.
3. `ISOLATE`: Fully isolates catastrophic failures to protect healthy network partitions.
4. `FAILOVER`: Dynamically re-routes dependencies to pre-configured warm backup instances.
5. `RETRY_WITH_BACKOFF`: Applies bounded exponential backoff for transient timeouts.
6. `RESTART`: Clears fault state and transitions service into staged recovery.
7. `DEFER_AND_ALERT`: Low-overhead telemetry and alerting for non-critical services.
8. `RESTORE_TRAFFIC`: Stages progressive traffic ramp-up for recovering services.

---

## 5. Domain Profiles & Scenarios

Cascade Shield includes four production-inspired domain profiles, each featuring 4 preset disaster scenarios:

| Domain | Services | Edges | Key Preset Scenarios |
|---|---|---|---|
| **E-Commerce** | 11 | 15 | Database Outage, Payment Gateway Timeout, Cascading Order Failure, Multi-Service Degradation |
| **Banking** | 10 | 14 | Database Outage, Auth Service Failure, Transaction Timeout Storm, Fraud Detection Overload |
| **Video Streaming** | 9 | 12 | Content Storage Failure, Streaming Service Crash, Transcoding Bottleneck, Multi-Service Stress |
| **SaaS Platform** | 10 | 15 | Database Outage, App Service Crash, Auth Timeout, Billing & Tenant Stress |

---

## 6. Benchmark Suite & Comparative Results

Every scenario is tested across three policies under identical initial seeds and conditions:
- **No Containment (Baseline)**: Passive observation without intervention.
- **Simple Circuit Breaker (Standard)**: Naive circuit breaking on failing services.
- **Cascade Shield (Proposed)**: Intelligent multi-strategy containment with heuristic decision engine and staged topological recovery.

### 6.1 Results Summary across 16 Scenarios:
- **Cascade Shield Wins**: 8 (50%)
- **Ties**: 8 (50% — in transient timeout/degradation scenarios where basic mitigations suffice)
- **Simple Circuit Breaker Wins**: 0
- **No Containment Wins**: 0

### 6.2 Scenario Breakdown:
| Domain | Scenario | Winner | Shield Min Avail | Simple CB Min | No Cont. Min |
|---|---|---|---|---|---|
| **E-Commerce** | Database Outage | **Cascade Shield** | **68.2%** | 36.4% | 27.3% |
| **E-Commerce** | Payment Gateway Timeout | Tie | 95.5% | 95.5% | 95.5% |
| **E-Commerce** | Cascading Order Failure | **Cascade Shield** | **81.8%** | 72.7% | 45.5% |
| **E-Commerce** | Multi-Service Degradation | Tie | 90.9% | 90.9% | 90.9% |
| **Banking** | Database Outage | **Cascade Shield** | **55.0%** | 30.0% | 10.0% |
| **Banking** | Auth Service Failure | **Cascade Shield** | **85.0%** | 70.0% | 40.0% |
| **Banking** | Transaction Timeout Storm | Tie | 95.0% | 95.0% | 95.0% |
| **Banking** | Fraud Detection Overload | Tie | 90.0% | 90.0% | 90.0% |
| **Streaming** | Content Storage Failure | **Cascade Shield** | **66.7%** | 44.4% | 33.3% |
| **Streaming** | Streaming Service Crash | **Cascade Shield** | **83.3%** | 66.7% | 44.4% |
| **Streaming** | Transcoding Bottleneck | Tie | 94.4% | 94.4% | 94.4% |
| **Streaming** | Multi-Service Stress | Tie | 88.9% | 88.9% | 88.9% |
| **SaaS** | Database Outage | **Cascade Shield** | **55.0%** | 30.0% | 10.0% |
| **SaaS** | App Service Crash | **Cascade Shield** | **80.0%** | 70.0% | 50.0% |
| **SaaS** | Auth Timeout | Tie | 95.0% | 95.0% | 95.0% |
| **SaaS** | Billing and Tenant Stress | Tie | 90.0% | 90.0% | 90.0% |

Benchmark results are automatically exported to:
- `benchmark_results/benchmark_results.csv`
- `benchmark_results/benchmark_results.json`
- `benchmark_results/benchmark_report.md`

---

## 7. Interactive Streamlit Dashboard

The redesigned dashboard provides an intuitive, dark-mode user interface:
- **Live Topology**: Interactive Plotly graph depicting services colored by health state, sized and shaped by criticality tier, with directed dependency arrows and blast radius highlighting.
- **Fault Injection Studio**: One-click preset scenario injection or custom fault generation (target, fault type, duration, severity).
- **Decision Engine Auditor**: Real-time explainability table showing candidate action ranking, feasibility breakdown, and heuristic rationales.
- **Policy Comparison Arena**: Side-by-side time-series comparison charts and bar charts comparing all three policies.
- **Domain Profiles Explorer**: Architectural view of all service definitions, backup bindings, and dependency edges.

Launch dashboard:
```bash
streamlit run dashboard/app.py
```

---

## 8. Installation & Verification

### 8.1 Setup
```bash
# Clone and install in editable mode
git clone <repo-url>
cd cascade-shield
pip install -e .
```

### 8.2 Run Test Suite
```bash
pytest -v --cov=cascade_shield --cov-report=term-missing
```
*Current test results: **50 passed, 0 failed, 92% coverage**.*

### 8.3 Run Benchmark Suite
```bash
python scripts/benchmark_all_scenarios.py
```

### 8.4 Export Config Topologies
```bash
python scripts/generate_configs.py
```

---

## 9. Assumptions & Research Limitations

1. **Simulated Runtime**: This framework simulates microservice request-response loops and exhaustion dynamics; it does not deploy containerized OS processes or bind to physical network sockets.
2. **Heuristic Optimization**: The decision engine employs a multi-factor weighted heuristic scoring function rather than reinforcement learning or offline gradient optimization.
3. **Reproducibility**: All benchmark results are deterministic when initialized with identical PRNG seeds and topology configurations.
