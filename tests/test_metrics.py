"""Unit tests for cascade_shield.metrics.collector."""

import pytest
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.models.service import (
    ServiceDefinition,
    Criticality,
    HealthState,
    FailureScenario,
    FaultType,
)
from cascade_shield.metrics.collector import MetricsCollector


def test_metrics_collector_empty_graph():
    graph = DependencyGraph()
    mc = MetricsCollector(graph)
    snap = mc.snapshot()

    assert snap.effective_availability == 1.0
    assert snap.critical_availability == 1.0
    assert snap.total_services == 0


def test_availability_calculation():
    graph = DependencyGraph()
    graph.add_service(ServiceDefinition("s1", "S1", Criticality.CRITICAL))
    graph.add_service(ServiceDefinition("s2", "S2", Criticality.HIGH))
    graph.add_service(ServiceDefinition("s3", "S3", Criticality.LOW))
    graph.add_service(ServiceDefinition("s4", "S4", Criticality.LOW))

    mc = MetricsCollector(graph)

    # Initial: 4 healthy -> 1.0
    snap = mc.snapshot()
    assert snap.effective_availability == 1.0
    assert snap.critical_availability == 1.0

    # s1 degraded (0.5), s2 failed (0.0), s3 healthy (1.0), s4 healthy (1.0)
    # Total = (1 + 1 + 0.5 + 0) / 4 = 2.5 / 4 = 0.625
    # Critical only (s1, s2): (0 + 0.5 * 1) / 2 = 0.25
    graph.get_service("s1").health = HealthState.DEGRADED
    graph.get_service("s2").health = HealthState.FAILED

    snap2 = mc.tick()
    assert abs(snap2.effective_availability - 0.625) < 0.001
    assert abs(snap2.critical_availability - 0.25) < 0.001


def test_aggregations():
    graph = DependencyGraph()
    graph.add_service(ServiceDefinition("s1", "S1"))
    graph.add_service(ServiceDefinition("s2", "S2"))

    mc = MetricsCollector(graph)

    # Tick 0: 1.0
    mc.snapshot()

    # Tick 1: s1 fails -> avail = 0.5
    graph.get_service("s1").health = HealthState.FAILED
    mc.tick()

    # Tick 2: s1 still failed
    mc.tick()

    # Tick 3: s1 recovers -> avail = 1.0
    graph.get_service("s1").health = HealthState.HEALTHY
    mc.tick()

    assert mc.get_min_availability() == 0.5
    assert mc.get_peak_affected() == 1
    assert mc.get_affected_proportion() == 0.5
    assert mc.get_downtime_ticks() == 2
    assert mc.get_recovery_time() == 2

    summary = mc.get_summary()
    assert summary["min_availability"] == 0.5
    assert summary["peak_affected"] == 1
    assert summary["downtime_ticks"] == 2

    mc.reset()
    assert len(mc.history) == 0
