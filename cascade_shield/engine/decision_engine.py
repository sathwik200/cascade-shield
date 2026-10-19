"""Deterministic, explainable weighted-scoring decision engine.

Evaluates candidate containment actions based on service state, criticality,
blast radius, dependency impact, and recovery history. Selects the
highest-scoring feasible action with deterministic tie-breaking.

This is a heuristic decision engine, not a mathematically optimal or
machine-learned algorithm.
"""

from __future__ import annotations

from typing import Optional

from cascade_shield.models.service import (
    ServiceInstance,
    ContainmentAction,
    ImpactAnalysis,
    HealthState,
    CircuitState,
    FaultType,
    Criticality,
)
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.containment.policies import ContainmentManager
from cascade_shield.config import (
    WEIGHT_CRITICALITY,
    WEIGHT_BLAST_RADIUS,
    WEIGHT_FAILURE_SEVERITY,
    WEIGHT_DEPENDENCY_IMPACT,
    WEIGHT_FEASIBILITY,
    WEIGHT_RECOVERY_HISTORY,
    INFEASIBLE_PENALTY,
    CRITICALITY_SCORES,
    FAILURE_SEVERITY_SCORES,
    ACTION_OPEN_CIRCUIT_BREAKER,
    ACTION_RATE_LIMIT,
    ACTION_ISOLATE,
    ACTION_RESTART,
    ACTION_FAILOVER,
    ACTION_RETRY_WITH_BACKOFF,
    ACTION_DEFER_AND_ALERT,
    ACTION_RESTORE_TRAFFIC,
    RECOVERY_MAX_ATTEMPTS,
)


# Action priority for deterministic tie-breaking (lower = preferred)
ACTION_PRIORITY = {
    ACTION_OPEN_CIRCUIT_BREAKER: 1,
    ACTION_RATE_LIMIT: 2,
    ACTION_ISOLATE: 3,
    ACTION_FAILOVER: 4,
    ACTION_RETRY_WITH_BACKOFF: 5,
    ACTION_RESTART: 6,
    ACTION_RESTORE_TRAFFIC: 7,
    ACTION_DEFER_AND_ALERT: 8,
}

ALL_ACTIONS = list(ACTION_PRIORITY.keys())


