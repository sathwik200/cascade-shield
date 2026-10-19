"""Unit tests for cascade_shield.recovery.manager."""

import pytest
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.models.service import (
    ServiceDefinition,
    DependencyEdge,
    HealthState,
    CircuitState,
    FailureScenario,
    FaultType,
)
from cascade_shield.recovery.manager import RecoveryManager


def build_recovery_graph() -> DependencyGraph:
    g = DependencyGraph()
    # A -> B -> C
    g.add_service(ServiceDefinition("A", "Service A"))
    g.add_service(ServiceDefinition("B", "Service B", backup_service_id="B_backup"))
    g.add_service(ServiceDefinition("B_backup", "Service B Backup"))
    g.add_service(ServiceDefinition("C", "Service C"))

    g.add_dependency(DependencyEdge("A", "B", is_critical=True))
    g.add_dependency(DependencyEdge("B", "C", is_critical=True))
    g.add_dependency(DependencyEdge("B_backup", "C", is_critical=True))
    return g


def test_health_check_read_only():
    graph = build_recovery_graph()
    rm = RecoveryManager(graph)

    # Initial state
    chk1 = rm.health_check("C")
    assert chk1.healthy
    assert chk1.dependencies_ok
    assert graph.get_service("C").health == HealthState.HEALTHY

    # Failed service
    graph.get_service("C").health = HealthState.FAILED
    chk2 = rm.health_check("C")
    assert not chk2.healthy
    assert graph.get_service("C").health == HealthState.FAILED  # Health check did not change state

    # Service with missing dependency
    chk_b = rm.health_check("B")
    assert not chk_b.dependencies_ok
    assert not chk_b.healthy


def test_initiate_recovery_lifecycle():
    graph = build_recovery_graph()
    rm = RecoveryManager(graph, max_attempts=2)
    svc = graph.get_service("C")

    # Reject recovery when healthy
    ok, evt = rm.initiate_recovery("C")
    assert not ok
    assert evt.event_type == "RECOVERY_REJECTED"

    # Reject recovery when active failure is ongoing
    svc.health = HealthState.FAILED
    svc.active_failure = FailureScenario("C", FaultType.UNAVAILABLE, duration_ticks=5)
    ok, evt = rm.initiate_recovery("C")
    assert not ok
    assert "active failure" in evt.description

    # Clear active failure -> recovery succeeds
    svc.active_failure = None
    ok, evt = rm.initiate_recovery("C")
    assert ok
    assert evt.event_type == "RECOVERY_INITIATED"
    assert svc.health == HealthState.RECOVERING
    assert svc.circuit_state == CircuitState.HALF_OPEN
    assert svc.traffic_percentage == 0.0
    assert svc.recovery_attempts == 1


def test_advance_recovery_staged_traffic():
    graph = build_recovery_graph()
    rm = RecoveryManager(graph)
    svc = graph.get_service("C")

    # Fail and initiate
    svc.health = HealthState.FAILED
    rm.initiate_recovery("C")

    # Staged restoration: 20%, 40%, 60%, 80%, 100%
    expected_stages = [0.2, 0.4, 0.6, 0.8, 1.0]
    for stage in expected_stages:
        ok, evt = rm.advance_recovery("C")
        assert ok
        assert abs(svc.traffic_percentage - stage) < 0.01
        if stage < 1.0:
            assert svc.health == HealthState.RECOVERING
            assert evt.event_type == "RECOVERY_STEP_ADVANCED"

    # At 100%, service is healthy and circuit closed
    assert svc.health == HealthState.HEALTHY
    assert svc.circuit_state == CircuitState.CLOSED


def test_staged_recovery_restores_failover_routes():
    graph = build_recovery_graph()
    rm = RecoveryManager(graph)

    # Fail B and failover A -> B_backup
    graph.get_service("B").health = HealthState.FAILED
    graph.apply_failover("A", "B", "B_backup")
    assert graph.get_active_route("A", "B") == "B_backup"

    # Recover B through all stages
    rm.initiate_recovery("B")
    for _ in range(5):
        rm.advance_recovery("B")

    assert graph.get_service("B").health == HealthState.HEALTHY
    # Failover route should have been automatically restored
    assert graph.get_active_route("A", "B") is None


def test_recover_cascade_topological_order():
    graph = build_recovery_graph()
    rm = RecoveryManager(graph)

    # Both C and B are failed (no active failure)
    graph.get_service("C").health = HealthState.FAILED
    graph.get_service("B").health = HealthState.FAILED

    # B cannot initiate recovery because C is unavailable.
    # But C (leaf) can initiate!
    events = rm.recover_cascade()
    c_initiated = any(e.service_id == "C" and e.event_type == "RECOVERY_INITIATED" for e in events)
    assert c_initiated
    b_initiated = any(e.service_id == "B" and e.event_type == "RECOVERY_INITIATED" for e in events)
    assert not b_initiated  # B cannot recover until C is healthy
