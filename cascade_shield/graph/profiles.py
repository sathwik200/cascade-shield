"""Domain topology profiles and preset failure scenarios.

Four complete domain profiles: e-commerce, banking, video streaming, and SaaS.
Each profile defines services, dependencies, and four preset failure scenarios.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Optional

from cascade_shield.models.service import (
    ServiceDefinition,
    DependencyEdge,
    FailureScenario,
    Criticality,
    FaultType,
)
from cascade_shield.graph.dependency_graph import DependencyGraph


# ---------------------------------------------------------------------------
# Profile definitions (in-code, also saved to YAML)
# ---------------------------------------------------------------------------

PROFILES: dict[str, dict[str, Any]] = {
    "ecommerce": {
        "name": "E-Commerce Platform",
        "description": "Online retail platform with order processing, payments, and inventory",
        "services": [
            {"id": "api_gateway", "name": "API Gateway", "criticality": "CRITICAL"},
            {"id": "order_service", "name": "Order Service", "criticality": "CRITICAL", "backup": "order_service_backup"},
            {"id": "payment_service", "name": "Payment Service", "criticality": "CRITICAL"},
            {"id": "inventory_service", "name": "Inventory Service", "criticality": "HIGH"},
            {"id": "product_catalog", "name": "Product Catalog", "criticality": "HIGH", "backup": "product_cache"},
            {"id": "product_cache", "name": "Product Cache", "criticality": "MEDIUM"},
            {"id": "notification_service", "name": "Notification Service", "criticality": "LOW"},
            {"id": "user_service", "name": "User Service", "criticality": "HIGH"},
            {"id": "shipping_service", "name": "Shipping Service", "criticality": "MEDIUM"},
            {"id": "database_service", "name": "Database Service", "criticality": "CRITICAL"},
            {"id": "order_service_backup", "name": "Order Backup", "criticality": "HIGH"},
        ],
        "dependencies": [
            {"source": "api_gateway", "target": "order_service", "critical": True},
            {"source": "api_gateway", "target": "product_catalog", "critical": True},
            {"source": "api_gateway", "target": "user_service", "critical": True},
            {"source": "order_service", "target": "payment_service", "critical": True},
            {"source": "order_service", "target": "inventory_service", "critical": True},
            {"source": "order_service", "target": "notification_service", "critical": False},
            {"source": "order_service", "target": "database_service", "critical": True},
            {"source": "payment_service", "target": "database_service", "critical": True},
            {"source": "inventory_service", "target": "database_service", "critical": True},
            {"source": "product_catalog", "target": "database_service", "critical": True},
            {"source": "product_catalog", "target": "product_cache", "critical": False},
            {"source": "shipping_service", "target": "order_service", "critical": True},
            {"source": "shipping_service", "target": "notification_service", "critical": False},
            {"source": "notification_service", "target": "user_service", "critical": False},
            {"source": "order_service_backup", "target": "database_service", "critical": True},
        ],
        "scenarios": [
            {
                "name": "Database Outage",
                "description": "Complete database failure affecting all data-dependent services",
                "failures": [{"service": "database_service", "type": "UNAVAILABLE", "duration": 15, "severity": 1.0}],
            },
            {
                "name": "Payment Gateway Timeout",
                "description": "Payment service experiencing timeouts during peak traffic",
                "failures": [{"service": "payment_service", "type": "TIMEOUT", "duration": 10, "severity": 0.8}],
            },
            {
                "name": "Cascading Order Failure",
                "description": "Order service fails, cascading to dependent services",
                "failures": [{"service": "order_service", "type": "UNAVAILABLE", "duration": 12, "severity": 1.0}],
            },
            {
                "name": "Multi-Service Degradation",
                "description": "Simultaneous issues across inventory and product catalog",
                "failures": [
                    {"service": "inventory_service", "type": "HIGH_LATENCY", "duration": 10, "severity": 0.7},
                    {"service": "product_catalog", "type": "HIGH_ERROR_RATE", "duration": 8, "severity": 0.6},
                ],
            },
        ],
    },
    "banking": {
        "name": "Banking System",
        "description": "Financial services platform with transactions, ledger, and fraud detection",
        "services": [
            {"id": "api_gateway", "name": "API Gateway", "criticality": "CRITICAL"},
            {"id": "auth_service", "name": "Auth Service", "criticality": "CRITICAL", "backup": "auth_service_backup"},
            {"id": "transaction_service", "name": "Transaction Service", "criticality": "CRITICAL"},
            {"id": "ledger_service", "name": "Ledger Service", "criticality": "CRITICAL"},
            {"id": "account_service", "name": "Account Service", "criticality": "HIGH"},
            {"id": "fraud_detection", "name": "Fraud Detection", "criticality": "HIGH"},
            {"id": "audit_service", "name": "Audit Service", "criticality": "MEDIUM"},
            {"id": "notification_service", "name": "Notification Service", "criticality": "LOW"},
            {"id": "database_service", "name": "Database Service", "criticality": "CRITICAL"},
            {"id": "auth_service_backup", "name": "Auth Backup", "criticality": "HIGH"},
        ],
        "dependencies": [
            {"source": "api_gateway", "target": "auth_service", "critical": True},
            {"source": "api_gateway", "target": "transaction_service", "critical": True},
            {"source": "api_gateway", "target": "account_service", "critical": True},
            {"source": "transaction_service", "target": "ledger_service", "critical": True},
            {"source": "transaction_service", "target": "fraud_detection", "critical": True},
            {"source": "transaction_service", "target": "database_service", "critical": True},
            {"source": "transaction_service", "target": "notification_service", "critical": False},
            {"source": "ledger_service", "target": "database_service", "critical": True},
            {"source": "account_service", "target": "database_service", "critical": True},
            {"source": "fraud_detection", "target": "database_service", "critical": True},
            {"source": "audit_service", "target": "database_service", "critical": True},
            {"source": "audit_service", "target": "transaction_service", "critical": False},
            {"source": "auth_service", "target": "database_service", "critical": True},
            {"source": "auth_service_backup", "target": "database_service", "critical": True},
        ],
        "scenarios": [
            {
                "name": "Database Outage",
                "description": "Core database failure in banking system",
                "failures": [{"service": "database_service", "type": "UNAVAILABLE", "duration": 15, "severity": 1.0}],
            },
            {
                "name": "Auth Service Failure",
                "description": "Authentication service becomes unavailable",
                "failures": [{"service": "auth_service", "type": "UNAVAILABLE", "duration": 10, "severity": 1.0}],
            },
            {
                "name": "Transaction Timeout Storm",
                "description": "Transaction service experiencing cascading timeouts",
                "failures": [{"service": "transaction_service", "type": "TIMEOUT", "duration": 12, "severity": 0.9}],
            },
            {
                "name": "Fraud Detection Overload",
                "description": "Fraud detection and ledger under simultaneous stress",
                "failures": [
                    {"service": "fraud_detection", "type": "HIGH_LATENCY", "duration": 10, "severity": 0.8},
                    {"service": "ledger_service", "type": "HIGH_ERROR_RATE", "duration": 8, "severity": 0.7},
                ],
            },
        ],
    },
    "streaming": {
        "name": "Video Streaming Platform",
        "description": "Media streaming service with transcoding, catalog, and recommendations",
        "services": [
            {"id": "api_gateway", "name": "API Gateway", "criticality": "CRITICAL"},
            {"id": "streaming_service", "name": "Streaming Service", "criticality": "CRITICAL", "backup": "streaming_backup"},
            {"id": "transcoding_service", "name": "Transcoding Service", "criticality": "HIGH"},
            {"id": "video_catalog", "name": "Video Catalog", "criticality": "HIGH"},
            {"id": "recommendation_service", "name": "Recommendation Service", "criticality": "MEDIUM"},
            {"id": "content_storage", "name": "Content Storage", "criticality": "CRITICAL"},
            {"id": "user_service", "name": "User Service", "criticality": "HIGH"},
            {"id": "analytics_service", "name": "Analytics Service", "criticality": "LOW"},
            {"id": "streaming_backup", "name": "Streaming Backup", "criticality": "HIGH"},
        ],
        "dependencies": [
            {"source": "api_gateway", "target": "streaming_service", "critical": True},
            {"source": "api_gateway", "target": "video_catalog", "critical": True},
            {"source": "api_gateway", "target": "user_service", "critical": True},
            {"source": "streaming_service", "target": "content_storage", "critical": True},
            {"source": "streaming_service", "target": "transcoding_service", "critical": True},
            {"source": "streaming_service", "target": "analytics_service", "critical": False},
            {"source": "video_catalog", "target": "content_storage", "critical": True},
            {"source": "video_catalog", "target": "recommendation_service", "critical": False},
            {"source": "transcoding_service", "target": "content_storage", "critical": True},
            {"source": "recommendation_service", "target": "user_service", "critical": False},
            {"source": "analytics_service", "target": "user_service", "critical": False},
            {"source": "streaming_backup", "target": "content_storage", "critical": True},
        ],
        "scenarios": [
            {
                "name": "Content Storage Failure",
                "description": "Primary content storage becomes unavailable",
                "failures": [{"service": "content_storage", "type": "UNAVAILABLE", "duration": 15, "severity": 1.0}],
            },
            {
                "name": "Streaming Service Crash",
                "description": "Main streaming service crashes under load",
                "failures": [{"service": "streaming_service", "type": "UNAVAILABLE", "duration": 12, "severity": 1.0}],
            },
            {
                "name": "Transcoding Bottleneck",
                "description": "Transcoding service experiencing high latency",
                "failures": [{"service": "transcoding_service", "type": "HIGH_LATENCY", "duration": 10, "severity": 0.8}],
            },
            {
                "name": "Multi-Service Stress",
                "description": "Catalog errors combined with recommendation timeouts",
                "failures": [
                    {"service": "video_catalog", "type": "HIGH_ERROR_RATE", "duration": 10, "severity": 0.7},
                    {"service": "recommendation_service", "type": "TIMEOUT", "duration": 8, "severity": 0.6},
                ],
            },
        ],
    },
    "saas": {
        "name": "SaaS Platform",
        "description": "Multi-tenant SaaS platform with billing, analytics, and tenant management",
        "services": [
            {"id": "api_gateway", "name": "API Gateway", "criticality": "CRITICAL"},
            {"id": "app_service", "name": "Application Service", "criticality": "CRITICAL", "backup": "app_service_backup"},
            {"id": "database_service", "name": "Database Service", "criticality": "CRITICAL"},
            {"id": "tenant_management", "name": "Tenant Management", "criticality": "HIGH"},
            {"id": "authentication_service", "name": "Authentication Service", "criticality": "CRITICAL"},
            {"id": "billing_service", "name": "Billing Service", "criticality": "HIGH"},
            {"id": "analytics_service", "name": "Analytics Service", "criticality": "MEDIUM"},
            {"id": "notification_service", "name": "Notification Service", "criticality": "LOW"},
            {"id": "audit_service", "name": "Audit Service", "criticality": "MEDIUM"},
            {"id": "app_service_backup", "name": "App Backup", "criticality": "HIGH"},
        ],
        "dependencies": [
            {"source": "api_gateway", "target": "app_service", "critical": True},
            {"source": "api_gateway", "target": "authentication_service", "critical": True},
            {"source": "app_service", "target": "database_service", "critical": True},
            {"source": "app_service", "target": "tenant_management", "critical": True},
            {"source": "app_service", "target": "notification_service", "critical": False},
            {"source": "app_service", "target": "analytics_service", "critical": False},
            {"source": "tenant_management", "target": "database_service", "critical": True},
            {"source": "authentication_service", "target": "database_service", "critical": True},
            {"source": "billing_service", "target": "database_service", "critical": True},
            {"source": "billing_service", "target": "tenant_management", "critical": True},
            {"source": "billing_service", "target": "notification_service", "critical": False},
            {"source": "analytics_service", "target": "database_service", "critical": True},
            {"source": "audit_service", "target": "database_service", "critical": True},
            {"source": "audit_service", "target": "app_service", "critical": False},
            {"source": "app_service_backup", "target": "database_service", "critical": True},
        ],
        "scenarios": [
            {
                "name": "Database Outage",
                "description": "Core database failure affecting all services",
                "failures": [{"service": "database_service", "type": "UNAVAILABLE", "duration": 15, "severity": 1.0}],
            },
            {
                "name": "App Service Crash",
                "description": "Primary application service becomes unavailable",
                "failures": [{"service": "app_service", "type": "UNAVAILABLE", "duration": 12, "severity": 1.0}],
            },
            {
                "name": "Auth Timeout",
                "description": "Authentication service experiencing timeouts",
                "failures": [{"service": "authentication_service", "type": "TIMEOUT", "duration": 10, "severity": 0.8}],
            },
            {
                "name": "Billing and Tenant Stress",
                "description": "Simultaneous billing and tenant management issues",
                "failures": [
                    {"service": "billing_service", "type": "HIGH_ERROR_RATE", "duration": 10, "severity": 0.7},
                    {"service": "tenant_management", "type": "HIGH_LATENCY", "duration": 8, "severity": 0.6},
                ],
            },
        ],
    },
}

DOMAIN_KEYS = list(PROFILES.keys())


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_topology(domain: str) -> DependencyGraph:
    """Build a DependencyGraph from a domain profile name."""
    if domain not in PROFILES:
        raise ValueError(f"Unknown domain: {domain}. Available: {DOMAIN_KEYS}")
    return _build_from_profile(PROFILES[domain])


def _build_from_profile(profile: dict[str, Any]) -> DependencyGraph:
    """Build graph from a profile dict."""
    graph = DependencyGraph()

    for svc_def in profile["services"]:
        crit = Criticality(svc_def.get("criticality", "MEDIUM"))
        definition = ServiceDefinition(
            service_id=svc_def["id"],
            display_name=svc_def["name"],
            criticality=crit,
            backup_service_id=svc_def.get("backup"),
        )
        graph.add_service(definition)

    for dep_def in profile["dependencies"]:
        edge = DependencyEdge(
            source_id=dep_def["source"],
            target_id=dep_def["target"],
            is_critical=dep_def.get("critical", True),
        )
        graph.add_dependency(edge)

    return graph


def get_scenarios(domain: str) -> list[dict[str, Any]]:
    """Get preset failure scenarios for a domain."""
    if domain not in PROFILES:
        raise ValueError(f"Unknown domain: {domain}")
    return PROFILES[domain]["scenarios"]


def build_failure_scenarios(domain: str, scenario_name: str) -> list[FailureScenario]:
    """Build FailureScenario objects from a named preset."""
    scenarios = get_scenarios(domain)
    for sc in scenarios:
        if sc["name"] == scenario_name:
            return [
                FailureScenario(
                    target_service_id=f["service"],
                    fault_type=FaultType(f["type"]),
                    duration_ticks=f.get("duration", 10),
                    severity=f.get("severity", 1.0),
                    description=sc.get("description", ""),
                )
                for f in sc["failures"]
            ]
    raise ValueError(f"Scenario '{scenario_name}' not found in domain '{domain}'")


def get_scenario_names(domain: str) -> list[str]:
    """Get the names of all preset scenarios for a domain."""
    return [sc["name"] for sc in get_scenarios(domain)]


# ---------------------------------------------------------------------------
# YAML export
# ---------------------------------------------------------------------------

def export_profile_yaml(domain: str, path: Path) -> None:
    """Export a domain profile to a YAML file."""
    if domain not in PROFILES:
        raise ValueError(f"Unknown domain: {domain}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(PROFILES[domain], f, default_flow_style=False, sort_keys=False)


def load_profile_yaml(path: Path) -> DependencyGraph:
    """Load a topology from a YAML file."""
    with open(path) as f:
        profile = yaml.safe_load(f)
    return _build_from_profile(profile)
