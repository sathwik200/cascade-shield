"""Metrics collection and aggregation.

Metric formulas:
- Effective availability = (healthy + 0.5 * degraded) / total
- Critical availability = same formula applied to CRITICAL and HIGH services only
- All calculations handle zero denominators safely.

All metrics are derived from actual simulation state. No data is fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from cascade_shield.models.service import (
    MetricSnapshot,
    HealthState,
    Criticality,
)
from cascade_shield.graph.dependency_graph import DependencyGraph


class MetricsCollector:
    """Collects and aggregates system metrics from simulation state."""

    def __init__(self, graph: DependencyGraph):
        self._graph = graph
        self._history: list[MetricSnapshot] = []
        self._tick = 0

    @property
    def history(self) -> list[MetricSnapshot]:
        return list(self._history)

    def snapshot(self) -> MetricSnapshot:
        """Take a point-in-time snapshot of the system."""
        services = self._graph.services

        total = len(services)
        healthy = 0
        degraded = 0
        failed = 0
        isolated = 0
        recovering = 0
        active_incidents = 0

        for svc in services.values():
            if svc.health == HealthState.HEALTHY:
                healthy += 1
            elif svc.health == HealthState.DEGRADED:
                degraded += 1
            elif svc.health == HealthState.FAILED:
                failed += 1
            elif svc.health == HealthState.ISOLATED:
                isolated += 1
            elif svc.health == HealthState.RECOVERING:
                recovering += 1

            if svc.active_failure is not None:
                active_incidents += 1

        effective_availability = self._calculate_availability(
            healthy, degraded, total
        )
        critical_availability = self._calculate_critical_availability(services)

        snap = MetricSnapshot(
            tick=self._tick,
            effective_availability=effective_availability,
            critical_availability=critical_availability,
            healthy_count=healthy,
            degraded_count=degraded,
            failed_count=failed,
            isolated_count=isolated,
            recovering_count=recovering,
            total_services=total,
            active_incidents=active_incidents,
        )
        self._history.append(snap)
        return snap

    @staticmethod
    def _calculate_availability(healthy: int, degraded: int, total: int) -> float:
        """Calculate effective availability.

        Formula: (healthy + 0.5 * degraded) / total
        """
        if total == 0:
            return 1.0  # No services = vacuously available
        return (healthy + 0.5 * degraded) / total

    def _calculate_critical_availability(self, services: dict) -> float:
        """Calculate availability of CRITICAL and HIGH services only."""
        critical_services = [
            svc for svc in services.values()
            if svc.criticality in (Criticality.CRITICAL, Criticality.HIGH)
        ]
        total = len(critical_services)
        if total == 0:
            return 1.0

        healthy = sum(1 for s in critical_services if s.health == HealthState.HEALTHY)
        degraded = sum(1 for s in critical_services if s.health == HealthState.DEGRADED)

        return (healthy + 0.5 * degraded) / total

    def tick(self) -> MetricSnapshot:
        """Advance tick and take snapshot."""
        self._tick += 1
        return self.snapshot()

    # ----- Aggregation -----

    def get_min_availability(self) -> float:
        """Get the minimum effective availability across all snapshots."""
        if not self._history:
            return 1.0
        return min(s.effective_availability for s in self._history)

    def get_peak_affected(self) -> int:
        """Get the peak number of affected (non-healthy) services."""
        if not self._history:
            return 0
        return max(
            s.total_services - s.healthy_count
            for s in self._history
        )

    def get_affected_proportion(self) -> float:
        """Get the maximum proportion of affected services."""
        if not self._history:
            return 0.0
        peak = self.get_peak_affected()
        total = self._history[-1].total_services if self._history else 0
        if total == 0:
            return 0.0
        return peak / total

    def get_downtime_ticks(self) -> int:
        """Get the number of ticks where availability was below 1.0."""
        return sum(
            1 for s in self._history
            if s.effective_availability < 1.0 - 0.001
        )

    def get_recovery_time(self) -> int:
        """Get the number of ticks from first degradation to full recovery."""
        first_degradation = None
        last_recovery = None

        for snap in self._history:
            if snap.effective_availability < 1.0 - 0.001:
                if first_degradation is None:
                    first_degradation = snap.tick
                last_recovery = snap.tick

        if first_degradation is None:
            return 0
        return (last_recovery or first_degradation) - first_degradation + 1

    def get_summary(self) -> dict:
        """Get aggregated metrics summary."""
        return {
            "min_availability": round(self.get_min_availability(), 4),
            "peak_affected": self.get_peak_affected(),
            "affected_proportion": round(self.get_affected_proportion(), 4),
            "downtime_ticks": self.get_downtime_ticks(),
            "recovery_time_ticks": self.get_recovery_time(),
            "total_snapshots": len(self._history),
        }

    def reset(self) -> None:
        """Reset metrics state."""
        self._history.clear()
        self._tick = 0
