"""Unit tests for cascade_shield.engine.decision_engine."""

import pytest
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.models.service import (
    ServiceDefinition,
    DependencyEdge,
    Criticality,
    HealthState,
    CircuitState,
    FailureScenario,
    FaultType,
)
from cascade_shield.containment.policies import ContainmentManager
from cascade_shield.engine.decision_engine import DecisionEngine, ALL_ACTIONS
from cascade_shield.config import (
    ACTION_OPEN_CIRCUIT_BREAKER,
    ACTION_RATE_LIMIT,
    ACTION_FAILOVER,
    ACTION_RESTART,
    ACTION_ISOLATE,
)


def build_engine_setup():
    graph = DependencyGraph()
    graph.add_service(ServiceDefinition("gateway", "API Gateway", Criticality.CRITICAL))
    graph.add_service(ServiceDefinition("order_service", "Order Service", Criticality.CRITICAL, backup_service_id="order_backup"))
    graph.add_service(ServiceDefinition("order_backup", "Order Backup", Criticality.HIGH))
    graph.add_service(ServiceDefinition("database", "Database Service", Criticality.CRITICAL))

    graph.add_dependency(DependencyEdge("gateway", "order_service", is_critical=True))
    graph.add_dependency(DependencyEdge("order_service", "database", is_critical=True))
    graph.add_dependency(DependencyEdge("order_backup", "database", is_critical=True))

    cm = ContainmentManager(graph)
    engine = DecisionEngine(graph, cm)
    return graph, cm, engine


def test_evaluate_all_actions():
    graph, cm, engine = build_engine_setup()

    candidates = engine.evaluate("order_service")
    assert len(candidates) == len(ALL_ACTIONS)

    # Candidates should be sorted descending by score
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_feasibility_rules():
    graph, cm, engine = build_engine_setup()
    svc = graph.get_service("order_service")

    # 1. Circuit breaker already OPEN
    svc.circuit_state = CircuitState.OPEN
    cand_cb = next(c for c in engine.evaluate("order_service") if c.action_type == ACTION_OPEN_CIRCUIT_BREAKER)
    assert not cand_cb.feasible
    assert cand_cb.score < 0  # Penalty applied

    # 2. Rate limit already applied
    svc.circuit_state = CircuitState.CLOSED
    svc.is_rate_limited = True
    cand_rl = next(c for c in engine.evaluate("order_service") if c.action_type == ACTION_RATE_LIMIT)
    assert not cand_rl.feasible

    # 3. Failover infeasible when backup is FAILED
    graph.get_service("order_backup").health = HealthState.FAILED
    cand_fo = next(c for c in engine.evaluate("order_service") if c.action_type == ACTION_FAILOVER)
    assert not cand_fo.feasible


def test_recommend_and_explanations():
    graph, cm, engine = build_engine_setup()

    # Fail database service
    db = graph.get_service("database")
    db.health = HealthState.FAILED
    db.active_failure = FailureScenario("database", FaultType.UNAVAILABLE, duration_ticks=10)

    rec = engine.recommend("database")
    assert rec.feasible
    assert rec.explanation != ""
    assert "Database Service" in rec.explanation

    # Decision log has recorded evaluation
    assert len(engine.decision_log) >= 1
    assert engine.decision_log[-1]["service_id"] == "database"

    engine.reset()
    assert len(engine.decision_log) == 0
