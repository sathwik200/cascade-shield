"""Dependency graph management using NetworkX.

An edge A → B means service A depends on service B.
The graph is never corrupted by failures; routing changes for failover
are tracked separately and restored on reset.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx

from cascade_shield.models.service import (
    ServiceDefinition,
    ServiceInstance,
    DependencyEdge,
    ImpactAnalysis,
    HealthState,
    Criticality,
    ServiceNotFoundError,
)
from cascade_shield.config import (
    CRIT_CRITICAL,
    CRIT_HIGH,
)


class DependencyGraph:
    """Manages the microservice dependency topology."""

    def __init__(self):
        self._graph: nx.DiGraph = nx.DiGraph()
        self._services: dict[str, ServiceInstance] = {}
        self._edges: dict[tuple[str, str], DependencyEdge] = {}
        # Failover routing: maps (source, original_target) -> backup_target
        self._active_routes: dict[tuple[str, str], str] = {}
        # Original edges displaced by failover
        self._original_edges: dict[tuple[str, str], DependencyEdge] = {}

    # ----- Service Registration -----

    def add_service(self, definition: ServiceDefinition) -> ServiceInstance:
        """Register a service and return its runtime instance."""
        if definition.service_id in self._services:
            raise ValueError(f"Service {definition.service_id} already registered")
        instance = ServiceInstance(definition=definition)
        self._services[definition.service_id] = instance
        self._graph.add_node(definition.service_id)
        return instance

    def get_service(self, service_id: str) -> ServiceInstance:
        """Look up a service instance."""
        if service_id not in self._services:
            raise ServiceNotFoundError(f"Service not found: {service_id}")
        return self._services[service_id]

    def has_service(self, service_id: str) -> bool:
        return service_id in self._services

    @property
    def services(self) -> dict[str, ServiceInstance]:
        return dict(self._services)

    @property
    def service_ids(self) -> list[str]:
        return list(self._services.keys())

    # ----- Dependency Registration -----

    def add_dependency(self, edge: DependencyEdge) -> None:
        """Register a dependency: source depends on target."""
        if edge.source_id not in self._services:
            raise ServiceNotFoundError(f"Source not found: {edge.source_id}")
        if edge.target_id not in self._services:
            raise ServiceNotFoundError(f"Target not found: {edge.target_id}")
        if edge.source_id == edge.target_id:
            raise ValueError("Self-dependency not allowed")
        key = (edge.source_id, edge.target_id)
        self._edges[key] = edge
        self._graph.add_edge(
            edge.source_id, edge.target_id,
            is_critical=edge.is_critical,
            latency_ms=edge.latency_ms,
        )

    def get_dependency(self, source_id: str, target_id: str) -> Optional[DependencyEdge]:
        """Get the dependency edge between two services."""
        return self._edges.get((source_id, target_id))

    @property
    def edges(self) -> list[DependencyEdge]:
        return list(self._edges.values())

    # ----- Dependency Queries -----

    def get_dependencies(self, service_id: str) -> list[str]:
        """Services that this service depends on (successors in DiGraph)."""
        if service_id not in self._services:
            raise ServiceNotFoundError(f"Service not found: {service_id}")
        return list(self._graph.successors(service_id))

    def get_critical_dependencies(self, service_id: str) -> list[str]:
        """Critical dependencies of this service."""
        deps = self.get_dependencies(service_id)
        result = []
        for dep_id in deps:
            edge = self._edges.get((service_id, dep_id))
            if edge and edge.is_critical:
                result.append(dep_id)
        return result

    def get_optional_dependencies(self, service_id: str) -> list[str]:
        """Optional (non-critical) dependencies of this service."""
        deps = self.get_dependencies(service_id)
        result = []
        for dep_id in deps:
            edge = self._edges.get((service_id, dep_id))
            if edge and not edge.is_critical:
                result.append(dep_id)
        return result

    def get_direct_dependents(self, service_id: str) -> list[str]:
        """Services that directly depend on this service (predecessors)."""
        if service_id not in self._services:
            raise ServiceNotFoundError(f"Service not found: {service_id}")
        return list(self._graph.predecessors(service_id))

    def get_transitive_dependents(self, service_id: str) -> list[str]:
        """All services that transitively depend on this service."""
        if service_id not in self._services:
            raise ServiceNotFoundError(f"Service not found: {service_id}")
        result = set()
        queue = list(self._graph.predecessors(service_id))
        visited = {service_id}
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            result.add(current)
            for pred in self._graph.predecessors(current):
                if pred not in visited:
                    queue.append(pred)
        return sorted(result)

    # ----- Impact Analysis -----

    def analyze_impact(self, failed_service_id: str) -> ImpactAnalysis:
        """Calculate the blast radius of a service failure."""
        if failed_service_id not in self._services:
            raise ServiceNotFoundError(f"Service not found: {failed_service_id}")

        direct = self.get_direct_dependents(failed_service_id)
        transitive = self.get_transitive_dependents(failed_service_id)
        all_affected = set(direct) | set(transitive)

        critical_at_risk = [
            sid for sid in all_affected
            if self._services[sid].criticality in (Criticality.CRITICAL, Criticality.HIGH)
        ]

        unaffected = [
            sid for sid in self._services
            if sid != failed_service_id and sid not in all_affected
        ]

        return ImpactAnalysis(
            failed_service_id=failed_service_id,
            directly_affected=sorted(direct),
            transitively_affected=sorted(transitive),
            critical_services_at_risk=sorted(critical_at_risk),
            blast_radius=len(all_affected),
            unaffected_services=sorted(unaffected),
        )

    # ----- Failover Routing -----

    def apply_failover(self, source_id: str, original_target_id: str,
                       backup_target_id: str) -> bool:
        """Redirect a dependency from original_target to backup_target.

        Preserves the original edge metadata. Returns True on success.
        """
        if not self.has_service(source_id):
            return False
        if not self.has_service(backup_target_id):
            return False

        original_edge = self._edges.get((source_id, original_target_id))
        if original_edge is None:
            return False

        # Check backup is healthy enough
        backup = self._services.get(backup_target_id)
        if backup is None or backup.health in (HealthState.FAILED, HealthState.ISOLATED):
            return False

        # Don't duplicate if already routed
        route_key = (source_id, original_target_id)
        if route_key in self._active_routes:
            return False

        # Store original edge
        self._original_edges[route_key] = original_edge

        # Add new edge to backup
        backup_edge = DependencyEdge(
            source_id=source_id,
            target_id=backup_target_id,
            is_critical=original_edge.is_critical,
            latency_ms=original_edge.latency_ms,
            metadata={**original_edge.metadata, "_failover": True},
        )
        backup_key = (source_id, backup_target_id)
        if backup_key not in self._edges:
            self._edges[backup_key] = backup_edge
            self._graph.add_edge(
                source_id, backup_target_id,
                is_critical=backup_edge.is_critical,
                latency_ms=backup_edge.latency_ms,
            )

        # Record active route
        self._active_routes[route_key] = backup_target_id
        self._services[source_id].active_backup_id = backup_target_id

        return True

    def restore_route(self, source_id: str, original_target_id: str) -> bool:
        """Restore original dependency, removing the failover route."""
        route_key = (source_id, original_target_id)
        if route_key not in self._active_routes:
            return False

        backup_target_id = self._active_routes[route_key]

        # Remove the failover edge if no other dependency uses it
        backup_key = (source_id, backup_target_id)
        backup_edge = self._edges.get(backup_key)
        if backup_edge and backup_edge.metadata.get("_failover"):
            del self._edges[backup_key]
            if self._graph.has_edge(source_id, backup_target_id):
                self._graph.remove_edge(source_id, backup_target_id)

        # Remove routing record
        del self._active_routes[route_key]
        if route_key in self._original_edges:
            del self._original_edges[route_key]

        self._services[source_id].active_backup_id = None
        return True

    def restore_routes_for_target(self, target_id: str) -> list[tuple[str, str]]:
        """Restore all failover routes where original target was target_id."""
        restored = []
        for (src, orig_tgt) in list(self._active_routes.keys()):
            if orig_tgt == target_id:
                if self.restore_route(src, orig_tgt):
                    restored.append((src, orig_tgt))
        return restored

    def get_active_route(self, source_id: str, target_id: str) -> Optional[str]:
        """Get the current active target for a dependency (backup if routed)."""
        route_key = (source_id, target_id)
        return self._active_routes.get(route_key, None)

    @property
    def active_routes(self) -> dict[tuple[str, str], str]:
        return dict(self._active_routes)

    # ----- Dependency Availability -----

    def is_dependency_available(self, source_id: str, target_id: str) -> bool:
        """Check if a dependency is available, considering failover routing."""
        route_key = (source_id, target_id)
        actual_target = self._active_routes.get(route_key, target_id)
        if actual_target not in self._services:
            return False
        svc = self._services[actual_target]
        if svc.health in (HealthState.FAILED, HealthState.ISOLATED):
            return False
        if svc.health == HealthState.RECOVERING and svc.traffic_percentage < 0.2:
            return False
        return True

    def are_critical_dependencies_available(self, service_id: str) -> bool:
        """Check if all critical dependencies are available."""
        for dep_id in self.get_critical_dependencies(service_id):
            if not self.is_dependency_available(service_id, dep_id):
                return False
        return True

    def are_all_dependencies_available(self, service_id: str) -> bool:
        """Check if all dependencies (critical and optional) are available."""
        for dep_id in self.get_dependencies(service_id):
            if not self.is_dependency_available(service_id, dep_id):
                return False
        return True

    # ----- Topology Validation -----

    def validate(self) -> list[str]:
        """Validate the topology. Returns a list of error messages."""
        errors = []
        # Check for cycles
        if not nx.is_directed_acyclic_graph(self._graph):
            cycles = list(nx.simple_cycles(self._graph))
            for cycle in cycles[:5]:
                errors.append(f"Circular dependency: {' -> '.join(cycle)}")

        # Check backup references
        for sid, svc in self._services.items():
            backup_id = svc.definition.backup_service_id
            if backup_id and backup_id not in self._services:
                errors.append(
                    f"Service {sid} references non-existent backup {backup_id}"
                )
            if backup_id == sid:
                errors.append(f"Service {sid} is its own backup")

        return errors

    # ----- Reset -----

    def reset(self) -> None:
        """Reset all service states and remove routing changes.
        Preserves topology structure.
        """
        # Restore all failover routes
        for route_key in list(self._active_routes.keys()):
            self.restore_route(route_key[0], route_key[1])

        # Reset all services
        for svc in self._services.values():
            svc.reset()

    def clear(self) -> None:
        """Remove everything."""
        self._graph.clear()
        self._services.clear()
        self._edges.clear()
        self._active_routes.clear()
        self._original_edges.clear()

    # ----- Utility -----

    def get_networkx_graph(self) -> nx.DiGraph:
        """Return the underlying NetworkX graph (read-only use)."""
        return self._graph

    @property
    def service_count(self) -> int:
        return len(self._services)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def summary(self) -> dict:
        """Return a summary dict."""
        healthy = sum(
            1 for s in self._services.values()
            if s.health == HealthState.HEALTHY
        )
        degraded = sum(
            1 for s in self._services.values()
            if s.health == HealthState.DEGRADED
        )
        failed = sum(
            1 for s in self._services.values()
            if s.health == HealthState.FAILED
        )
        isolated = sum(
            1 for s in self._services.values()
            if s.health == HealthState.ISOLATED
        )
        recovering = sum(
            1 for s in self._services.values()
            if s.health == HealthState.RECOVERING
        )
        return {
            "total_services": self.service_count,
            "total_edges": self.edge_count,
            "healthy": healthy,
            "degraded": degraded,
            "failed": failed,
            "isolated": isolated,
            "recovering": recovering,
        }
