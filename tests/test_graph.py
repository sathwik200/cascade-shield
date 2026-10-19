"""Unit tests for cascade_shield.graph.dependency_graph."""

import pytest
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.models.service import (
    ServiceDefinition,
    DependencyEdge,
    Criticality,
    HealthState,
    ServiceNotFoundError,
)


def create_simple_graph() -> DependencyGraph:
    graph = DependencyGraph()
    # A -> B -> C
    graph.add_service(ServiceDefinition("gateway", "Gateway", Criticality.CRITICAL))
    graph.add_service(ServiceDefinition("order_service", "Order Service", Criticality.CRITICAL, backup_service_id="order_backup"))
    graph.add_service(ServiceDefinition("order_backup", "Order Backup", Criticality.HIGH))
    graph.add_service(ServiceDefinition("database", "Database", Criticality.CRITICAL))

    graph.add_dependency(DependencyEdge("gateway", "order_service", is_critical=True))
    graph.add_dependency(DependencyEdge("order_service", "database", is_critical=True))
    graph.add_dependency(DependencyEdge("order_backup", "database", is_critical=True))
    return graph


def test_service_registration():
    graph = DependencyGraph()
    sd = ServiceDefinition("svc_a", "Service A")
    inst = graph.add_service(sd)

    assert graph.has_service("svc_a")
    assert graph.get_service("svc_a") is inst
    assert graph.service_count == 1
    assert "svc_a" in graph.service_ids

    # Duplicate raises
    with pytest.raises(ValueError, match="already registered"):
        graph.add_service(sd)

    # Missing lookup raises
    with pytest.raises(ServiceNotFoundError):
        graph.get_service("missing_id")


def test_dependency_registration_and_validation():
    graph = DependencyGraph()
    graph.add_service(ServiceDefinition("s1", "S1"))
    graph.add_service(ServiceDefinition("s2", "S2"))

    # Missing source/target
    with pytest.raises(ServiceNotFoundError):
        graph.add_dependency(DependencyEdge("s1", "s3"))
    with pytest.raises(ServiceNotFoundError):
        graph.add_dependency(DependencyEdge("s3", "s2"))

    # Self-dependency
    with pytest.raises(ValueError, match="Self-dependency not allowed"):
        graph.add_dependency(DependencyEdge("s1", "s1"))

    edge = DependencyEdge("s1", "s2", is_critical=True, latency_ms=15.0)
    graph.add_dependency(edge)
    assert graph.edge_count == 1
    assert graph.get_dependency("s1", "s2") == edge
    assert graph.get_dependency("s2", "s1") is None


def test_dependency_queries():
    graph = create_simple_graph()

    assert graph.get_dependencies("gateway") == ["order_service"]
    assert graph.get_critical_dependencies("gateway") == ["order_service"]
    assert graph.get_optional_dependencies("gateway") == []

    # Direct dependents (incoming edges)
    assert graph.get_direct_dependents("order_service") == ["gateway"]
    assert sorted(graph.get_direct_dependents("database")) == ["order_backup", "order_service"]

    # Transitive dependents
    assert graph.get_transitive_dependents("database") == ["gateway", "order_backup", "order_service"]


def test_impact_analysis():
    graph = create_simple_graph()
    impact = graph.analyze_impact("database")

    assert impact.failed_service_id == "database"
    assert "order_service" in impact.directly_affected
    assert "gateway" in impact.transitively_affected
    assert impact.blast_radius == 3  # gateway, order_service, order_backup
    assert len(impact.critical_services_at_risk) >= 2


def test_failover_routing_and_restoration():
    graph = create_simple_graph()

    # Apply failover from order_service to order_backup for caller 'gateway'
    success = graph.apply_failover("gateway", "order_service", "order_backup")
    assert success
    assert graph.get_active_route("gateway", "order_service") == "order_backup"
    assert graph.is_dependency_available("gateway", "order_service")

    # Duplicate failover returns False
    assert not graph.apply_failover("gateway", "order_service", "order_backup")

    # Restore route for target
    restored = graph.restore_routes_for_target("order_service")
    assert restored == [("gateway", "order_service")]
    assert graph.get_active_route("gateway", "order_service") is None


def test_topology_validation_cycles():
    graph = DependencyGraph()
    graph.add_service(ServiceDefinition("s1", "S1"))
    graph.add_service(ServiceDefinition("s2", "S2"))
    graph.add_dependency(DependencyEdge("s1", "s2"))
    graph.add_dependency(DependencyEdge("s2", "s1"))

    errors = graph.validate()
    assert any("Circular dependency" in e for e in errors)


def test_reset_and_clear():
    graph = create_simple_graph()
    graph.apply_failover("gateway", "order_service", "order_backup")
    graph.get_service("order_service").health = HealthState.FAILED

    graph.reset()
    assert graph.get_service("order_service").health == HealthState.HEALTHY
    assert len(graph.active_routes) == 0

    graph.clear()
    assert graph.service_count == 0
    assert graph.edge_count == 0
