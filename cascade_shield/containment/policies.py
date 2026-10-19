"""Containment policies: circuit breaker, timeout, retry, rate limiter, bulkhead, isolation.

All policies operate on the simulated service model. They do not interact
with real OS threads or network sockets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from cascade_shield.models.service import (
    ServiceInstance,
    SystemEvent,
    HealthState,
    CircuitState,
    ContainmentAction,
    InvalidTransitionError,
)
from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.config import (
    CB_FAILURE_THRESHOLD,
    CB_SUCCESS_THRESHOLD,
    CB_COOLDOWN_TICKS,
    RETRY_MAX_ATTEMPTS,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    RETRY_BACKOFF_FACTOR,
    RATE_LIMIT_TOKENS_PER_TICK,
    RATE_LIMIT_BUCKET_SIZE,
    BULKHEAD_MAX_CONCURRENT,
    ACTION_OPEN_CIRCUIT_BREAKER,
    ACTION_RATE_LIMIT,
    ACTION_ISOLATE,
    ACTION_RESTART,
    ACTION_FAILOVER,
    ACTION_RETRY_WITH_BACKOFF,
    ACTION_DEFER_AND_ALERT,
    ACTION_RESTORE_TRAFFIC,
)


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Simulated circuit breaker with CLOSED → OPEN → HALF_OPEN → CLOSED lifecycle."""

    def __init__(
        self,
        failure_threshold: int = CB_FAILURE_THRESHOLD,
        success_threshold: int = CB_SUCCESS_THRESHOLD,
        cooldown_ticks: int = CB_COOLDOWN_TICKS,
    ):
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.cooldown_ticks = cooldown_ticks

    def record_failure(self, svc: ServiceInstance) -> bool:
        """Record a failure. Returns True if circuit opened."""
        svc.circuit_failure_count += 1
        svc.circuit_success_count = 0
        if (svc.circuit_state == CircuitState.CLOSED and
                svc.circuit_failure_count >= self.failure_threshold):
            svc.circuit_state = CircuitState.OPEN
            svc.circuit_cooldown_remaining = self.cooldown_ticks
            return True
        if svc.circuit_state == CircuitState.HALF_OPEN:
            svc.circuit_state = CircuitState.OPEN
            svc.circuit_cooldown_remaining = self.cooldown_ticks
            return True
        return False

    def record_success(self, svc: ServiceInstance) -> bool:
        """Record a success. Returns True if circuit closed."""
        svc.circuit_success_count += 1
        svc.circuit_failure_count = 0
        if (svc.circuit_state == CircuitState.HALF_OPEN and
                svc.circuit_success_count >= self.success_threshold):
            svc.circuit_state = CircuitState.CLOSED
            svc.circuit_cooldown_remaining = 0
            return True
        return False

    def tick(self, svc: ServiceInstance) -> bool:
        """Advance cooldown. Returns True if transitioned to HALF_OPEN."""
        if svc.circuit_state == CircuitState.OPEN:
            svc.circuit_cooldown_remaining -= 1
            if svc.circuit_cooldown_remaining <= 0:
                svc.circuit_state = CircuitState.HALF_OPEN
                svc.circuit_failure_count = 0
                svc.circuit_success_count = 0
                return True
        return False

    def open_circuit(self, svc: ServiceInstance) -> None:
        """Manually open the circuit."""
        svc.circuit_state = CircuitState.OPEN
        svc.circuit_cooldown_remaining = self.cooldown_ticks
        svc.circuit_failure_count = self.failure_threshold


# ---------------------------------------------------------------------------
# Timeout Policy
# ---------------------------------------------------------------------------

class TimeoutPolicy:
    """Simulated timeout evaluation."""

    def __init__(self, default_timeout: float = 5.0):
        self.default_timeout = default_timeout

    def check_timeout(self, svc: ServiceInstance, latency_ms: float) -> bool:
        """Returns True if the request would time out."""
        timeout = svc.definition.timeout
        return latency_ms > (timeout * 1000)  # convert s to ms


# ---------------------------------------------------------------------------
# Retry Policy
# ---------------------------------------------------------------------------

@dataclass
class RetryState:
    """Tracks retry state for a service."""
    attempts: int = 0
    next_delay: float = RETRY_BASE_DELAY


