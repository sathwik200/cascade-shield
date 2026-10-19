"""Topology visualization component using Plotly."""

from __future__ import annotations

import math
# pyrefly: ignore[missing-import]
import plotly.graph_objects as go
import networkx as nx

from cascade_shield.graph.dependency_graph import DependencyGraph
from cascade_shield.models.service import HealthState, Criticality


# Color palette
HEALTH_COLORS = {
    HealthState.HEALTHY: "#00C853",
    HealthState.DEGRADED: "#FFB300",
    HealthState.FAILED: "#FF1744",
    HealthState.ISOLATED: "#AA00FF",
    HealthState.RECOVERING: "#2979FF",
}

CRITICALITY_SIZES = {
    Criticality.CRITICAL: 40,
    Criticality.HIGH: 32,
    Criticality.MEDIUM: 26,
    Criticality.LOW: 20,
}

CRITICALITY_SYMBOLS = {
    Criticality.CRITICAL: "diamond",
    Criticality.HIGH: "square",
    Criticality.MEDIUM: "circle",
    Criticality.LOW: "circle",
}


def create_topology_figure(
    graph: DependencyGraph,
    selected_service: str | None = None,
    highlight_blast: bool = False,
    width: int = 800,
    height: int = 600,
) -> go.Figure:
    """Create an interactive Plotly topology graph.

    Nodes are colored by health state, sized by criticality.
    Edges show dependency direction with arrows.
    """
    G = graph.get_networkx_graph()
    services = graph.services

    if not services:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0a0e27",
            plot_bgcolor="#0a0e27",
            annotations=[{
                "text": "No services to display",
                "xref": "paper", "yref": "paper",
                "x": 0.5, "y": 0.5, "showarrow": False,
                "font": {"size": 16, "color": "#8892b0"},
            }],
        )
        return fig

    # Layout
    try:
        pos = nx.spring_layout(G, seed=42, k=2.5, iterations=60)
    except Exception:
        pos = nx.shell_layout(G)

    # Blast radius highlighting
    blast_services = set()
    if selected_service and highlight_blast and selected_service in services:
        impact = graph.analyze_impact(selected_service)
        blast_services = set(impact.directly_affected) | set(impact.transitively_affected)
        blast_services.add(selected_service)

    # Create edges
    edge_traces = []
    annotations = []

    for edge_def in graph.edges:
        src = edge_def.source_id
        tgt = edge_def.target_id
        if src not in pos or tgt not in pos:
            continue

        x0, y0 = pos[src]
        x1, y1 = pos[tgt]

        is_failover = edge_def.metadata.get("_failover", False)
        is_critical = edge_def.is_critical

        if is_failover:
            color = "#AA00FF"
            dash = "dash"
            width_val = 2
        elif is_critical:
            color = "#4a5568"
            dash = "solid"
            width_val = 2
        else:
            color = "#2d3748"
            dash = "dot"
            width_val = 1

        # If part of blast radius, highlight
        if blast_services and (src in blast_services or tgt in blast_services):
            color = "#FF6B6B"
            width_val = 3

        edge_traces.append(go.Scatter(
            x=[x0, x1, None],
            y=[y0, y1, None],
            mode="lines",
            line=dict(width=width_val, color=color, dash=dash),
            hoverinfo="none",
            showlegend=False,
        ))

        # Arrow annotation
        mid_x = (x0 + x1) / 2
        mid_y = (y0 + y1) / 2
        dx = x1 - x0
        dy = y1 - y0
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0:
            # Place arrow at 70% along the edge
            ax = x0 + 0.7 * dx
            ay = y0 + 0.7 * dy
            annotations.append(dict(
                x=ax + 0.05 * dx / dist,
                y=ay + 0.05 * dy / dist,
                ax=ax - 0.05 * dx / dist,
                ay=ay - 0.05 * dy / dist,
                xref="x", yref="y",
                axref="x", ayref="y",
                showarrow=True,
                arrowhead=3,
                arrowsize=1.5,
                arrowwidth=width_val,
                arrowcolor=color,
            ))

    # Create nodes
    node_x = []
    node_y = []
    node_colors = []
    node_sizes = []
    node_symbols = []
    node_text = []
    node_hover = []
    node_borders = []

    for sid, svc in services.items():
        if sid not in pos:
            continue
        x, y = pos[sid]
        node_x.append(x)
        node_y.append(y)

        color = HEALTH_COLORS.get(svc.health, "#888888")
        node_colors.append(color)
        node_sizes.append(CRITICALITY_SIZES.get(svc.criticality, 24))
        node_symbols.append(CRITICALITY_SYMBOLS.get(svc.criticality, "circle"))
        node_text.append(svc.display_name)

        hover = (
            f"<b>{svc.display_name}</b><br>"
            f"ID: {sid}<br>"
            f"Health: {svc.health.value}<br>"
            f"Criticality: {svc.criticality.value}<br>"
            f"Circuit: {svc.circuit_state.value}<br>"
            f"Traffic: {svc.traffic_percentage:.0%}"
        )
        if svc.active_backup_id:
            hover += f"<br>Active Backup: {svc.active_backup_id}"
        node_hover.append(hover)

        # Border for selected service
        if selected_service and sid == selected_service:
            node_borders.append(dict(color="white", width=3))
        elif blast_services and sid in blast_services:
            node_borders.append(dict(color="#FF6B6B", width=2))
        else:
            node_borders.append(dict(color="rgba(0,0,0,0.3)", width=1))

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        marker=dict(
            size=node_sizes,
            color=node_colors,
            symbol=node_symbols,
            line=dict(
                color=[b["color"] for b in node_borders],
                width=[b["width"] for b in node_borders],
            ),
        ),
        text=node_text,
        textposition="top center",
        textfont=dict(size=10, color="#ccd6f6"),
        hovertext=node_hover,
        hoverinfo="text",
        showlegend=False,
    )

    # Build figure
    fig = go.Figure(data=edge_traces + [node_trace])

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0a0e27",
        plot_bgcolor="#0d1333",
        margin=dict(l=20, r=20, t=30, b=20),
        width=width,
        height=height,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, visible=False),
        annotations=annotations,
        hovermode="closest",
    )

    return fig


def create_health_legend() -> dict[str, str]:
    """Return health state colors for legend display."""
    return {state.value: color for state, color in HEALTH_COLORS.items()}