class DecisionEngine:
    """Weighted-scoring decision engine for containment action selection."""

    def __init__(self, graph: DependencyGraph, containment: ContainmentManager):
        self._graph = graph
        self._containment = containment
        self._decision_log: list[dict] = []

    @property
    def decision_log(self) -> list[dict]:
        return list(self._decision_log)

    def evaluate(self, service_id: str) -> list[ContainmentAction]:
        """Generate, score, and rank candidate actions for a service.

        Returns list sorted by score descending, with the recommended
        action first.
        """
        svc = self._graph.get_service(service_id)
        impact = self._graph.analyze_impact(service_id)

        candidates = []
        for action_type in ALL_ACTIONS:
            action = ContainmentAction(
                action_type=action_type,
                target_service_id=service_id,
            )

            # Check feasibility
            action.feasible = self._check_feasibility(action_type, svc, impact)

            # Calculate score
            action.score = self._calculate_score(action_type, svc, impact)

            # Apply infeasible penalty
            if not action.feasible:
                action.score += INFEASIBLE_PENALTY

            # Generate explanation
            action.explanation = self._explain(action_type, svc, impact, action.feasible)

            candidates.append(action)

        # Sort by score descending, then by action priority for tie-breaking
        candidates.sort(
            key=lambda a: (-a.score, ACTION_PRIORITY.get(a.action_type, 99))
        )

        # Log decision
        self._decision_log.append({
            "service_id": service_id,
            "health": svc.health.value,
            "recommended": candidates[0].action_type if candidates else None,
            "scores": {a.action_type: round(a.score, 3) for a in candidates},
        })

        return candidates

    def recommend(self, service_id: str) -> ContainmentAction:
        """Get the single best recommended action."""
        candidates = self.evaluate(service_id)
        return candidates[0]

    # ----- Feasibility Checks -----

    def _check_feasibility(self, action_type: str, svc: ServiceInstance,
                          impact: ImpactAnalysis) -> bool:
        """Check if an action is feasible for the current service state."""
        if action_type == ACTION_OPEN_CIRCUIT_BREAKER:
            # Can't open an already-open circuit
            return svc.circuit_state != CircuitState.OPEN

        elif action_type == ACTION_RATE_LIMIT:
            # Can't rate-limit an already-rate-limited or failed service
            return not svc.is_rate_limited and svc.health != HealthState.FAILED

        elif action_type == ACTION_ISOLATE:
            # Can't isolate an already-isolated service
            return svc.health != HealthState.ISOLATED

        elif action_type == ACTION_RESTART:
            # Can only restart failed/degraded services with remaining attempts
            return (svc.health in (HealthState.FAILED, HealthState.DEGRADED, HealthState.ISOLATED)
                    and svc.recovery_attempts < RECOVERY_MAX_ATTEMPTS)

        elif action_type == ACTION_FAILOVER:
            # Need a valid, healthy backup
            backup_id = svc.definition.backup_service_id
            if not backup_id or not self._graph.has_service(backup_id):
                return False
            backup = self._graph.get_service(backup_id)
            if backup.health in (HealthState.FAILED, HealthState.ISOLATED):
                return False
            # Check not already failed over
            if svc.active_backup_id:
                return False
            return True

        elif action_type == ACTION_RETRY_WITH_BACKOFF:
            # Can retry if attempts remain
            return (self._containment.retry_policy.should_retry(svc.service_id)
                    and svc.health in (HealthState.DEGRADED, HealthState.FAILED))

        elif action_type == ACTION_DEFER_AND_ALERT:
            # Always feasible
            return True

        elif action_type == ACTION_RESTORE_TRAFFIC:
            # Only for recovering services
            return svc.health == HealthState.RECOVERING

        return True

    # ----- Score Calculation -----

    def _calculate_score(self, action_type: str, svc: ServiceInstance,
                        impact: ImpactAnalysis) -> float:
        """Calculate weighted score for an action."""
        criticality_score = CRITICALITY_SCORES.get(svc.criticality.value, 0.5)
        blast_score = min(impact.blast_radius / max(self._graph.service_count - 1, 1), 1.0)
        failure_score = self._get_failure_severity(svc)
        dep_impact_score = len(impact.critical_services_at_risk) / max(self._graph.service_count, 1)
        recovery_penalty = svc.recovery_attempts / RECOVERY_MAX_ATTEMPTS

        # Base score from weighted factors
        base = (
            WEIGHT_CRITICALITY * criticality_score
            + WEIGHT_BLAST_RADIUS * blast_score
            + WEIGHT_FAILURE_SEVERITY * failure_score
            + WEIGHT_DEPENDENCY_IMPACT * dep_impact_score
            - WEIGHT_RECOVERY_HISTORY * recovery_penalty
        )

        # Action-specific modifiers
        modifier = self._action_modifier(action_type, svc, impact)

        return base + modifier

    def _get_failure_severity(self, svc: ServiceInstance) -> float:
        """Get failure severity score for a service."""
        if svc.active_failure:
            return FAILURE_SEVERITY_SCORES.get(svc.active_failure.fault_type.value, 0.5)
        if svc.health == HealthState.FAILED:
            return 1.0
        if svc.health == HealthState.DEGRADED:
            return 0.4
        if svc.health == HealthState.ISOLATED:
            return 0.8
        return 0.0

    def _action_modifier(self, action_type: str, svc: ServiceInstance,
                        impact: ImpactAnalysis) -> float:
        """Calculate action-specific score modifier."""
        if action_type == ACTION_OPEN_CIRCUIT_BREAKER:
            # Good for high-blast-radius failures
            return 0.15 if impact.blast_radius > 2 else 0.05

        elif action_type == ACTION_RATE_LIMIT:
            # Good for latency/error issues
            if svc.active_failure and svc.active_failure.fault_type in (
                FaultType.HIGH_LATENCY, FaultType.HIGH_ERROR_RATE
            ):
                return 0.12
            return 0.02

        elif action_type == ACTION_ISOLATE:
            # Good for critical failures with large blast radius
            if svc.health == HealthState.FAILED and impact.blast_radius > 3:
                return 0.18
            return 0.0

        elif action_type == ACTION_RESTART:
            # Good when the direct failure is expired
            if svc.active_failure is None and svc.health in (HealthState.FAILED, HealthState.ISOLATED):
                return 0.15
            return -0.05  # Less useful during active failure

        elif action_type == ACTION_FAILOVER:
            # Good for critical services with backups
            if svc.criticality in (Criticality.CRITICAL, Criticality.HIGH):
                return 0.20
            return 0.08

        elif action_type == ACTION_RETRY_WITH_BACKOFF:
            # Good for transient failures
            if svc.active_failure and svc.active_failure.fault_type in (
                FaultType.TIMEOUT, FaultType.HIGH_ERROR_RATE
            ):
                return 0.10
            return 0.0

        elif action_type == ACTION_DEFER_AND_ALERT:
            # Baseline low-priority action
            return -0.10

        elif action_type == ACTION_RESTORE_TRAFFIC:
            # Only useful for recovering services
            if svc.health == HealthState.RECOVERING:
                return 0.15
            return -0.20

        return 0.0

    # ----- Explanations -----

    def _explain(self, action_type: str, svc: ServiceInstance,
                impact: ImpactAnalysis, feasible: bool) -> str:
        """Generate human-readable explanation for action selection."""
        parts = []

        if not feasible:
            parts.append(f"INFEASIBLE: ")

        crit = svc.criticality.value
        health = svc.health.value
        blast = impact.blast_radius
        at_risk = len(impact.critical_services_at_risk)

        if action_type == ACTION_OPEN_CIRCUIT_BREAKER:
            parts.append(
                f"Open circuit breaker for {svc.display_name} "
                f"({crit} criticality, {health} health). "
                f"Blast radius: {blast} services. "
                f"Prevents further request propagation to a failing service."
            )
            if svc.circuit_state == CircuitState.OPEN:
                parts.append("Circuit is already open.")

        elif action_type == ACTION_RATE_LIMIT:
            parts.append(
                f"Apply rate limiting to {svc.display_name} "
                f"to reduce request volume and prevent overload. "
                f"Current health: {health}."
            )

        elif action_type == ACTION_ISOLATE:
            parts.append(
                f"Isolate {svc.display_name} ({crit} criticality) "
                f"to contain failure spread. "
                f"{at_risk} critical services at risk from blast radius of {blast}."
            )

        elif action_type == ACTION_RESTART:
            parts.append(
                f"Restart {svc.display_name} ({health}). "
                f"Recovery attempts: {svc.recovery_attempts}/{RECOVERY_MAX_ATTEMPTS}."
            )

        elif action_type == ACTION_FAILOVER:
            backup_id = svc.definition.backup_service_id or "none"
            parts.append(
                f"Failover {svc.display_name} to backup '{backup_id}'. "
                f"Service is {health} with blast radius {blast}."
            )
            if not svc.definition.backup_service_id:
                parts.append("No backup configured.")

        elif action_type == ACTION_RETRY_WITH_BACKOFF:
            retry_state = self._containment.retry_policy.get_state(svc.service_id)
            parts.append(
                f"Retry with exponential backoff for {svc.display_name}. "
                f"Attempts: {retry_state.attempts}/{self._containment.retry_policy.max_attempts}."
            )

        elif action_type == ACTION_DEFER_AND_ALERT:
            parts.append(
                f"Defer action for {svc.display_name} and generate alert. "
                f"Low-priority passive response."
            )

        elif action_type == ACTION_RESTORE_TRAFFIC:
            parts.append(
                f"Restore traffic to {svc.display_name} "
                f"(currently at {svc.traffic_percentage:.0%}). "
                f"Service health: {health}."
            )

        return " ".join(parts)

    def reset(self) -> None:
        """Clear decision history."""
        self._decision_log.clear()
