"""Metrics visualization components using Plotly."""

from __future__ import annotations

import plotly.graph_objects as go
from cascade_shield.models.service import MetricSnapshot
from cascade_shield.experiment.runner import ScenarioResult, POLICY_LABELS


def create_availability_chart(history: list[MetricSnapshot], width: int = 800, height: int = 340) -> go.Figure:
    """Create interactive line chart for system availability over simulation ticks."""
    fig = go.Figure()

    if not history:
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0a0e27",
            plot_bgcolor="#0d1333",
            annotations=[dict(text="No metric data available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)],
        )
        return fig

    ticks = [s.tick for s in history]
    eff_avail = [round(s.effective_availability * 100, 2) for s in history]
    crit_avail = [round(s.critical_availability * 100, 2) for s in history]

    fig.add_trace(go.Scatter(
        x=ticks,
        y=eff_avail,
        mode="lines+markers",
        name="Effective Availability",
        line=dict(color="#00f2fe", width=3),
        marker=dict(size=6, color="#00f2fe"),
        hovertemplate="Tick %{x}: %{y:.1f}%<extra>Effective</extra>",
    ))

    fig.add_trace(go.Scatter(
        x=ticks,
        y=crit_avail,
        mode="lines+markers",
        name="Critical Services Avail",
        line=dict(color="#a855f7", width=2.5, dash="dash"),
        marker=dict(size=5, color="#a855f7"),
        hovertemplate="Tick %{x}: %{y:.1f}%<extra>Critical</extra>",
    ))

    # Threshold 100% line
    fig.add_hline(y=100, line_dash="dot", line_color="rgba(0, 230, 118, 0.4)", annotation_text="100% SLA Target", annotation_position="top right")

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0a0e27",
        plot_bgcolor="#0d1333",
        margin=dict(l=30, r=20, t=30, b=30),
        width=width,
        height=height,
        xaxis=dict(title="Simulation Tick", showgrid=True, gridcolor="rgba(255,255,255,0.06)", dtick=2),
        yaxis=dict(title="Availability (%)", showgrid=True, gridcolor="rgba(255,255,255,0.06)", range=[0, 105]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return fig


def create_health_distribution_chart(history: list[MetricSnapshot], width: int = 800, height: int = 300) -> go.Figure:
    """Create a stacked area chart representing service health distribution over time."""
    fig = go.Figure()

    if not history:
        return fig

    ticks = [s.tick for s in history]
    healthy = [s.healthy_count for s in history]
    degraded = [s.degraded_count for s in history]
    failed = [s.failed_count for s in history]
    isolated = [s.isolated_count for s in history]
    recovering = [s.recovering_count for s in history]

    traces = [
        ("Healthy", healthy, "#00e676"),
        ("Degraded", degraded, "#ffab00"),
        ("Recovering", recovering, "#2979ff"),
        ("Isolated", isolated, "#aa00ff"),
        ("Failed", failed, "#ff1744"),
    ]

    for name, data, color in traces:
        fig.add_trace(go.Scatter(
            x=ticks,
            y=data,
            mode="lines",
            name=name,
            stackgroup="one",
            line=dict(width=0.5, color=color),
            fillcolor=color,
            hovertemplate=f"{name}: %{{y}}<extra></extra>",
        ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0a0e27",
        plot_bgcolor="#0d1333",
        margin=dict(l=30, r=20, t=25, b=30),
        width=width,
        height=height,
        xaxis=dict(title="Simulation Tick", showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(title="Service Count", showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return fig


def create_policy_comparison_chart(scenario_result: ScenarioResult, width: int = 800, height: int = 380) -> go.Figure:
    """Create side-by-side comparative time-series availability chart for all 3 policies."""
    fig = go.Figure()

    styles = {
        "no_containment": dict(color="#ff1744", width=2, dash="dash", name="No Containment"),
        "simple_circuit_breaker": dict(color="#ffab00", width=2, dash="dot", name="Simple Circuit Breaker"),
        "cascade_shield": dict(color="#00f2fe", width=3.5, dash="solid", name="Cascade Shield"),
    }

    for policy, pr in scenario_result.policy_results.items():
        if not pr.metrics_history:
            continue
        ticks = [s.tick for s in pr.metrics_history]
        avail = [round(s.effective_availability * 100, 2) for s in pr.metrics_history]
        st = styles.get(policy, dict(color="#ffffff", width=2, dash="solid", name=policy))

        fig.add_trace(go.Scatter(
            x=ticks,
            y=avail,
            mode="lines+markers",
            name=st["name"],
            line=dict(color=st["color"], width=st["width"], dash=st["dash"]),
            marker=dict(size=5 if policy == "cascade_shield" else 4, color=st["color"]),
            hovertemplate=f"{st['name']}: %{{y:.1f}}%<extra></extra>",
        ))

    fig.update_layout(
        title=f"Policy Resilience Comparison: {scenario_result.scenario}",
        template="plotly_dark",
        paper_bgcolor="#0a0e27",
        plot_bgcolor="#0d1333",
        margin=dict(l=30, r=20, t=50, b=30),
        width=width,
        height=height,
        xaxis=dict(title="Simulation Tick", showgrid=True, gridcolor="rgba(255,255,255,0.06)", dtick=2),
        yaxis=dict(title="Effective Availability (%)", showgrid=True, gridcolor="rgba(255,255,255,0.06)", range=[0, 105]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return fig


def create_policy_metrics_bar(scenario_result: ScenarioResult, width: int = 800, height: int = 320) -> go.Figure:
    """Create a grouped bar chart comparing key resilience metrics across policies."""
    policies = list(scenario_result.policy_results.keys())
    labels = [POLICY_LABELS.get(p, p) for p in policies]

    min_avails = [scenario_result.policy_results[p].min_availability * 100 for p in policies]
    cascades = [scenario_result.policy_results[p].cascade_count for p in policies]
    downtimes = [scenario_result.policy_results[p].downtime_ticks for p in policies]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=labels,
        y=min_avails,
        name="Min Availability (%)",
        marker_color="#00f2fe",
        text=[f"{v:.1f}%" for v in min_avails],
        textposition="auto",
    ))

    fig.add_trace(go.Bar(
        x=labels,
        y=cascades,
        name="Cascade Count",
        marker_color="#ff1744",
        text=cascades,
        textposition="auto",
    ))

    fig.add_trace(go.Bar(
        x=labels,
        y=downtimes,
        name="Downtime Ticks",
        marker_color="#ffab00",
        text=downtimes,
        textposition="auto",
    ))

    fig.update_layout(
        barmode="group",
        template="plotly_dark",
        paper_bgcolor="#0a0e27",
        plot_bgcolor="#0d1333",
        margin=dict(l=30, r=20, t=30, b=30),
        width=width,
        height=height,
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig
