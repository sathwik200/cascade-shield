"""Deterministic failure injection and cascading propagation simulator.

Models failure spread through dependency chains. Uses configurable
exhaustion periods and supports both critical and optional dependencies.
"""

from __future__ import annotations

import random
from typing import Optional

from cascade_shield.models.service import (
    ServiceInstance,
    FailureScenario,
    SystemEvent,
    HealthState,
    FaultType,
    CircuitState,
    InvalidTransitionError,
)
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.config import (
    FAILURE_DEFAULT_DURATION,
    FAILURE_EXHAUSTION_TICKS,
    FAILURE_CASCADE_PROBABILITY,
)


class FailureSimulator:
    """Injects failures and propagates cascading effects through dependencies."""

    def __init__(self, graph: DependencyGraph, seed: int = 42):
        self._graph = graph
        self._rng = random.Random(seed)
        self._tick = 0
        self._events: list[SystemEvent] = []
        self._failure_history: list[dict] = []
        self._cascade_count = 0
        self._active_containment: set[str] = set()  # services with active containment

    @property
    def tick(self) -> int:
        return self._tick

    @property
    def events(self) -> list[SystemEvent]:
        return list(self._events)

    @property
    def cascade_count(self) -> int:
        return self._cascade_count

    @property
    def failure_history(self) -> list[dict]:
        return list(self._failure_history)

    def set_contained(self, service_id: str) -> None:
        """Mark a service as having active containment (circuit breaker, isolation, etc.)."""
        self._active_containment.add(service_id)

    def clear_contained(self, service_id: str) -> None:
        """Remove containment marking."""
        self._active_containment.discard(service_id)

    def is_contained(self, service_id: str) -> bool:
        return service_id in self._active_containment

    # ----- Injection -----

    def inject_failure(self, scenario: FailureScenario) -> SystemEvent:
        """Inject a failure into a service."""
        svc = self._graph.get_service(scenario.target_service_id)

        svc.active_failure = scenario
        svc.failure_ticks_remaining = scenario.duration_ticks
        svc.exhaustion_ticks = 0

        # Determine initial health based on fault type
        if scenario.fault_type == FaultType.UNAVAILABLE:
            target_state = HealthState.FAILED
        elif scenario.fault_type in (FaultType.HIGH_LATENCY, FaultType.HIGH_ERROR_RATE, FaultType.TIMEOUT):
            target_state = HealthState.DEGRADED
        else:
            target_state = HealthState.DEGRADED

        try:
            svc.transition_to(target_state)
        except InvalidTransitionError:
            # Force the state if the transition is invalid from current state
            svc.health = target_state

        # Open circuit breaker for direct failures
        if scenario.fault_type == FaultType.UNAVAILABLE:
            svc.circuit_state = CircuitState.OPEN

        event = SystemEvent(
            tick=self._tick,
            event_type="FAILURE_INJECTED",
            service_id=scenario.target_service_id,
            description=f"Injected {scenario.fault_type.value} failure "
                       f"(severity={scenario.severity}, duration={scenario.duration_ticks})",
            severity="CRITICAL" if scenario.fault_type == FaultType.UNAVAILABLE else "WARNING",
        )
        self._events.append(event)
        self._failure_history.append({
            "tick": self._tick,
            "service_id": scenario.target_service_id,
            "fault_type": scenario.fault_type.value,
            "severity": scenario.severity,
            "duration": scenario.duration_ticks,
        })
        return event

    def inject_failures(self, scenarios: list[FailureScenario]) -> list[SystemEvent]:
        """Inject multiple simultaneous failures."""
        return [self.inject_failure(s) for s in scenarios]

    # ----- Simulation Step -----

    def step(self) -> list[SystemEvent]:
        """Advance the simulation by one tick."""
        self._tick += 1
        events: list[SystemEvent] = []

        # Phase 1: Tick down failure durations and expire
        events.extend(self._tick_failures())

        # Phase 2: Propagate cascading effects
        events.extend(self._propagate_cascades())

        # Phase 3: Heal services whose dependencies have recovered
        events.extend(self._heal_recovered())

        return events

    def _tick_failures(self) -> list[SystemEvent]:
        """Decrement failure timers and expire completed failures."""
        events: list[SystemEvent] = []
        for svc in self._graph.services.values():
            if svc.active_failure and svc.failure_ticks_remaining > 0:
                svc.failure_ticks_remaining -= 1
                if svc.failure_ticks_remaining <= 0:
                    events.append(self._expire_failure(svc))
        return events

    def _expire_failure(self, svc: ServiceInstance) -> SystemEvent:
        """Clear an expired failure."""
        fault_type = svc.active_failure.fault_type.value if svc.active_failure else "UNKNOWN"
        svc.active_failure = None
        svc.failure_ticks_remaining = 0
        svc.exhaustion_ticks = 0

        # If service is failed/degraded from direct failure, move to degraded
        # (not immediately healthy — callers need to re-check)
        if svc.health == HealthState.FAILED and not svc.is_isolated:
            svc.health = HealthState.DEGRADED
            svc.circuit_state = CircuitState.HALF_OPEN
        elif svc.health == HealthState.DEGRADED:
            # Check if critical deps are all OK
            if self._graph.are_critical_dependencies_available(svc.service_id):
                svc.health = HealthState.HEALTHY
                svc.circuit_state = CircuitState.CLOSED
                self.clear_contained(svc.service_id)

        event = SystemEvent(
            tick=self._tick,
            event_type="FAILURE_EXPIRED",
            service_id=svc.service_id,
            description=f"Failure expired ({fault_type}), service is now {svc.health.value}",
            severity="INFO",
        )
        self._events.append(event)
        return event

    def _propagate_cascades(self) -> list[SystemEvent]:
        """Propagate failures through dependency chains."""
        events: list[SystemEvent] = []
        services = list(self._graph.services.values())

        for svc in services:
            if svc.health in (HealthState.HEALTHY, HealthState.DEGRADED):
                events.extend(self._check_dependency_impact(svc))

        return events

    def _check_dependency_impact(self, svc: ServiceInstance) -> list[SystemEvent]:
        """Check if a service is affected by its dependencies' failures."""
        events: list[SystemEvent] = []
        service_id = svc.service_id

        critical_deps = self._graph.get_critical_dependencies(service_id)
        optional_deps = self._graph.get_optional_dependencies(service_id)

        # Check critical dependencies
        critical_unavailable = []
        for dep_id in critical_deps:
            if not self._graph.is_dependency_available(service_id, dep_id):
                # Check if the failing dependency has containment active
                if self.is_contained(dep_id):
                    # Containment prevents full cascade, but service degrades
                    if svc.health == HealthState.HEALTHY:
                        try:
                            svc.transition_to(HealthState.DEGRADED)
                            events.append(SystemEvent(
                                tick=self._tick,
                                event_type="DEGRADED_BY_CONTAINMENT",
                                service_id=service_id,
                                description=f"Degraded: critical dependency {dep_id} is contained",
                                severity="WARNING",
                            ))
                            self._events.append(events[-1])
                        except InvalidTransitionError:
                            pass
                else:
                    critical_unavailable.append(dep_id)

        if critical_unavailable:
            if svc.health == HealthState.HEALTHY:
                try:
                    svc.transition_to(HealthState.DEGRADED)
                    event = SystemEvent(
                        tick=self._tick,
                        event_type="CASCADE_DEGRADED",
                        service_id=service_id,
                        description=f"Degraded due to unavailable critical deps: {critical_unavailable}",
                        severity="WARNING",
                    )
                    self._events.append(event)
                    events.append(event)
                    self._cascade_count += 1
                except InvalidTransitionError:
                    pass

            elif svc.health == HealthState.DEGRADED:
                # Exhaustion: after N ticks without critical deps, fail
                svc.exhaustion_ticks += 1
                if svc.exhaustion_ticks >= FAILURE_EXHAUSTION_TICKS:
                    try:
                        svc.transition_to(HealthState.FAILED)
                        svc.circuit_state = CircuitState.OPEN
                        event = SystemEvent(
                            tick=self._tick,
                            event_type="CASCADE_FAILED",
                            service_id=service_id,
                            description=f"Failed after exhaustion: critical deps {critical_unavailable} "
                                       f"unavailable for {svc.exhaustion_ticks} ticks",
                            severity="CRITICAL",
                        )
                        self._events.append(event)
                        events.append(event)
                        self._cascade_count += 1
                    except InvalidTransitionError:
                        pass

        # Check optional dependencies - only degrade, never fail
        for dep_id in optional_deps:
            if not self._graph.is_dependency_available(service_id, dep_id):
                if svc.health == HealthState.HEALTHY:
                    try:
                        svc.transition_to(HealthState.DEGRADED)
                        event = SystemEvent(
                            tick=self._tick,
                            event_type="DEGRADED_OPTIONAL",
                            service_id=service_id,
                            description=f"Degraded: optional dependency {dep_id} unavailable",
                            severity="INFO",
                        )
                        self._events.append(event)
                        events.append(event)
                    except InvalidTransitionError:
                        pass

        return events

    def _heal_recovered(self) -> list[SystemEvent]:
        """Heal services whose dependencies have all recovered."""
        events: list[SystemEvent] = []
        services = list(self._graph.services.values())

        for svc in services:
            if svc.health == HealthState.DEGRADED and svc.active_failure is None:
                if self._graph.are_all_dependencies_available(svc.service_id):
                    # Reset exhaustion
                    svc.exhaustion_ticks = 0
                    try:
                        svc.transition_to(HealthState.HEALTHY)
                        svc.circuit_state = CircuitState.CLOSED
                        self.clear_contained(svc.service_id)
                        event = SystemEvent(
                            tick=self._tick,
                            event_type="AUTO_HEALED",
                            service_id=svc.service_id,
                            description="Healed: all dependencies available",
                            severity="INFO",
                        )
                        self._events.append(event)
                        events.append(event)
                    except InvalidTransitionError:
                        pass

        return events

    # ----- Clear -----

    def clear_failure(self, service_id: str) -> SystemEvent:
        """Manually clear a failure from a service."""
        svc = self._graph.get_service(service_id)
        svc.active_failure = None
        svc.failure_ticks_remaining = 0
        svc.exhaustion_ticks = 0

        if self._graph.are_critical_dependencies_available(service_id):
            svc.health = HealthState.HEALTHY
            svc.circuit_state = CircuitState.CLOSED
            self.clear_contained(service_id)
        else:
            svc.health = HealthState.DEGRADED
            svc.circuit_state = CircuitState.HALF_OPEN

        event = SystemEvent(
            tick=self._tick,
            event_type="FAILURE_CLEARED",
            service_id=service_id,
            description="Failure manually cleared",
            severity="INFO",
        )
        self._events.append(event)
        return event

    def clear_all_failures(self) -> list[SystemEvent]:
        """Clear all active failures."""
        events = []
        for svc in self._graph.services.values():
            if svc.active_failure:
                events.append(self.clear_failure(svc.service_id))
        return events

    # ----- Reset -----

    def reset(self) -> None:
        """Reset simulator state."""
        self._tick = 0
        self._events.clear()
        self._failure_history.clear()
        self._cascade_count = 0
        self._active_containment.clear()
