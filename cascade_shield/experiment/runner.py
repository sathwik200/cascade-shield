"""Experiment runner for comparing containment policies.

Compares three policies under identical conditions:
1. No Containment — baseline that does nothing
2. Simple Circuit Breaker — baseline with only circuit breakers
3. Cascade Shield — full framework with all containment and recovery

All runs start from fresh topologies with identical failure scenarios,
timing, random seeds, and experimental configurations.

Results are reported honestly including wins, losses, and ties.
"""

from __future__ import annotations

import csv
import json
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from cascade_shield.graph.profiles import build_topology, build_failure_scenarios, get_scenario_names
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.failure.simulator import FailureSimulator
from cascade_shield.containment.policies import ContainmentManager
from cascade_shield.engine.decision_engine import DecisionEngine
from cascade_shield.recovery.manager import RecoveryManager
from cascade_shield.metrics.collector import MetricsCollector
from cascade_shield.models.service import (
    FailureScenario,
    ExperimentConfig,
    MetricSnapshot,
    HealthState,
    CircuitState,
)
from cascade_shield.config import (
    DEFAULT_EXPERIMENT_DURATION,
    DEFAULT_SEED,
    ACTION_OPEN_CIRCUIT_BREAKER,
    ACTION_ISOLATE,
    ACTION_FAILOVER,
    ACTION_RATE_LIMIT,
    ACTION_RESTART,
    ACTION_RETRY_WITH_BACKOFF,
    ACTION_DEFER_AND_ALERT,
    ACTION_RESTORE_TRAFFIC,
)


POLICIES = ["no_containment", "simple_circuit_breaker", "cascade_shield"]
POLICY_LABELS = {
    "no_containment": "No Containment",
    "simple_circuit_breaker": "Simple Circuit Breaker",
    "cascade_shield": "Cascade Shield",
}


@dataclass
class PolicyResult:
    """Results from running one policy on one scenario."""
    policy: str
    domain: str
    scenario: str
    metrics_history: list[MetricSnapshot] = field(default_factory=list)
    min_availability: float = 1.0
    avg_availability: float = 1.0
    critical_availability_min: float = 1.0
    peak_affected: int = 0
    downtime_ticks: int = 0
    recovery_time: int = 0
    cascade_count: int = 0
    containment_actions: int = 0
    recovery_attempts: int = 0


@dataclass
class ScenarioResult:
    """Comparison results for one scenario across all policies."""
    domain: str
    scenario: str
    policy_results: dict[str, PolicyResult] = field(default_factory=dict)
    winner: str = ""
    shield_improvement: float = 0.0


@dataclass
class BenchmarkResults:
    """Full benchmark results across all scenarios."""
    scenarios: list[ScenarioResult] = field(default_factory=list)
    wins: dict[str, int] = field(default_factory=dict)
    ties: int = 0
    total_scenarios: int = 0


