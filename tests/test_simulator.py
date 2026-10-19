"""Unit tests for cascade_shield.failure.simulator."""

# pyrefly: ignore[missing-import]
import pytest
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.models.service import (
    ServiceDefinition,
    DependencyEdge,
    FailureScenario,
    HealthState,
    FaultType,
    CircuitState,
)
from cascade_shield.failure.simulator import FailureSimulator


def build_test_chain() -> DependencyGraph:
    g = DependencyGraph()
    # A -> B (critical), A -> C (optional)
    g.add_service(ServiceDefinition("A", "Service A"))
    g.add_service(ServiceDefinition("B", "Service B"))
    g.add_service(ServiceDefinition("C", "Service C"))

    g.add_dependency(DependencyEdge("A", "B", is_critical=True))
    g.add_dependency(DependencyEdge("A", "C", is_critical=False))
    return g


def test_failure_injection():
    graph = build_test_chain()
    sim = FailureSimulator(graph, seed=42)

    scenario = FailureScenario(
        target_service_id="B",
        fault_type=FaultType.UNAVAILABLE,
        duration_ticks=5,
        severity=1.0,
    )
    event = sim.inject_failure(scenario)
    b = graph.get_service("B")

    assert b.health == HealthState.FAILED
    assert b.circuit_state == CircuitState.OPEN
    assert b.failure_ticks_remaining == 5
    assert event.event_type == "FAILURE_INJECTED"
    assert event.service_id == "B"


def test_cascade_propagation_and_exhaustion():
    graph = build_test_chain()
    sim = FailureSimulator(graph, seed=42)

    # Inject failure into critical dependency B
    sim.inject_failure(FailureScenario("B", FaultType.UNAVAILABLE, duration_ticks=10))

    # Tick 1: A should become degraded due to unavailable critical dependency B
    sim.step()
    a = graph.get_service("A")
    assert a.health == HealthState.DEGRADED

    # Exhaustion ticks default is 3
    # Tick 2, 3: A stays degraded and increases exhaustion_ticks
    sim.step()
    sim.step()
    assert a.health == HealthState.DEGRADED

    # Tick 4: Exhaustion threshold reached, A cascades to FAILED
    sim.step()
    assert a.health == HealthState.FAILED
    assert a.circuit_state == CircuitState.OPEN
    assert sim.cascade_count >= 1


def test_optional_dependency_cascade():
    graph = build_test_chain()
    sim = FailureSimulator(graph, seed=42)

    # Inject failure into optional dependency C
    sim.inject_failure(FailureScenario("C", FaultType.UNAVAILABLE, duration_ticks=10))

    sim.step()
    a = graph.get_service("A")
    # Optional dependency failure degrades A, but should never fail it
    assert a.health == HealthState.DEGRADED

    # Step 5 more ticks (exceeding FAILURE_EXHAUSTION_TICKS=3)
    for _ in range(5):
        sim.step()
    # A remains DEGRADED, not FAILED
    assert a.health == HealthState.DEGRADED

    # After failure expires (another 5 ticks), C recovers and A heals
    for _ in range(5):
        sim.step()
    assert a.health == HealthState.HEALTHY


def test_containment_prevents_full_cascade():
    graph = build_test_chain()
    sim = FailureSimulator(graph, seed=42)

    sim.inject_failure(FailureScenario("B", FaultType.UNAVAILABLE, duration_ticks=10))
    # Mark B as contained (e.g. circuit breaker opened)
    sim.set_contained("B")
    assert sim.is_contained("B")

    # Step simulation multiple ticks
    for _ in range(6):
        sim.step()

    a = graph.get_service("A")
    # Because B was contained, A only degraded and did not cascade-fail
    assert a.health == HealthState.DEGRADED


def test_auto_heal_when_dependency_recovers():
    graph = build_test_chain()
    sim = FailureSimulator(graph, seed=42)

    # B fails for only 2 ticks
    sim.inject_failure(FailureScenario("B", FaultType.UNAVAILABLE, duration_ticks=2))

    sim.step()  # Tick 1: B failed, A degraded
    assert graph.get_service("A").health == HealthState.DEGRADED

    sim.step()  # Tick 2: failure expires on B
    sim.step()  # Tick 3: B heals, A auto-heals

    assert graph.get_service("B").health == HealthState.HEALTHY
    assert graph.get_service("A").health == HealthState.HEALTHY


def test_manual_clear_and_reset():
    graph = build_test_chain()
    sim = FailureSimulator(graph, seed=42)

    sim.inject_failure(FailureScenario("B", FaultType.UNAVAILABLE, duration_ticks=10))
    sim.clear_failure("B")

    b = graph.get_service("B")
    assert b.active_failure is None
    assert b.health == HealthState.HEALTHY

    sim.reset()
    assert sim.tick == 0
    assert len(sim.events) == 0
    assert sim.cascade_count == 0
