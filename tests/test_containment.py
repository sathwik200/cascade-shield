"""Unit tests for containment policies and ContainmentManager."""

import pytest
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.models.service import (
    ServiceDefinition,
    DependencyEdge,
    ServiceInstance,
    HealthState,
    CircuitState,
    ContainmentAction,
)
from cascade_shield.containment.policies import (
    CircuitBreaker,
    TimeoutPolicy,
    RetryPolicy,
    RateLimiter,
    Bulkhead,
    ContainmentManager,
)
from cascade_shield.config import (
    ACTION_OPEN_CIRCUIT_BREAKER,
    ACTION_RATE_LIMIT,
    ACTION_ISOLATE,
    ACTION_RESTART,
    ACTION_FAILOVER,
    ACTION_RETRY_WITH_BACKOFF,
    ACTION_DEFER_AND_ALERT,
    ACTION_RESTORE_TRAFFIC,
)


def test_circuit_breaker_lifecycle():
    cb = CircuitBreaker(failure_threshold=3, success_threshold=2, cooldown_ticks=3)
    svc = ServiceInstance(definition=ServiceDefinition("s1", "S1"))

    assert svc.circuit_state == CircuitState.CLOSED

    # Failures 1 & 2: still CLOSED
    assert not cb.record_failure(svc)
    assert not cb.record_failure(svc)
    assert svc.circuit_state == CircuitState.CLOSED

    # Failure 3: opens circuit
    assert cb.record_failure(svc)
    assert svc.circuit_state == CircuitState.OPEN
    assert svc.circuit_cooldown_remaining == 3

    # Cooldown ticks
    assert not cb.tick(svc)  # 2 left
    assert not cb.tick(svc)  # 1 left
    assert cb.tick(svc)      # 0 left -> HALF_OPEN
    assert svc.circuit_state == CircuitState.HALF_OPEN

    # Success 1 in HALF_OPEN
    assert not cb.record_success(svc)
    assert svc.circuit_state == CircuitState.HALF_OPEN

    # Success 2 in HALF_OPEN -> CLOSED
    assert cb.record_success(svc)
    assert svc.circuit_state == CircuitState.CLOSED


def test_timeout_policy():
    tp = TimeoutPolicy()
    svc = ServiceInstance(definition=ServiceDefinition("s1", "S1", timeout=2.0))

    assert not tp.check_timeout(svc, 1500.0)
    assert tp.check_timeout(svc, 2500.0)


def test_retry_policy():
    rp = RetryPolicy(max_attempts=3, base_delay=1.0, backoff_factor=2.0, max_delay=10.0)

    assert rp.should_retry("s1")
    d1 = rp.record_attempt("s1")
    assert d1 == 1.0

    assert rp.should_retry("s1")
    d2 = rp.record_attempt("s1")
    assert d2 == 2.0

    assert rp.should_retry("s1")
    d3 = rp.record_attempt("s1")
    assert d3 == 4.0

    # Exhausted
    assert not rp.should_retry("s1")

    # Reset
    rp.reset("s1")
    assert rp.should_retry("s1")


def test_rate_limiter():
    rl = RateLimiter(tokens_per_tick=5, bucket_size=10)

    # Allow 10 requests
    for _ in range(10):
        assert rl.allow_request("s1")
    # 11th request denied
    assert not rl.allow_request("s1")

    # Refill 5 tokens
    rl.refill("s1")
    for _ in range(5):
        assert rl.allow_request("s1")
    assert not rl.allow_request("s1")

    # Activate restricts tokens
    rl.activate("s1")
    assert rl.get_utilization("s1") <= 0.5


def test_bulkhead():
    bh = Bulkhead(max_concurrent=2)

    assert bh.acquire("s1")
    assert bh.acquire("s1")
    assert not bh.acquire("s1")  # Cap reached

    bh.release("s1")
    assert bh.acquire("s1")

    bh.isolate("s1")
    assert bh.get_utilization("s1") == 1.0


def test_containment_manager_actions():
    graph = DependencyGraph()
    graph.add_service(ServiceDefinition("gateway", "Gateway"))
    graph.add_service(ServiceDefinition("orders", "Orders", backup_service_id="orders_backup"))
    graph.add_service(ServiceDefinition("orders_backup", "Orders Backup"))

    graph.add_dependency(DependencyEdge("gateway", "orders", is_critical=True))

    cm = ContainmentManager(graph)

    # 1. Open Circuit Breaker
    act_cb = ContainmentAction(ACTION_OPEN_CIRCUIT_BREAKER, "orders")
    res_cb = cm.execute_action(act_cb)
    assert res_cb.success
    assert graph.get_service("orders").circuit_state == CircuitState.OPEN

    # 2. Rate Limit
    act_rl = ContainmentAction(ACTION_RATE_LIMIT, "gateway")
    res_rl = cm.execute_action(act_rl)
    assert res_rl.success
    assert graph.get_service("gateway").is_rate_limited

    # 3. Failover
    act_fo = ContainmentAction(ACTION_FAILOVER, "orders")
    res_fo = cm.execute_action(act_fo)
    assert res_fo.success
    assert graph.get_active_route("gateway", "orders") == "orders_backup"

    # 4. Isolate
    act_iso = ContainmentAction(ACTION_ISOLATE, "orders")
    res_iso = cm.execute_action(act_iso)
    assert res_iso.success
    assert graph.get_service("orders").health == HealthState.ISOLATED

    # 5. Restart
    act_rst = ContainmentAction(ACTION_RESTART, "orders")
    res_rst = cm.execute_action(act_rst)
    assert res_rst.success
    assert graph.get_service("orders").health == HealthState.RECOVERING

    # 6. Retry
    act_retry = ContainmentAction(ACTION_RETRY_WITH_BACKOFF, "gateway")
    res_retry = cm.execute_action(act_retry)
    assert res_retry.success

    # 7. Defer
    act_defer = ContainmentAction(ACTION_DEFER_AND_ALERT, "gateway")
    res_defer = cm.execute_action(act_defer)
    assert res_defer.success

    summary = cm.get_containment_summary("orders")
    assert "circuit_state" in summary
