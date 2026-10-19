"""Typed data models with validated state transitions for Cascade Shield.

All core domain objects are defined here as dataclasses with explicit
validation to prevent invalid states.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from cascade_shield.config import (
    VALID_TRANSITIONS,
    HEALTH_HEALTHY,
    HEALTH_DEGRADED,
    HEALTH_FAILED,
    HEALTH_ISOLATED,
    HEALTH_RECOVERING,
    CB_CLOSED,
    CB_OPEN,
    CB_HALF_OPEN,
    CRIT_CRITICAL,
    CRIT_HIGH,
    CRIT_MEDIUM,
    CRIT_LOW,
    FAULT_UNAVAILABLE,
    FAULT_HIGH_LATENCY,
    FAULT_HIGH_ERROR_RATE,
    FAULT_TIMEOUT,
    CB_FAILURE_THRESHOLD,
    CB_SUCCESS_THRESHOLD,
    CB_COOLDOWN_TICKS,
    RECOVERY_MAX_ATTEMPTS,
    RETRY_MAX_ATTEMPTS,
    RATE_LIMIT_TOKENS_PER_TICK,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class HealthState(str, Enum):
    HEALTHY = HEALTH_HEALTHY
    DEGRADED = HEALTH_DEGRADED
    FAILED = HEALTH_FAILED
    ISOLATED = HEALTH_ISOLATED
    RECOVERING = HEALTH_RECOVERING


class CircuitState(str, Enum):
    CLOSED = CB_CLOSED
    OPEN = CB_OPEN
    HALF_OPEN = CB_HALF_OPEN


class Criticality(str, Enum):
    CRITICAL = CRIT_CRITICAL
    HIGH = CRIT_HIGH
    MEDIUM = CRIT_MEDIUM
    LOW = CRIT_LOW


class FaultType(str, Enum):
    UNAVAILABLE = FAULT_UNAVAILABLE
    HIGH_LATENCY = FAULT_HIGH_LATENCY
    HIGH_ERROR_RATE = FAULT_HIGH_ERROR_RATE
    TIMEOUT = FAULT_TIMEOUT


# ---------------------------------------------------------------------------
# Service Definition (static blueprint)
# ---------------------------------------------------------------------------

@dataclass
class ServiceDefinition:
    """Immutable blueprint for a microservice."""
    service_id: str
    display_name: str
    criticality: Criticality = Criticality.MEDIUM
    backup_service_id: Optional[str] = None
    retry_limit: int = RETRY_MAX_ATTEMPTS
    timeout: float = 5.0
    rate_limit: int = RATE_LIMIT_TOKENS_PER_TICK
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.service_id:
            raise ValueError("service_id must be non-empty")
        if self.retry_limit < 0:
            raise ValueError("retry_limit must be >= 0")
        if self.timeout <= 0:
            raise ValueError("timeout must be > 0")
        if self.rate_limit < 0:
            raise ValueError("rate_limit must be >= 0")


# ---------------------------------------------------------------------------
# Service Instance (mutable runtime state)
# ---------------------------------------------------------------------------

@dataclass
class ServiceInstance:
    """Mutable runtime state for a deployed microservice."""
    definition: ServiceDefinition
    health: HealthState = HealthState.HEALTHY
    circuit_state: CircuitState = CircuitState.CLOSED
    circuit_failure_count: int = 0
    circuit_success_count: int = 0
    circuit_cooldown_remaining: int = 0
    recovery_attempts: int = 0
    traffic_percentage: float = 1.0
    active_failure: Optional[FailureScenario] = None
    failure_ticks_remaining: int = 0
    exhaustion_ticks: int = 0
    is_rate_limited: bool = False
    is_isolated: bool = False
    active_backup_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def service_id(self) -> str:
        return self.definition.service_id

    @property
    def display_name(self) -> str:
        return self.definition.display_name

    @property
    def criticality(self) -> Criticality:
        return self.definition.criticality

    def transition_to(self, new_state: HealthState) -> None:
        """Transition health state with validation."""
        if new_state == self.health:
            return
        allowed = VALID_TRANSITIONS.get(self.health.value, set())
        if new_state.value not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition {self.service_id} from "
                f"{self.health.value} to {new_state.value}"
            )
        self.health = new_state

    def reset(self) -> None:
        """Reset to initial healthy state."""
        self.health = HealthState.HEALTHY
        self.circuit_state = CircuitState.CLOSED
        self.circuit_failure_count = 0
        self.circuit_success_count = 0
        self.circuit_cooldown_remaining = 0
        self.recovery_attempts = 0
        self.traffic_percentage = 1.0
        self.active_failure = None
        self.failure_ticks_remaining = 0
        self.exhaustion_ticks = 0
        self.is_rate_limited = False
        self.is_isolated = False
        self.active_backup_id = None


# ---------------------------------------------------------------------------
# Dependency Edge
# ---------------------------------------------------------------------------

@dataclass
class DependencyEdge:
    """A directed dependency from source to target."""
    source_id: str
    target_id: str
    is_critical: bool = True
    latency_ms: float = 10.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Failure Scenario
# ---------------------------------------------------------------------------

@dataclass
class FailureScenario:
    """Describes a fault to inject."""
    target_service_id: str
    fault_type: FaultType
    duration_ticks: int = 10
    severity: float = 1.0  # 0.0-1.0
    description: str = ""

    def __post_init__(self):
        if self.duration_ticks < 1:
            raise ValueError("duration_ticks must be >= 1")
        self.severity = max(0.0, min(1.0, self.severity))


# ---------------------------------------------------------------------------
# Impact Analysis
# ---------------------------------------------------------------------------

@dataclass
class ImpactAnalysis:
    """Result of a blast-radius analysis."""
    failed_service_id: str
    directly_affected: list[str] = field(default_factory=list)
    transitively_affected: list[str] = field(default_factory=list)
    critical_services_at_risk: list[str] = field(default_factory=list)
    blast_radius: int = 0
    unaffected_services: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Containment Action
# ---------------------------------------------------------------------------

@dataclass
class ContainmentAction:
    """A candidate or executed containment action."""
    action_type: str
    target_service_id: str
    score: float = 0.0
    feasible: bool = True
    explanation: str = ""
    executed: bool = False
    success: bool = False
    timestamp: int = 0

    @property
    def action_id(self) -> str:
        return f"{self.action_type}:{self.target_service_id}:{self.timestamp}"


# ---------------------------------------------------------------------------
# System Event
# ---------------------------------------------------------------------------

@dataclass
class SystemEvent:
    """A logged event in the simulation."""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    tick: int = 0
    event_type: str = ""
    service_id: str = ""
    description: str = ""
    severity: str = "INFO"
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Metric Snapshot
# ---------------------------------------------------------------------------

@dataclass
class MetricSnapshot:
    """Point-in-time metrics for the system."""
    tick: int = 0
    effective_availability: float = 1.0
    critical_availability: float = 1.0
    healthy_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0
    isolated_count: int = 0
    recovering_count: int = 0
    total_services: int = 0
    active_incidents: int = 0
    containment_actions: int = 0
    cascade_count: int = 0


# ---------------------------------------------------------------------------
# Health Check Result
# ---------------------------------------------------------------------------

@dataclass
class HealthCheckResult:
    """Result of a health probe (read-only, no side effects)."""
    service_id: str
    healthy: bool = False
    latency_ms: float = 0.0
    error_rate: float = 0.0
    dependencies_ok: bool = False
    message: str = ""


# ---------------------------------------------------------------------------
# Experiment Config
# ---------------------------------------------------------------------------

@dataclass
class ExperimentConfig:
    """Configuration for a comparison experiment."""
    name: str = ""
    domain: str = "ecommerce"
    scenario_name: str = ""
    duration_ticks: int = 30
    seed: int = 42
    failure_scenarios: list[FailureScenario] = field(default_factory=list)
    description: str = ""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvalidTransitionError(Exception):
    """Raised when an invalid health state transition is attempted."""
    pass


class ServiceNotFoundError(Exception):
    """Raised when a service ID is not found."""
    pass


class ContainmentError(Exception):
    """Raised when a containment action cannot be applied."""
    pass
