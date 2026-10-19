"""Unit tests for cascade_shield.models.service."""

import pytest
from cascade_shield.models.service import (
    HealthState,
    CircuitState,
    Criticality,
    FaultType,
    ServiceDefinition,
    ServiceInstance,
    DependencyEdge,
    FailureScenario,
    ImpactAnalysis,
    ContainmentAction,
    SystemEvent,
    MetricSnapshot,
    HealthCheckResult,
    ExperimentConfig,
    InvalidTransitionError,
)
from cascade_shield.config import (
    HEALTH_HEALTHY,
    HEALTH_DEGRADED,
    HEALTH_FAILED,
    HEALTH_ISOLATED,
    HEALTH_RECOVERING,
    ACTION_OPEN_CIRCUIT_BREAKER,
)


def test_service_definition_validation():
    # Valid definition
    sd = ServiceDefinition(service_id="svc_1", display_name="Service 1")
    assert sd.service_id == "svc_1"
    assert sd.criticality == Criticality.MEDIUM
    assert sd.retry_limit == 3
    assert sd.timeout == 5.0
    assert sd.rate_limit == 10

    # Invalid empty ID
    with pytest.raises(ValueError, match="service_id must be non-empty"):
        ServiceDefinition(service_id="", display_name="Bad Service")

    # Invalid retry limit
    with pytest.raises(ValueError, match="retry_limit must be >= 0"):
        ServiceDefinition(service_id="s", display_name="S", retry_limit=-1)

    # Invalid timeout
    with pytest.raises(ValueError, match="timeout must be > 0"):
        ServiceDefinition(service_id="s", display_name="S", timeout=0.0)

    # Invalid rate limit
    with pytest.raises(ValueError, match="rate_limit must be >= 0"):
        ServiceDefinition(service_id="s", display_name="S", rate_limit=-5)


def test_service_instance_lifecycle_and_transitions():
    sd = ServiceDefinition(service_id="orders", display_name="Orders", criticality=Criticality.HIGH)
    inst = ServiceInstance(definition=sd)

    assert inst.service_id == "orders"
    assert inst.display_name == "Orders"
    assert inst.criticality == Criticality.HIGH
    assert inst.health == HealthState.HEALTHY
    assert inst.circuit_state == CircuitState.CLOSED

    # Valid transitions
    inst.transition_to(HealthState.DEGRADED)
    assert inst.health == HealthState.DEGRADED

    inst.transition_to(HealthState.FAILED)
    assert inst.health == HealthState.FAILED

    inst.transition_to(HealthState.ISOLATED)
    assert inst.health == HealthState.ISOLATED

    inst.transition_to(HealthState.RECOVERING)
    assert inst.health == HealthState.RECOVERING

    inst.transition_to(HealthState.HEALTHY)
    assert inst.health == HealthState.HEALTHY

    # Self-transition is a no-op
    inst.transition_to(HealthState.HEALTHY)
    assert inst.health == HealthState.HEALTHY

    # Invalid transition (HEALTHY -> RECOVERING is not allowed)
    with pytest.raises(InvalidTransitionError):
        inst.transition_to(HealthState.RECOVERING)


def test_service_instance_reset():
    sd = ServiceDefinition(service_id="auth", display_name="Auth")
    inst = ServiceInstance(definition=sd)
    inst.health = HealthState.FAILED
    inst.circuit_state = CircuitState.OPEN
    inst.circuit_failure_count = 5
    inst.traffic_percentage = 0.4
    inst.is_isolated = True
    inst.active_backup_id = "auth_backup"

    inst.reset()
    assert inst.health == HealthState.HEALTHY
    assert inst.circuit_state == CircuitState.CLOSED
    assert inst.circuit_failure_count == 0
    assert inst.traffic_percentage == 1.0
    assert not inst.is_isolated
    assert inst.active_backup_id is None


def test_failure_scenario_validation():
    sc = FailureScenario(
        target_service_id="db",
        fault_type=FaultType.UNAVAILABLE,
        duration_ticks=10,
        severity=1.0,
    )
    assert sc.target_service_id == "db"
    assert sc.duration_ticks == 10

    # Invalid duration
    with pytest.raises(ValueError, match="duration_ticks must be >= 1"):
        FailureScenario(target_service_id="db", fault_type=FaultType.TIMEOUT, duration_ticks=0)

    # Clamped severity
    sc2 = FailureScenario(target_service_id="db", fault_type=FaultType.TIMEOUT, severity=2.5)
    assert sc2.severity == 1.0
    sc3 = FailureScenario(target_service_id="db", fault_type=FaultType.TIMEOUT, severity=-0.5)
    assert sc3.severity == 0.0


def test_containment_action_properties():
    act = ContainmentAction(
        action_type=ACTION_OPEN_CIRCUIT_BREAKER,
        target_service_id="api_gateway",
        timestamp=4,
    )
    assert act.action_id == f"{ACTION_OPEN_CIRCUIT_BREAKER}:api_gateway:4"
    assert not act.executed
    assert not act.success


def test_other_dataclasses():
    edge = DependencyEdge(source_id="a", target_id="b", is_critical=True, latency_ms=12.5)
    assert edge.source_id == "a"
    assert edge.target_id == "b"

    impact = ImpactAnalysis(
        failed_service_id="db",
        directly_affected=["orders"],
        transitively_affected=["gateway"],
        blast_radius=2,
    )
    assert impact.blast_radius == 2

    event = SystemEvent(tick=1, event_type="TEST", service_id="s1")
    assert event.event_id is not None
    assert event.tick == 1

    snap = MetricSnapshot(tick=2, effective_availability=0.9)
    assert snap.tick == 2
    assert snap.effective_availability == 0.9

    chk = HealthCheckResult(service_id="s1", healthy=True)
    assert chk.healthy

    cfg = ExperimentConfig(name="exp1", domain="ecommerce")
    assert cfg.name == "exp1"