class ExperimentRunner:
    """Runs comparison experiments between policies."""

    def __init__(self):
        pass

    def run_scenario(
        self,
        domain: str,
        scenario_name: str,
        duration: int = DEFAULT_EXPERIMENT_DURATION,
        seed: int = DEFAULT_SEED,
    ) -> ScenarioResult:
        """Run all three policies on a single scenario."""
        scenarios = build_failure_scenarios(domain, scenario_name)
        result = ScenarioResult(domain=domain, scenario=scenario_name)

        for policy in POLICIES:
            pr = self._run_policy(policy, domain, scenarios, duration, seed)
            pr.domain = domain
            pr.scenario = scenario_name
            result.policy_results[policy] = pr

        # Determine winner by minimum availability (higher is better)
        result.winner, result.shield_improvement = self._determine_winner(result)
        return result

    def run_all_scenarios(
        self,
        domain: str,
        duration: int = DEFAULT_EXPERIMENT_DURATION,
        seed: int = DEFAULT_SEED,
    ) -> list[ScenarioResult]:
        """Run all scenarios for a domain."""
        results = []
        for sc_name in get_scenario_names(domain):
            results.append(self.run_scenario(domain, sc_name, duration, seed))
        return results

    def run_benchmark(
        self,
        domains: Optional[list[str]] = None,
        duration: int = DEFAULT_EXPERIMENT_DURATION,
        seed: int = DEFAULT_SEED,
    ) -> BenchmarkResults:
        """Run full benchmark across specified domains."""
        from cascade_shield.graph.profiles import DOMAIN_KEYS
        if domains is None:
            domains = list(DOMAIN_KEYS)

        benchmark = BenchmarkResults()
        for policy in POLICIES:
            benchmark.wins[policy] = 0

        for domain in domains:
            for sc_name in get_scenario_names(domain):
                sr = self.run_scenario(domain, sc_name, duration, seed)
                benchmark.scenarios.append(sr)
                benchmark.total_scenarios += 1

                if sr.winner == "tie":
                    benchmark.ties += 1
                elif sr.winner in benchmark.wins:
                    benchmark.wins[sr.winner] += 1

        return benchmark

    # ----- Policy Execution -----

    def _run_policy(
        self,
        policy: str,
        domain: str,
        scenarios: list[FailureScenario],
        duration: int,
        seed: int,
    ) -> PolicyResult:
        """Run a single policy to completion."""
        # Fresh topology
        graph = build_topology(domain)
        simulator = FailureSimulator(graph, seed=seed)
        containment = ContainmentManager(graph)
        engine = DecisionEngine(graph, containment)
        recovery = RecoveryManager(graph)
        metrics = MetricsCollector(graph)

        result = PolicyResult(policy=policy, domain=domain, scenario="")

        # Initial snapshot
        metrics.snapshot()

        # Inject failures at tick 1
        inject_tick = 1

        for tick in range(1, duration + 1):
            # Inject failures at the designated tick
            if tick == inject_tick:
                simulator.inject_failures(scenarios)

            # Advance simulation
            simulator.step()

            # Apply policy-specific containment
            if policy == "simple_circuit_breaker":
                self._apply_simple_cb(graph, containment, simulator)
            elif policy == "cascade_shield":
                self._apply_cascade_shield(graph, containment, engine, simulator, recovery, tick)

            # Tick containment and recovery
            containment.tick()
            recovery.tick()

            # Collect metrics
            snap = metrics.tick()

        # Aggregate results
        result.metrics_history = metrics.history
        result.min_availability = metrics.get_min_availability()
        result.peak_affected = metrics.get_peak_affected()
        result.downtime_ticks = metrics.get_downtime_ticks()
        result.recovery_time = metrics.get_recovery_time()
        result.cascade_count = simulator.cascade_count
        result.containment_actions = len(containment.actions)
        result.recovery_attempts = sum(
            svc.recovery_attempts for svc in graph.services.values()
        )

        if result.metrics_history:
            avails = [s.effective_availability for s in result.metrics_history]
            result.avg_availability = sum(avails) / len(avails)
            crit_avails = [s.critical_availability for s in result.metrics_history]
            result.critical_availability_min = min(crit_avails)

        return result

    def _apply_simple_cb(self, graph: DependencyGraph,
                         containment: ContainmentManager,
                         simulator: FailureSimulator) -> None:
        """Simple Circuit Breaker policy: open circuit breakers for failing services."""
        for svc in graph.services.values():
            if svc.health in (HealthState.FAILED, HealthState.DEGRADED):
                if svc.circuit_state == CircuitState.CLOSED:
                    containment.circuit_breaker.open_circuit(svc)
                    simulator.set_contained(svc.service_id)

    def _apply_cascade_shield(self, graph: DependencyGraph,
                              containment: ContainmentManager,
                              engine: DecisionEngine,
                              simulator: FailureSimulator,
                              recovery: RecoveryManager,
                              tick: int) -> None:
        """Cascade Shield policy: full intelligent containment and recovery."""
        # Phase 1: Evaluate and apply containment for unhealthy services
        for svc in list(graph.services.values()):
            if svc.health in (HealthState.FAILED, HealthState.DEGRADED):
                if not simulator.is_contained(svc.service_id) or (svc.health == HealthState.FAILED and not svc.is_isolated):
                    recommendation = engine.recommend(svc.service_id)
                    if recommendation.feasible:
                        result = containment.execute_action(recommendation)
                        if result.success:
                            simulator.set_contained(svc.service_id)

        # Phase 2: Attempt recovery for services past their failure
        if tick > 3:  # Allow some ticks for failures to settle
            recovery.recover_cascade()

    # ----- Winner Determination -----

    def _determine_winner(self, result: ScenarioResult) -> tuple[str, float]:
        """Determine the winner based on minimum availability.

        Returns (winner_policy, improvement_pct).
        """
        avails = {
            policy: pr.min_availability
            for policy, pr in result.policy_results.items()
        }

        best_avail = max(avails.values())
        best_policies = [p for p, a in avails.items() if abs(a - best_avail) < 0.001]

        if len(best_policies) > 1:
            # Tie-break by average availability
            avg_avails = {
                p: result.policy_results[p].avg_availability
                for p in best_policies
            }
            best_avg = max(avg_avails.values())
            best_by_avg = [p for p, a in avg_avails.items() if abs(a - best_avg) < 0.001]

            if len(best_by_avg) > 1:
                winner = "tie"
            else:
                winner = best_by_avg[0]
        else:
            winner = best_policies[0]

        # Calculate shield improvement over no containment
        shield_avail = avails.get("cascade_shield", 1.0)
        no_cont_avail = avails.get("no_containment", 1.0)
        if no_cont_avail < 1.0 - 0.001:
            improvement = ((shield_avail - no_cont_avail) / (1.0 - no_cont_avail)) * 100
        else:
            improvement = 0.0

        return winner, improvement

    # ----- Export -----

    @staticmethod
    def export_csv(results: BenchmarkResults, path: Path) -> None:
        """Export benchmark results to CSV."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Domain", "Scenario", "Policy",
                "Min Availability", "Avg Availability",
                "Critical Availability Min",
                "Peak Affected", "Downtime Ticks",
                "Recovery Time", "Cascade Count",
                "Containment Actions", "Recovery Attempts",
                "Winner",
            ])
            for sr in results.scenarios:
                for policy, pr in sr.policy_results.items():
                    writer.writerow([
                        pr.domain, sr.scenario, POLICY_LABELS.get(policy, policy),
                        f"{pr.min_availability:.4f}",
                        f"{pr.avg_availability:.4f}",
                        f"{pr.critical_availability_min:.4f}",
                        pr.peak_affected, pr.downtime_ticks,
                        pr.recovery_time, pr.cascade_count,
                        pr.containment_actions, pr.recovery_attempts,
                        sr.winner,
                    ])

    @staticmethod
    def export_json(results: BenchmarkResults, path: Path) -> None:
        """Export benchmark results to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "total_scenarios": results.total_scenarios,
            "wins": results.wins,
            "ties": results.ties,
            "scenarios": [],
        }
        for sr in results.scenarios:
            sc_data = {
                "domain": sr.domain,
                "scenario": sr.scenario,
                "winner": sr.winner,
                "shield_improvement": round(sr.shield_improvement, 2),
                "policies": {},
            }
            for policy, pr in sr.policy_results.items():
                sc_data["policies"][policy] = {
                    "min_availability": round(pr.min_availability, 4),
                    "avg_availability": round(pr.avg_availability, 4),
                    "critical_availability_min": round(pr.critical_availability_min, 4),
                    "peak_affected": pr.peak_affected,
                    "downtime_ticks": pr.downtime_ticks,
                    "recovery_time": pr.recovery_time,
                    "cascade_count": pr.cascade_count,
                    "containment_actions": pr.containment_actions,
                    "recovery_attempts": pr.recovery_attempts,
                }
            data["scenarios"].append(sc_data)

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def export_markdown(results: BenchmarkResults, path: Path) -> str:
        """Export benchmark results to Markdown report. Returns the report text."""
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        lines.append("# Cascade Shield Benchmark Report\n")
        lines.append("## Summary\n")
        lines.append(f"- **Total scenarios**: {results.total_scenarios}")
        for policy, count in results.wins.items():
            lines.append(f"- **{POLICY_LABELS.get(policy, policy)} wins**: {count}")
        lines.append(f"- **Ties**: {results.ties}")
        lines.append("")

        lines.append("## Detailed Results\n")
        lines.append("| Domain | Scenario | Metric | No Containment | Simple CB | Cascade Shield | Winner |")
        lines.append("|--------|----------|--------|----------------|-----------|----------------|--------|")

        for sr in results.scenarios:
            nc = sr.policy_results.get("no_containment")
            cb = sr.policy_results.get("simple_circuit_breaker")
            cs = sr.policy_results.get("cascade_shield")

            if not all([nc, cb, cs]):
                continue

            winner_label = POLICY_LABELS.get(sr.winner, sr.winner)

            lines.append(
                f"| {sr.domain} | {sr.scenario} | Min Availability | "
                f"{nc.min_availability:.4f} | {cb.min_availability:.4f} | "
                f"{cs.min_availability:.4f} | {winner_label} |"
            )
            lines.append(
                f"| | | Peak Affected | "
                f"{nc.peak_affected} | {cb.peak_affected} | "
                f"{cs.peak_affected} | |"
            )
            lines.append(
                f"| | | Cascade Count | "
                f"{nc.cascade_count} | {cb.cascade_count} | "
                f"{cs.cascade_count} | |"
            )
            lines.append(
                f"| | | Downtime Ticks | "
                f"{nc.downtime_ticks} | {cb.downtime_ticks} | "
                f"{cs.downtime_ticks} | |"
            )

        lines.append("\n## Methodology\n")
        lines.append("Each scenario was run with three policies under identical conditions:")
        lines.append("1. **No Containment**: No automatic response to failures")
        lines.append("2. **Simple Circuit Breaker**: Only circuit breakers for failing services")
        lines.append("3. **Cascade Shield**: Full intelligent containment with decision engine, "
                      "failover, rate limiting, isolation, and staged recovery")
        lines.append("")
        lines.append("All runs used the same random seed, failure scenarios, and duration. "
                      "Results are deterministic and reproducible.")
        lines.append("")
        lines.append("### Assumptions and Limitations")
        lines.append("- This is a simulation, not a production system test")
        lines.append("- Failure propagation is modeled, not measured from real traffic")
        lines.append("- The decision engine uses a heuristic, not an optimal algorithm")
        lines.append("- Results reflect the specific topology and failure patterns tested")
        lines.append("- Results are NOT cherry-picked; wins, losses, and ties are all reported")

        report = "\n".join(lines)
        with open(path, "w") as f:
            f.write(report)

        return report