class RetryPolicy:
    """Bounded retry with exponential backoff."""

    def __init__(
        self,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        max_delay: float = RETRY_MAX_DELAY,
        backoff_factor: float = RETRY_BACKOFF_FACTOR,
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self._states: dict[str, RetryState] = {}

    def get_state(self, service_id: str) -> RetryState:
        if service_id not in self._states:
            self._states[service_id] = RetryState(next_delay=self.base_delay)
        return self._states[service_id]

    def should_retry(self, service_id: str) -> bool:
        """Check if we should retry (haven't exhausted attempts)."""
        state = self.get_state(service_id)
        return state.attempts < self.max_attempts

    def record_attempt(self, service_id: str) -> float:
        """Record a retry attempt. Returns the delay before next retry."""
        state = self.get_state(service_id)
        state.attempts += 1
        delay = state.next_delay
        state.next_delay = min(
            state.next_delay * self.backoff_factor,
            self.max_delay,
        )
        return delay

    def reset(self, service_id: str) -> None:
        """Reset retry state for a service."""
        self._states.pop(service_id, None)

    def reset_all(self) -> None:
        self._states.clear()


# ---------------------------------------------------------------------------
# Rate Limiter (Token Bucket)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token-bucket rate limiter.

    Each tick refills tokens_per_tick tokens up to bucket_size.
    Each request consumes one token.
    """

    def __init__(
        self,
        tokens_per_tick: int = RATE_LIMIT_TOKENS_PER_TICK,
        bucket_size: int = RATE_LIMIT_BUCKET_SIZE,
    ):
        self.tokens_per_tick = tokens_per_tick
        self.bucket_size = bucket_size
        self._buckets: dict[str, int] = {}

    def _get_tokens(self, service_id: str) -> int:
        if service_id not in self._buckets:
            self._buckets[service_id] = self.bucket_size
        return self._buckets[service_id]

    def allow_request(self, service_id: str) -> bool:
        """Try to consume a token. Returns True if allowed."""
        tokens = self._get_tokens(service_id)
        if tokens > 0:
            self._buckets[service_id] = tokens - 1
            return True
        return False

    def refill(self, service_id: str) -> None:
        """Refill tokens for one tick."""
        current = self._get_tokens(service_id)
        self._buckets[service_id] = min(current + self.tokens_per_tick, self.bucket_size)

    def refill_all(self) -> None:
        for sid in list(self._buckets):
            self.refill(sid)

    def activate(self, service_id: str) -> None:
        """Activate rate limiting by draining most tokens."""
        self._buckets[service_id] = max(1, self.tokens_per_tick // 2)

    def deactivate(self, service_id: str) -> None:
        """Deactivate rate limiting by refilling fully."""
        self._buckets[service_id] = self.bucket_size

    def get_utilization(self, service_id: str) -> float:
        """Get bucket utilization (1.0 = full, 0.0 = empty)."""
        tokens = self._get_tokens(service_id)
        return tokens / self.bucket_size if self.bucket_size > 0 else 0.0

    def reset_all(self) -> None:
        self._buckets.clear()


# ---------------------------------------------------------------------------
# Bulkhead
# ---------------------------------------------------------------------------

class Bulkhead:
    """Simulated concurrency limiter / bulkhead."""

    def __init__(self, max_concurrent: int = BULKHEAD_MAX_CONCURRENT):
        self.max_concurrent = max_concurrent
        self._usage: dict[str, int] = {}

    def acquire(self, service_id: str) -> bool:
        """Try to acquire a concurrency slot."""
        current = self._usage.get(service_id, 0)
        if current < self.max_concurrent:
            self._usage[service_id] = current + 1
            return True
        return False

    def release(self, service_id: str) -> None:
        """Release a concurrency slot."""
        current = self._usage.get(service_id, 0)
        self._usage[service_id] = max(0, current - 1)

    def get_usage(self, service_id: str) -> int:
        return self._usage.get(service_id, 0)

    def get_utilization(self, service_id: str) -> float:
        return self.get_usage(service_id) / self.max_concurrent if self.max_concurrent > 0 else 0.0

    def isolate(self, service_id: str) -> None:
        """Set max usage to block all new requests."""
        self._usage[service_id] = self.max_concurrent

    def reset(self, service_id: str) -> None:
        self._usage.pop(service_id, None)

    def reset_all(self) -> None:
        self._usage.clear()


# ---------------------------------------------------------------------------
# Containment Manager
# ---------------------------------------------------------------------------

class ContainmentManager:
    """Coordinates all containment policies and provides a unified interface."""

    def __init__(self, graph: DependencyGraph):
        self.graph = graph
        self.circuit_breaker = CircuitBreaker()
        self.timeout_policy = TimeoutPolicy()
        self.retry_policy = RetryPolicy()
        self.rate_limiter = RateLimiter()
        self.bulkhead = Bulkhead()
        self._actions: list[ContainmentAction] = []
        self._tick = 0

    @property
    def actions(self) -> list[ContainmentAction]:
        return list(self._actions)

    def execute_action(self, action: ContainmentAction) -> ContainmentAction:
        """Execute a containment action and return it with execution result."""
        action.timestamp = self._tick
        handler = {
            ACTION_OPEN_CIRCUIT_BREAKER: self._execute_open_circuit,
            ACTION_RATE_LIMIT: self._execute_rate_limit,
            ACTION_ISOLATE: self._execute_isolate,
            ACTION_RESTART: self._execute_restart,
            ACTION_FAILOVER: self._execute_failover,
            ACTION_RETRY_WITH_BACKOFF: self._execute_retry,
            ACTION_DEFER_AND_ALERT: self._execute_defer,
            ACTION_RESTORE_TRAFFIC: self._execute_restore,
        }.get(action.action_type)

        if handler:
            action.executed = True
            action.success = handler(action.target_service_id)
        else:
            action.executed = True
            action.success = False
            action.explanation += f" (Unknown action type: {action.action_type})"

        self._actions.append(action)
        return action

    def _execute_open_circuit(self, service_id: str) -> bool:
        """Open the circuit breaker for a service."""
        svc = self.graph.get_service(service_id)
        self.circuit_breaker.open_circuit(svc)
        return True

    def _execute_rate_limit(self, service_id: str) -> bool:
        """Activate rate limiting."""
        svc = self.graph.get_service(service_id)
        svc.is_rate_limited = True
        self.rate_limiter.activate(service_id)
        return True

    def _execute_isolate(self, service_id: str) -> bool:
        """Isolate a service to prevent propagation."""
        svc = self.graph.get_service(service_id)
        try:
            svc.transition_to(HealthState.ISOLATED)
        except InvalidTransitionError:
            svc.health = HealthState.ISOLATED
        svc.is_isolated = True
        svc.circuit_state = CircuitState.OPEN
        self.bulkhead.isolate(service_id)
        return True

    def _execute_restart(self, service_id: str) -> bool:
        """Simulate restarting a service (clears failure, moves to RECOVERING)."""
        svc = self.graph.get_service(service_id)
        svc.active_failure = None
        svc.failure_ticks_remaining = 0
        svc.exhaustion_ticks = 0
        try:
            svc.transition_to(HealthState.RECOVERING)
        except InvalidTransitionError:
            if svc.health == HealthState.ISOLATED:
                svc.is_isolated = False
            svc.health = HealthState.RECOVERING
        svc.circuit_state = CircuitState.HALF_OPEN
        svc.traffic_percentage = 0.0
        return True

    def _execute_failover(self, service_id: str) -> bool:
        """Execute failover to backup service."""
        svc = self.graph.get_service(service_id)
        backup_id = svc.definition.backup_service_id

        if not backup_id:
            return False
        if not self.graph.has_service(backup_id):
            return False

        backup = self.graph.get_service(backup_id)
        if backup.health in (HealthState.FAILED, HealthState.ISOLATED):
            return False

        # Apply failover for all dependents of the failed service
        dependents = self.graph.get_direct_dependents(service_id)
        any_routed = False
        for dep_id in dependents:
            success = self.graph.apply_failover(dep_id, service_id, backup_id)
            if success:
                any_routed = True

        if any_routed:
            svc.active_backup_id = backup_id
        return any_routed

    def _execute_retry(self, service_id: str) -> bool:
        """Enable retry with backoff for a service."""
        if self.retry_policy.should_retry(service_id):
            self.retry_policy.record_attempt(service_id)
            return True
        return False

    def _execute_defer(self, service_id: str) -> bool:
        """Defer action and create an alert."""
        return True  # Always succeeds - it's a passive action

    def _execute_restore(self, service_id: str) -> bool:
        """Restore traffic to a recovering service."""
        svc = self.graph.get_service(service_id)
        if svc.health != HealthState.RECOVERING:
            return False
        # Traffic restoration is handled by recovery manager
        return True

    def tick(self) -> list[SystemEvent]:
        """Advance containment policies by one tick."""
        self._tick += 1
        events: list[SystemEvent] = []

        # Tick circuit breakers
        for svc in self.graph.services.values():
            if self.circuit_breaker.tick(svc):
                events.append(SystemEvent(
                    tick=self._tick,
                    event_type="CIRCUIT_HALF_OPEN",
                    service_id=svc.service_id,
                    description="Circuit breaker transitioned to HALF_OPEN after cooldown",
                    severity="INFO",
                ))

        # Refill rate limiter tokens
        self.rate_limiter.refill_all()

        return events

    def get_circuit_states(self) -> dict[str, str]:
        """Get circuit breaker states for all services."""
        return {
            sid: svc.circuit_state.value
            for sid, svc in self.graph.services.items()
        }

    def get_containment_summary(self, service_id: str) -> dict:
        """Get containment status summary for a service."""
        svc = self.graph.get_service(service_id)
        retry_state = self.retry_policy.get_state(service_id)
        return {
            "circuit_state": svc.circuit_state.value,
            "circuit_failures": svc.circuit_failure_count,
            "circuit_cooldown": svc.circuit_cooldown_remaining,
            "is_rate_limited": svc.is_rate_limited,
            "rate_limiter_utilization": self.rate_limiter.get_utilization(service_id),
            "is_isolated": svc.is_isolated,
            "bulkhead_utilization": self.bulkhead.get_utilization(service_id),
            "retry_attempts": retry_state.attempts,
            "retry_can_retry": self.retry_policy.should_retry(service_id),
            "recovery_attempts": svc.recovery_attempts,
            "traffic_percentage": svc.traffic_percentage,
            "active_backup": svc.active_backup_id,
        }

    def reset(self) -> None:
        """Reset all containment state."""
        self.circuit_breaker = CircuitBreaker()
        self.timeout_policy = TimeoutPolicy()
        self.retry_policy.reset_all()
        self.rate_limiter.reset_all()
        self.bulkhead.reset_all()
        self._actions.clear()
        self._tick = 0
