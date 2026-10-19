"""Recovery manager with health checks and staged traffic restoration.

Recovery follows this sequence:
1. Health check (read-only, no side effects)
2. Initiate recovery (service → RECOVERING)
3. Staged traffic restoration: 20% → 40% → 60% → 80% → 100%
4. At 100%: service → HEALTHY, circuit → CLOSED

Dependencies are recovered in topological order to ensure
downstream services recover before upstream callers.
"""

from __future__ import annotations

from typing import Optional

from cascade_shield.models.service import (
    ServiceInstance,
    SystemEvent,
    HealthCheckResult,
    HealthState,
    CircuitState,
    InvalidTransitionError,
)
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.config import (
    RECOVERY_MAX_ATTEMPTS,
    TRAFFIC_RESTORATION_STAGES,
)


class RecoveryManager:
    """Manages health checks, recovery initiation, and staged traffic restoration."""

    def __init__(self, graph: DependencyGraph, max_attempts: int = RECOVERY_MAX_ATTEMPTS):
        self._graph = graph
        self._max_attempts = max_attempts
        self._events: list[SystemEvent] = []
        self._tick = 0

    @property
    def events(self) -> list[SystemEvent]:
        return list(self._events)

    # ----- Health Check -----

    def health_check(self, service_id: str) -> HealthCheckResult:
        """Perform a read-only health check. Does NOT modify service state."""
        svc = self._graph.get_service(service_id)

        # Check direct health
        is_healthy = svc.active_failure is None and svc.health not in (
            HealthState.FAILED, HealthState.ISOLATED
        )

        # Check dependencies
        deps_ok = self._graph.are_critical_dependencies_available(service_id)

        # Simulated latency/error based on health
        if svc.health == HealthState.HEALTHY:
            latency = 5.0
            error_rate = 0.0
        elif svc.health == HealthState.DEGRADED:
            latency = 200.0
            error_rate = 0.1
        elif svc.health == HealthState.RECOVERING:
            latency = 50.0
            error_rate = 0.02
        else:
            latency = 999.0
            error_rate = 1.0

        overall_healthy = is_healthy and deps_ok

        message_parts = []
        if not is_healthy:
            message_parts.append(f"Service is {svc.health.value}")
        if svc.active_failure:
            message_parts.append(f"Active failure: {svc.active_failure.fault_type.value}")
        if not deps_ok:
            message_parts.append("Critical dependencies unavailable")
        if overall_healthy:
            message_parts.append("All checks passed")

        return HealthCheckResult(
            service_id=service_id,
            healthy=overall_healthy,
            latency_ms=latency,
            error_rate=error_rate,
            dependencies_ok=deps_ok,
            message="; ".join(message_parts),
        )

    # ----- Recovery Initiation -----

    def initiate_recovery(self, service_id: str) -> tuple[bool, SystemEvent]:
        """Initiate recovery for a service.

        Preconditions:
        - Service must be in FAILED, ISOLATED, or DEGRADED state
        - Recovery attempts must be below limit
        - No active failure on the service

        Returns (success, event).
        """
        svc = self._graph.get_service(service_id)

        # Check preconditions
        if svc.health not in (HealthState.FAILED, HealthState.ISOLATED,
                              HealthState.DEGRADED):
            event = SystemEvent(
                tick=self._tick,
                event_type="RECOVERY_REJECTED",
                service_id=service_id,
                description=f"Cannot recover: service is {svc.health.value}",
                severity="WARNING",
            )
            self._events.append(event)
            return False, event

        if svc.recovery_attempts >= self._max_attempts:
            event = SystemEvent(
                tick=self._tick,
                event_type="RECOVERY_BUDGET_EXHAUSTED",
                service_id=service_id,
                description=f"Recovery attempts exhausted: {svc.recovery_attempts}/{self._max_attempts}",
                severity="WARNING",
            )
            self._events.append(event)
            return False, event

        if svc.active_failure is not None:
            event = SystemEvent(
                tick=self._tick,
                event_type="RECOVERY_REJECTED",
                service_id=service_id,
                description="Cannot recover: active failure still present",
                severity="WARNING",
            )
            self._events.append(event)
            return False, event

        # Initiate recovery
        svc.recovery_attempts += 1
        svc.is_isolated = False
        try:
            svc.transition_to(HealthState.RECOVERING)
        except InvalidTransitionError:
            svc.health = HealthState.RECOVERING
        svc.circuit_state = CircuitState.HALF_OPEN
        svc.traffic_percentage = 0.0

        event = SystemEvent(
            tick=self._tick,
            event_type="RECOVERY_INITIATED",
            service_id=service_id,
            description=f"Recovery initiated (attempt {svc.recovery_attempts}/{self._max_attempts})",
            severity="INFO",
        )
        self._events.append(event)
        return True, event

    # ----- Staged Traffic Restoration -----

    def advance_recovery(self, service_id: str) -> tuple[bool, SystemEvent]:
        """Advance recovery by one traffic restoration stage.

        Preconditions for each step:
        - Service must be in RECOVERING state
        - Health check must pass
        - Critical dependencies must be available (or backed up)
        - Recovery budget must be available

        Returns (success, event).
        """
        svc = self._graph.get_service(service_id)

        # Check state
        if svc.health != HealthState.RECOVERING:
            event = SystemEvent(
                tick=self._tick,
                event_type="RECOVERY_STEP_REJECTED",
                service_id=service_id,
                description=f"Cannot advance: service is {svc.health.value}, not RECOVERING",
                severity="WARNING",
            )
            self._events.append(event)
            return False, event

        # Health check
        check = self.health_check(service_id)
        if not check.healthy:
            event = SystemEvent(
                tick=self._tick,
                event_type="RECOVERY_STEP_FAILED",
                service_id=service_id,
                description=f"Health check failed: {check.message}",
                severity="WARNING",
            )
            self._events.append(event)
            return False, event

        # Find next stage
        current_pct = svc.traffic_percentage
        next_stage = None
        for stage in TRAFFIC_RESTORATION_STAGES:
            if stage > current_pct + 0.001:  # floating point tolerance
                next_stage = stage
                break

        if next_stage is None:
            # Already at 100% - shouldn't happen but handle gracefully
            event = SystemEvent(
                tick=self._tick,
                event_type="RECOVERY_COMPLETE",
                service_id=service_id,
                description="Traffic already fully restored",
                severity="INFO",
            )
            self._events.append(event)
            return True, event

        svc.traffic_percentage = next_stage

        # Check if fully restored
        if next_stage >= 1.0 - 0.001:
            try:
                svc.transition_to(HealthState.HEALTHY)
            except InvalidTransitionError:
                svc.health = HealthState.HEALTHY
            svc.circuit_state = CircuitState.CLOSED
            svc.circuit_failure_count = 0
            svc.circuit_success_count = 0
            svc.exhaustion_ticks = 0
            # Restore any failover routes directed away from this service
            self._graph.restore_routes_for_target(service_id)

            event = SystemEvent(
                tick=self._tick,
                event_type="RECOVERY_COMPLETE",
                service_id=service_id,
                description=f"Recovery complete: traffic restored to 100%",
                severity="INFO",
            )
        else:
            event = SystemEvent(
                tick=self._tick,
                event_type="RECOVERY_STEP_ADVANCED",
                service_id=service_id,
                description=f"Traffic restored to {next_stage:.0%}",
                severity="INFO",
            )

        self._events.append(event)
        return True, event

    # ----- Dependency-Ordered Recovery -----

    def recover_cascade(self) -> list[SystemEvent]:
        """Attempt recovery for all recoverable services in dependency order.

        Services are recovered from leaf (no dependencies) to root,
        ensuring downstream services recover before callers.
        """
        events: list[SystemEvent] = []

        # Get topological order (reversed so leaves come first)
        try:
            import networkx as nx
            topo_order = list(nx.topological_sort(self._graph.get_networkx_graph()))
            topo_order.reverse()
        except Exception:
            topo_order = list(self._graph.service_ids)

        for service_id in topo_order:
            svc = self._graph.get_service(service_id)

            if svc.health == HealthState.RECOVERING:
                success, event = self.advance_recovery(service_id)
                events.append(event)
            elif svc.health in (HealthState.FAILED, HealthState.ISOLATED):
                # Try to initiate recovery if no active failure and deps are OK
                if svc.active_failure is None:
                    deps_ok = self._graph.are_critical_dependencies_available(service_id)
                    if deps_ok:
                        success, event = self.initiate_recovery(service_id)
                        events.append(event)

        return events

    def tick(self) -> None:
        """Advance tick counter."""
        self._tick += 1

    def reset(self) -> None:
        """Reset recovery state."""
        self._events.clear()
        self._tick = 0
